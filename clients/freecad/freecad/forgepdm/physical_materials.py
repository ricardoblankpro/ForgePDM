"""Native FreeCAD density snapshots and final-solid mass; GUI thread only."""

import hashlib
import json
import math
import re
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def native_uuid(value):
    digest = hashlib.sha256(canonical(value).encode()).hexdigest()
    return str(uuid5(NAMESPACE_URL, "forgepdm-density-v1:" + digest))


def density(material):
    import FreeCAD as App

    value = float(material.getPhysicalValue("Density") / App.Units.Quantity("1 kg/m^3"))
    if not math.isfinite(value) or not 0 < value <= 1000000:
        raise ValueError("material has no valid density")
    return format(Decimal(format(value, ".12g")).normalize(), "f")


def material_choices():
    import Materials

    result = []
    for material in Materials.MaterialManager().Materials.values():
        if "ForgePDM" in material.Directory.split("/"):
            continue
        try:
            density_value = density(material)
        except Exception:
            continue
        result.append(
            {
                "version": 1,
                "source_uuid": material.UUID,
                "name": material.Name,
                "density_kg_m3": density_value,
                "author": material.Author or "",
                "license": material.License or "",
            }
        )
    return sorted(result, key=lambda value: (value["name"].casefold(), value["source_uuid"]))


def unassigned_binding():
    return {
        "version": 1,
        "source_uuid": "00000000-0000-0000-0000-000000000000",
        "name": "Unassigned",
        "density_kg_m3": None,
        "author": "ForgePDM",
        "license": "",
    }


def card(value):
    uuid = native_uuid(value)
    lines = [
        "---",
        "General:",
        "  UUID: " + json.dumps(uuid),
        "  Name: " + json.dumps(value["name"]),
        "  Author: " + json.dumps(value.get("author", "")),
        "  License: " + json.dumps(value.get("license", "")),
        "  Description: "
        + json.dumps("ForgePDM frozen density snapshot of " + value["source_uuid"]),
        "Models:",
        "  Density:",
        '    UUID: "454661e5-265b-4320-8e6f-fcf6223ac3af"',
        "    Density: " + json.dumps((value["density_kg_m3"] or "") + " kg/m^3"),
    ]
    if value["density_kg_m3"] is None:
        lines = lines[:7] + ["Models: {}"]
    return "\n".join(lines) + "\n"


def ensure_native(value):
    import Materials

    manager = Materials.MaterialManager()
    uuid = native_uuid(value)
    material = None
    try:
        material = manager.getMaterial(uuid)
        if value["density_kg_m3"] is not None and density(material) != value["density_kg_m3"]:
            raise ValueError("managed native material density differs from its snapshot")
    except LookupError:
        pass
    libraries = [entry for entry in manager.MaterialLibraries if entry[0] == "User"]
    if not libraries:
        raise ValueError("FreeCAD User material library is unavailable")
    root = Path(libraries[0][1]) / "ForgePDM" / uuid
    root.mkdir(parents=True, exist_ok=True)
    name = (
        re.sub(r"[^\w .()-]", "_", value["name"], flags=re.UNICODE)[:100].strip(" .") or "Material"
    )
    path = root / (name + " (ForgePDM).FCMat")
    data = card(value)
    if path.exists():
        if path.is_symlink() or path.read_text() != data:
            raise ValueError("managed material cache differs; preserve it and inspect")
    else:
        with path.open("x", encoding="utf-8") as output:
            output.write(data)
    if material is not None and path.exists():
        return material
    manager.refresh()
    material = manager.getMaterial(uuid)
    if value["density_kg_m3"] is not None and density(material) != value["density_kg_m3"]:
        raise ValueError("native snapshot density could not be restored")
    return material


def final_solids(document):
    candidates = []
    for obj in document.Objects:
        if obj.TypeId in ("App::Link", "Assembly::AssemblyLink") or not obj.isDerivedFrom(
            "Part::Feature"
        ):
            continue
        if any(
            parent.TypeId == "PartDesign::Body" for parent in getattr(obj, "InListRecursive", ())
        ):
            continue
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull() or not shape.Solids:
            continue
        candidates.append(obj)
    return [
        obj
        for obj in candidates
        if not any(
            other is not obj and other in getattr(obj, "InListRecursive", ())
            for other in candidates
        )
    ]


def _set(metadata, name, value):
    if not hasattr(metadata, name):
        metadata.addProperty("App::PropertyString", name, "ForgePDM")
    if getattr(metadata, name) != value:
        setattr(metadata, name, value)
    if hasattr(metadata, "setEditorMode"):
        metadata.setEditorMode(name, 1)


def read(metadata):
    try:
        return json.loads(getattr(metadata, "PDMPartPhysicalData", "") or "null")
    except (ValueError, TypeError):
        return None


def apply(document, metadata, binding, assign=True):
    previous = read(metadata)
    objects = final_solids(document) if binding else []
    records = []
    reason = ""
    mass = None
    if binding:
        native = ensure_native(binding)
        if assign:
            for obj in objects:
                obj.ShapeMaterial = native
        if not objects:
            reason = "No final solid geometry"
        elif len(objects) > 100:
            reason = "Too many final solids"
        else:
            for index, obj in enumerate(objects):
                shape = obj.Shape
                if not shape.isValid() or not math.isfinite(shape.Volume) or shape.Volume <= 0:
                    reason = "Invalid final solid geometry"
                    break
                if (
                    obj.ShapeMaterial.UUID != native_uuid(binding)
                    or density(obj.ShapeMaterial) != binding["density_kg_m3"]
                ):
                    raise ValueError("Native material changed; assign the catalog material again")
                if any(shape.common(other.Shape).Volume > 1e-7 for other in objects[:index]):
                    reason = "Final solids overlap"
                    break
                records.append(
                    {
                        "name": obj.Name,
                        "volume_mm3": str(shape.Volume),
                        "native_uuid": obj.ShapeMaterial.UUID,
                    }
                )
            if not reason:
                volume = sum((Decimal(r["volume_mm3"]) for r in records), Decimal(0))
                mass = str(volume * Decimal(binding["density_kg_m3"]) / Decimal(1000000000))
    else:
        reason = "No linked physical material"
        # Keep unrelated manually assigned materials intact; only remove our own tracked assignments.
        if previous and previous.get("physical_material"):
            for obj in document.Objects:
                if obj.TypeId in ("App::Link", "Assembly::AssemblyLink") or not obj.isDerivedFrom(
                    "Part::Feature"
                ):
                    continue
                if obj.ShapeMaterial.UUID == native_uuid(previous["physical_material"]):
                    obj.ShapeMaterial = ensure_native(unassigned_binding())
    value = {
        "version": 1,
        "revision_id": metadata.RevisionId,
        "physical_material": binding,
        "objects": records if not reason else [],
        "mass_kg": mass,
        "reason": reason,
    }
    _set(metadata, "PDMPartPhysicalData", canonical(value))
    _set(metadata, "PDMPartMassKg", format(float(mass), ".8g") if mass else "")
    _set(metadata, "PDMPartMassStatus", reason or "Calculated from final solids")
    return value


def refresh(document, metadata):
    value = read(metadata)
    if value is None:
        return None
    # New final solids inherit the same single material; changing an existing assignment is explicit.
    binding = value.get("physical_material")
    if binding:
        previous = {r["name"] for r in value.get("objects", [])}
        for obj in final_solids(document):
            if obj.Name not in previous:
                obj.ShapeMaterial = ensure_native(binding)
    return apply(document, metadata, binding, assign=False)


def registration_dialog(description=None):
    from .ui import QtWidgets, execute_dialog, parent_window

    values = material_choices()
    if not values:
        raise ValueError("No FreeCAD materials with valid density were found")
    dialog = QtWidgets.QDialog(parent_window())
    dialog.setWindowTitle(
        "Register Raw Material" if description is None else "Link Physical Material"
    )
    layout = QtWidgets.QFormLayout(dialog)
    text = QtWidgets.QLineEdit(description or "")
    text.setMaxLength(1000)
    layout.addRow("Catalog description", text)
    if description is not None:
        text.setReadOnly(True)
    choices = QtWidgets.QComboBox()
    choices.setEditable(True)
    choices.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
    for value in values:
        choices.addItem(value["name"] + " — " + value["density_kg_m3"] + " kg/m³", value)
    layout.addRow("Physical material", choices)
    label = QtWidgets.QLabel()
    layout.addRow("Density", label)

    def update():
        value = choices.currentData()
        label.setText((value["density_kg_m3"] + " kg/m³") if value else "")

    choices.currentIndexChanged.connect(update)
    update()
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )

    def accept():
        if not text.text().strip() or choices.findText(choices.currentText()) < 0:
            QtWidgets.QMessageBox.warning(
                dialog, "Material", "Enter a description and select a material from the list."
            )
            return
        dialog.accept()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    layout.addRow(buttons)
    dialog.resize(650, 180)
    accepted = execute_dialog(dialog)
    result = (text.text().strip(), choices.currentData()) if accepted else None
    dialog.deleteLater()
    return result


def preload(path):
    """Register the file's frozen card before FreeCAD resolves UUID-only properties."""
    from zipfile import ZipFile, is_zipfile
    from xml.etree import ElementTree as ET

    if not is_zipfile(path):
        return
    with ZipFile(path) as archive:
        info = archive.getinfo("Document.xml")
        if info.file_size > 16 * 1024**2:
            raise ValueError("native XML too large")
        data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("invalid native XML")
    root = ET.fromstring(data)
    if any(
        node.get("uuid") == native_uuid(unassigned_binding())
        for node in root.findall(".//PropertyMaterial")
    ):
        ensure_native(unassigned_binding())
    for obj in root.findall("./ObjectData/Object"):
        if obj.get("name") != "ForgePDM_Metadata":
            continue
        for prop in obj.findall("./Properties/Property"):
            if prop.get("name") == "PDMPartPhysicalData":
                value = prop.find("String")
                text = value.get("value", "") if value is not None else ""
                if text:
                    if len(text) > 64000:
                        raise ValueError("physical metadata too large")
                    record = json.loads(text)
                    if record.get("physical_material"):
                        ensure_native(record["physical_material"])

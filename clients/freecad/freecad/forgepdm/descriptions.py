"""Small, undoable description metadata for managed engineering documents."""

import json


def local(document):
    metadata = document.getObject("ForgePDM_Metadata")
    raw = getattr(metadata, "PDMDescriptionData", "") if metadata else ""
    if not raw:
        return None
    try:
        value = json.loads(raw)
        if value.get("version") in (1, 2) and value.get("revision_id") == metadata.RevisionId:
            return value
    except (ValueError, AttributeError, TypeError):
        pass
    return None


def apply(
    document, metadata, current, description, material_revision_id=None, physical_material=None
):
    value = {
        "version": 2,
        "physical_material": physical_material,
        "revision_id": metadata.RevisionId,
        "description": description,
        "material_revision_id": material_revision_id,
        "expected_token": current["token"],
    }
    document.openTransaction("Set ForgePDM description")
    try:
        for field in ("PDMDescriptionData", "PDMDescription"):
            if not hasattr(metadata, field):
                metadata.addProperty("App::PropertyString", field, "ForgePDM")
        metadata.PDMDescriptionData = json.dumps(value, sort_keys=True)
        metadata.PDMDescription = description
        # Legacy proposals remain stored on the server; the simple workflow supersedes local processing.
        if hasattr(metadata, "PDMMaterialInputs"):
            metadata.PDMMaterialInputs = ""
        if hasattr(metadata, "PDMFinishedMassKg"):
            metadata.PDMFinishedMassKg = ""
        if getattr(metadata, "ItemNumber", "").startswith("P"):
            from . import physical_materials

            document.recompute()
            physical_materials.apply(document, metadata, physical_material)
        document.recompute()
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        raise
    return value


def prepare(document, metadata, current):
    """Adopt server text for an untouched document; preserve an explicit local edit."""
    value = local(document)
    if value is None:
        apply(
            document,
            metadata,
            current,
            current["description"],
            current["material_revision_id"],
            current.get("physical_material"),
        )
    elif (
        value["description"] == current["description"]
        and value["material_revision_id"] == current["material_revision_id"]
        and (
            value.get("version") == 1
            or value.get("physical_material") == current.get("physical_material")
        )
        and (
            value.get("version") == 1
            or (
                getattr(metadata, "ItemNumber", "").startswith("P")
                and not getattr(metadata, "PDMPartPhysicalData", "")
            )
        )
    ):
        # Older working copies have description metadata but no density/mass
        # evidence. Adopt the server snapshot only when text and M pin agree;
        # differing local edits retain their original concurrency token.
        apply(
            document,
            metadata,
            current,
            current["description"],
            current["material_revision_id"],
            current.get("physical_material"),
        )
    elif (
        value["description"] == current["description"]
        and value["material_revision_id"] == current["material_revision_id"]
        and value.get("physical_material") == current.get("physical_material")
    ):
        # Refresh only the concurrency token, allowing a repeated upload.
        value["expected_token"] = current["token"]
        metadata.PDMDescriptionData = json.dumps(value, sort_keys=True)

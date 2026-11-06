"""Conservative FCStd inspection/rewriting; no FreeCAD imports or file extraction."""

import os
import re
import xml.etree.ElementTree as ET
from copy import copy
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

from .techdraw import embedded_templates


class CADIntegrityError(Exception):
    """The native file cannot be reconstructed safely by the supported adapter."""

    code = "cad_validation_failed"
    server_mutation_started = False


def inspect(path):
    try:
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 50000 or sum(entry.file_size for entry in entries) > 2 * 1024**3:
                raise CADIntegrityError(
                    "Native CAD archive exceeds the supported inspection limits"
                )
            names = [entry.filename for entry in entries]
            if any(
                PurePosixPath(name).is_absolute()
                or ".." in PurePosixPath(name).parts
                or "\\" in name
                or ":" in name
                for name in names
            ):
                raise CADIntegrityError("Native CAD archive contains an unsafe member path")
            if len(names) != len(set(names)) or names.count("Document.xml") != 1:
                raise CADIntegrityError("Native CAD archive has duplicate/missing document entries")
            if archive.getinfo("Document.xml").file_size > 16 * 1024**2:
                raise CADIntegrityError("Native CAD document XML is too large")
            data = archive.read("Document.xml")
    except (BadZipFile, KeyError, OSError) as error:
        raise CADIntegrityError("The native dataset is not a readable FCStd document") from error
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise CADIntegrityError("Native CAD document XML contains unsupported entity declarations")
    try:
        tree = ET.fromstring(data)
    except ET.ParseError as error:
        raise CADIntegrityError("Native CAD document XML is invalid") from error
    if tree.tag != "Document" or tree.find("Objects") is None or tree.find("ObjectData") is None:
        raise CADIntegrityError("Native CAD document structure is unsupported")
    if any("{" in node.tag for node in tree.iter()):
        raise CADIntegrityError("Namespaced native CAD XML is unsupported")
    if any("#" in node.get("expression", "") for node in tree.iter("Expression")):
        raise CADIntegrityError("Cross-document expressions require a dedicated reference adapter")
    objects = {node.get("name"): node.get("type") for node in tree.findall("./Objects/Object")}
    try:
        with ZipFile(path) as archive:
            template_properties = embedded_templates(archive, tree, objects, CADIntegrityError)
    except (BadZipFile, OSError, RuntimeError) as error:
        raise CADIntegrityError("Embedded TechDraw template could not be read") from error
    references = []
    for obj in tree.findall("./ObjectData/Object"):
        for prop in obj.findall("./Properties/Property"):
            for link in prop.iter("XLink"):
                if not link.get("file"):
                    continue
                proxy = obj.find("./Properties/Property[@name='Proxy']/Python")
                fastener = (
                    objects.get(obj.get("name")) == "Part::FeaturePython"
                    and proxy is not None
                    and proxy.get("module") == "FastenersCmd"
                    and proxy.get("class", "").startswith("FS")
                    and prop.get("name") == "BaseObject"
                    and prop.get("type") == "App::PropertyXLinkSub"
                    and re.fullmatch(r"(?:Edge|Face|Vertex)[1-9][0-9]*", link.get("sub", ""))
                    is not None
                    and not list(link)
                    and link.get("count") in (None, "0")
                )
                if not fastener and (
                    objects.get(obj.get("name")) not in ("App::Link", "Assembly::AssemblyLink")
                    or prop.get("name") != "LinkedObject"
                    or prop.get("type") != "App::PropertyXLink"
                    or link.get("sub")
                    or link.get("count") not in (None, "0")
                    or list(link)
                ):
                    raise CADIntegrityError(
                        "Unsupported external CAD reference: {}.{}. "
                        "This version supports whole-object App::Link references only.".format(
                            obj.get("name"), prop.get("name")
                        )
                    )
                if not link.get("name"):
                    raise CADIntegrityError("External CAD reference has no target object name")
                references.append(
                    {
                        "object_name": obj.get("name"),
                        "property_name": prop.get("name"),
                        "target_object_name": link.get("name"),
                        "file": link.get("file"),
                        "element": link,
                        **({"target_subelement": link.get("sub")} if fastener else {}),
                    }
                )
            if prop.get("type") in ("App::PropertyFile", "App::PropertyPath"):
                if (obj.get("name"), prop.get("name")) in template_properties:
                    continue
                values = [node.get("value", "") for node in prop]
                if any(values):
                    raise CADIntegrityError(
                        "External file assets require an adapter: {}.{}".format(
                            obj.get("name"), prop.get("name")
                        )
                    )
    keys = [(reference["object_name"], reference["property_name"]) for reference in references]
    if len(keys) != len(set(keys)):
        raise CADIntegrityError("Native CAD file has duplicate external link occurrences")
    return tree, references


def validate(path, references, source_path=None):
    tree, actual = inspect(path)
    expected = {(entry["object_name"], entry["property_name"]): entry for entry in references}
    if len(expected) != len(references) or set(expected) != {
        (entry["object_name"], entry["property_name"]) for entry in actual
    }:
        raise CADIntegrityError(
            "Native external links do not match the recorded reference manifest"
        )
    for entry in actual:
        reference = expected[(entry["object_name"], entry["property_name"])]
        if entry["target_object_name"] != reference["target_object_name"] or entry.get(
            "target_subelement"
        ) != reference.get("target_subelement"):
            raise CADIntegrityError("Native link target object differs from the recorded manifest")
        if source_path is not None and "target_path" in reference:
            actual_path = (Path(source_path).parent / entry["file"]).resolve()
            if actual_path != Path(reference["target_path"]).resolve():
                raise CADIntegrityError("A CAD reference changed while preparing the upload")
    return tree, actual


def rewrite(source, destination, references, target_paths, checkpoint=lambda: None):
    """Rewrite only owned working copies, before FreeCAD can open stale paths."""
    tree, actual = validate(source, references)
    for entry in actual:
        reference = next(
            value
            for value in references
            if value["object_name"] == entry["object_name"]
            and value["property_name"] == entry["property_name"]
        )
        target = target_paths[reference["target_file_id"]]
        relative = os.path.relpath(target, Path(destination).parent).replace(os.sep, "/")
        entry["element"].set("file", relative)
    xml = ET.tostring(tree, encoding="utf-8", xml_declaration=True)
    with ZipFile(source) as incoming, ZipFile(destination, "x") as outgoing:
        for entry in incoming.infolist():
            checkpoint()
            with outgoing.open(copy(entry), "w") as output:
                if entry.filename == "Document.xml":
                    output.write(xml)
                else:
                    with incoming.open(entry) as input_file:
                        while chunk := input_file.read(1024 * 1024):
                            checkpoint()
                            output.write(chunk)

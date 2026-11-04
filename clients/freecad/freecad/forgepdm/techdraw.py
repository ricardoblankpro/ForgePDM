"""Bounded validation of TechDraw SVG templates embedded in FCStd archives."""

import base64
import binascii
from pathlib import PurePosixPath
import re
import xml.etree.ElementTree as ET

MAX_TEMPLATE_BYTES = 16 * 1024**2
SVG = "http://www.w3.org/2000/svg"


def _resource(value, fail):
    value = value.strip()
    if not value or value.startswith("#"):
        return
    if value.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
        try:
            if base64.b64decode(re.sub(r"\s+", "", value.split(",", 1)[1]), validate=True):
                return
        except (ValueError, binascii.Error):
            pass
    fail("Template references an external or unsupported resource; embed images as PNG/JPEG")


def validate_svg(data, fail):
    if not data or len(data) > MAX_TEMPLATE_BYTES or b"\0" in data:
        fail("Embedded SVG is empty, too large or uses an unsupported encoding")
    if (
        b"<!DOCTYPE" in data.upper()
        or b"<!ENTITY" in data.upper()
        or b"<?XML-STYLESHEET" in data.upper()
    ):
        fail("Embedded SVG has unsupported DTD/entity declarations")
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        fail("Embedded template is not valid SVG XML")
    if root.tag not in ("svg", "{" + SVG + "}svg"):
        fail("Embedded template root is not SVG")
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in ("script", "foreignobject"):
            fail("Embedded SVG contains unsupported active content")
        for name, value in node.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                fail("Embedded SVG contains unsupported event handlers")
            if local in ("href", "src"):
                _resource(value, fail)
        css_properties = {
            "style",
            "fill",
            "stroke",
            "filter",
            "clip-path",
            "mask",
            "cursor",
            "marker",
            "marker-start",
            "marker-mid",
            "marker-end",
            "color-profile",
        }
        values = [
            value
            for name, value in node.attrib.items()
            if name.rsplit("}", 1)[-1].lower() in css_properties
            or re.search(r"url\s*\(", value, re.IGNORECASE)
        ]
        if tag == "style":
            values.append("".join(node.itertext()))
        for value in values:
            # CSS escapes can disguise external references; no CSS decoding is guessed.
            if "\\" in value or re.search(r"@import\b", value, re.IGNORECASE):
                fail("Embedded SVG contains unsupported CSS imports or escapes")
            for url in re.findall(r"url\s*\((.*?)\)", value, re.IGNORECASE | re.DOTALL):
                _resource(url.strip().strip("\"'"), fail)


def embedded_templates(archive, tree, objects, error_type):
    """Return only Template properties proven to have a self-contained PageResult."""
    allowed = set()
    for obj in tree.findall("./ObjectData/Object"):
        name = obj.get("name")
        if objects.get(name) != "TechDraw::DrawSVGTemplate":
            continue

        def fail(message):
            raise error_type(
                "TechDraw template '{}': {}. Save a complete self-contained template before uploading.".format(
                    name, message
                )
            )

        properties = obj.findall("./Properties/Property")
        templates = [p for p in properties if p.get("name") == "Template"]
        results = [p for p in properties if p.get("name") == "PageResult"]
        if len(templates) != 1 or templates[0].get("type") != "App::PropertyFile":
            fail("Unsupported Template property")
        if len(results) != 1 or results[0].get("type") != "App::PropertyFileIncluded":
            fail("Missing embedded PageResult")
        included = list(results[0])
        if len(included) != 1 or included[0].tag != "FileIncluded":
            fail("Invalid embedded PageResult")
        filename = included[0].get("file", "")
        path = PurePosixPath(filename)
        if (
            not filename
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in filename
            or ":" in filename
        ):
            fail("Unsafe embedded SVG member path")
        try:
            info = archive.getinfo(filename)
        except KeyError:
            fail("Embedded SVG member is missing")
        if info.is_dir() or info.file_size > MAX_TEMPLATE_BYTES:
            fail("Embedded SVG member is invalid or too large")
        validate_svg(archive.read(info), fail)
        allowed.add((name, "Template"))
    return allowed

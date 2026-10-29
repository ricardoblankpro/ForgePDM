"""Offline manifest checks and deterministic addon-only ZIP packaging.

Run with the addon's development dependencies, never inside FreeCAD.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import etree


ADDON_ROOT = Path(__file__).resolve().parents[1]
VENDOR = Path(__file__).resolve().parent / "vendor"
NAMESPACE = "https://wiki.freecad.org/Package_Metadata"
NS = {"m": NAMESPACE}
TOP_FILES = ("package.xml", "pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md")


def _installed_file(root, relative):
    if not relative:
        raise ValueError("Resource path is required")
    path = root / relative
    if "\\" in relative or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Resource escapes addon root: {relative}")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Missing or linked resource: {relative}")
    return path


def validate(root=ADDON_ROOT):
    root = Path(root)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    manifest = etree.parse(str(root / "package.xml"), parser)
    if manifest.docinfo.doctype:
        raise ValueError("Manifest must not contain a DTD")

    schema_bytes = (VENDOR / "manifest.xsd").read_bytes()
    provenance = json.loads((VENDOR / "provenance.json").read_text())
    if hashlib.sha256(schema_bytes).hexdigest() != provenance["sha256"]:
        raise ValueError("Vendored schema checksum differs from provenance")
    # The official v1.0 schema has no targetNamespace. XSD's chameleon include
    # binds those unchanged declarations to the official template namespace.
    schema = etree.XMLSchema(etree.parse(str(VENDOR / "template-namespace.xsd"), parser))
    schema.assertValid(manifest)

    package = manifest.getroot()
    if package.tag != f"{{{NAMESPACE}}}package" or package.get("format") != "1":
        raise ValueError("Expected the template's format-1 manifest namespace")
    # Upstream's repeating choice does not enforce the required field counts.
    for name in (
        "name",
        "version",
        "date",
        "description",
        "icon",
        "content",
        "freecadmin",
        "pythonmin",
    ):
        fields = package.findall(f"m:{name}", NS)
        if len(fields) != 1 or (name != "content" and not (fields[0].text or "").strip()):
            raise ValueError(f"Manifest requires exactly one {name}")
    for name in ("maintainer", "license"):
        if not package.findtext(f"m:{name}", namespaces=NS):
            raise ValueError(f"Missing {name}")
    if package.findtext("m:name", namespaces=NS) != "ForgePDM":
        raise ValueError("Unexpected addon identity")
    workbenches = package.findall("m:content/m:workbench", NS)
    if len(workbenches) != 1 or len(package.find("m:content", NS)) != 1:
        raise ValueError("Expected exactly one Workbench content item")
    workbench = workbenches[0]
    if workbench.findtext("m:classname", namespaces=NS) != "ForgePDMWorkbench":
        raise ValueError("Workbench class mismatch")
    if workbench.findtext("m:subdirectory", namespaces=NS) != "freecad/forgepdm":
        raise ValueError("Workbench directory mismatch")
    if workbench.findtext("m:name", namespaces=NS) != "ForgePDM":
        raise ValueError("Workbench name mismatch")
    icon = workbench.findtext("m:icon", namespaces=NS)
    if not icon:
        raise ValueError("Workbench icon is required")
    _installed_file(root, "freecad/forgepdm/" + icon)
    _installed_file(root, package.findtext("m:icon", namespaces=NS))
    for license_node in package.findall("m:license", NS):
        _installed_file(root, license_node.get("file", ""))
    if not package.findall("m:url[@type='repository']", NS):
        raise ValueError("Repository URL is required")

    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    version = package.findtext("m:version", namespaces=NS)
    module = ast.parse((root / "freecad/forgepdm/__init__.py").read_text())
    versions = [
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        )
    ]
    if project["version"] != version or versions != [version]:
        raise ValueError("Manifest, project and Python versions must match")
    if project.get("dependencies"):
        raise ValueError("The addon must not require separately installed runtime packages")
    if project["requires-python"] != ">=" + package.findtext("m:pythonmin", namespaces=NS):
        raise ValueError("Python minimum differs between manifest and project")
    if (root / "freecad/__init__.py").exists():
        raise ValueError("freecad must remain a shared implicit namespace")
    for old in ("ForgePDM/InitGui.py", "InitGui.py", "Init.py"):
        if (root / old).exists():
            raise ValueError(f"Duplicate legacy initialization: {old}")
    for name in TOP_FILES:
        _installed_file(root, name)
    return version


def distribution_files(root):
    root = Path(root)
    files = [root / name for name in TOP_FILES]
    for directory, suffixes in (
        ("freecad/forgepdm", {".py", ".svg", ".ts", ".qm"}),
        ("Documentation", {".md"}),
    ):
        for path in (root / directory).rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError(f"Distribution must not contain symlinks: {path}")
            if path.is_file() and path.suffix in suffixes:
                files.append(path)
    for path in files:
        _installed_file(root, path.relative_to(root).as_posix())
    return sorted(files)


def build(destination, root=ADDON_ROOT):
    root, destination = Path(root), Path(destination)
    validate(root)
    files = distribution_files(root)
    if destination.resolve() in [path.resolve() for path in files]:
        raise ValueError("Output must not replace an addon source file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".zip.part")
    os.close(descriptor)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                # Stable timestamps, order, permissions and compression.
                entry = ZipInfo(path.relative_to(root).as_posix(), (2020, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = ZIP_DEFLATED
                archive.writestr(entry, path.read_bytes())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "build"))
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "check":
        print(f"ForgePDM {validate()}: manifest and layout valid (namespace bridge applied)")
    else:
        version = validate()
        output = arguments.output or ADDON_ROOT / "dist" / f"ForgePDM-{version}.zip"
        print(build(output))


if __name__ == "__main__":
    main()

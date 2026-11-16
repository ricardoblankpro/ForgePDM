"""Offline manifest checks and deterministic addon-only ZIP packaging.

Run with the addon's development dependencies, never inside FreeCAD.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import tempfile
import tomllib
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from lxml import etree


ADDON_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ADDON_ROOT.parents[1]
DOCUMENTATION_ROOT = PROJECT_ROOT / "docs"
SOURCE_URL = "https://github.com/ricardoblankpro/ForgePDM/blob/master/"
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


def documentation_files(documentation_root):
    """Only current user/operations docs belong in the installed client."""
    documentation_root = Path(documentation_root)
    user = documentation_root / "user"
    server = documentation_root / "operations/server.md"
    if not user.is_dir() or not server.is_file():
        raise ValueError("Canonical user/operations documentation is missing")
    files = [server] + sorted(path for path in user.rglob("*") if path.suffix in (".md", ".csv"))
    for path in files:
        _installed_file(documentation_root, path.relative_to(documentation_root).as_posix())
    return files


def document_links(text, source_name, archive_name, names):
    """Map repository-relative links to installed docs or canonical online sources."""

    def rewrite(match):
        target = match.group(2)
        if target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            return match.group(0)
        path, marker, anchor = target.partition("#")
        source = posixpath.normpath(posixpath.join(posixpath.dirname(source_name), path))
        if source in names:
            destination = posixpath.relpath(names[source], posixpath.dirname(archive_name) or ".")
        else:
            if source.startswith(("../", "/")):
                raise ValueError("Documentation link escapes the source repository: " + target)
            destination = SOURCE_URL + quote(source, safe="/")
        return match.group(1) + destination + (marker + anchor if marker else "") + match.group(3)

    return re.sub(r"(!?\[[^\]]*\]\()([^\)]+)(\))", rewrite, text)


def release_check(root=ADDON_ROOT):
    """Machine-checkable prerequisites, separate from preview package validation."""
    validate(root)
    root = Path(root)
    manifest = etree.parse(str(root / "package.xml")).getroot()
    problems = []
    license_id = manifest.findtext("m:license", namespaces=NS)
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    if license_id == "UNLICENSED" or str(project.get("license", "")).startswith("LicenseRef-"):
        problems.append("owner-approved project licensing is unset")
    elif project.get("license") != license_id:
        problems.append("manifest/Python license identifiers disagree")
    if not any("@" in node.get("email", "") for node in manifest.findall("m:maintainer", NS)):
        problems.append("owner-approved public maintainer email is unset")
    repository = manifest.find("m:url[@type='repository']", NS)
    monorepo = (
        repository is not None
        and (repository.text or "").removesuffix(".git").rstrip("/")
        == "https://github.com/ricardoblankpro/ForgePDM"
        and repository.get("branch") == "master"
    )
    if root.resolve() == ADDON_ROOT.resolve() or monorepo:
        problems.append(
            "approve/export an addon-only distribution source; the checkout addon is nested"
        )
    if problems:
        raise ValueError("Release prerequisites: " + "; ".join(problems))
    return validate(root)


def build(destination, root=ADDON_ROOT, documentation_root=DOCUMENTATION_ROOT):
    root, destination = Path(root), Path(destination)
    validate(root)
    files = distribution_files(root)
    if destination.resolve() in [path.resolve() for path in files]:
        raise ValueError("Output must not replace an addon source file")
    entries = {
        path.relative_to(root).as_posix(): (
            path,
            "clients/freecad/" + path.relative_to(root).as_posix(),
        )
        for path in files
    }
    for path in documentation_files(documentation_root):
        relative = path.relative_to(documentation_root).as_posix()
        name = "Documentation/" + relative
        if name in entries:
            raise ValueError("Duplicate packaged documentation: " + name)
        entries[name] = (path, "docs/" + relative)
    names = {source: name for name, (_, source) in entries.items()}
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".zip.part")
    os.close(descriptor)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for name, (path, source) in sorted(entries.items()):
                # Stable timestamps, order, permissions and compression.
                entry = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = ZIP_DEFLATED
                content = path.read_bytes()
                if path.suffix == ".md":
                    content = document_links(content.decode("utf-8"), source, name, names).encode(
                        "utf-8"
                    )
                archive.writestr(entry, content)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "build", "release-check"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--root", type=Path, default=ADDON_ROOT)
    arguments = parser.parse_args()
    if arguments.command == "check":
        print(
            f"ForgePDM {validate(arguments.root)}: manifest and layout valid (namespace bridge applied)"
        )
    elif arguments.command == "release-check":
        try:
            print(f"ForgePDM {release_check(arguments.root)}: release metadata prerequisites pass")
        except ValueError as error:
            parser.exit(2, str(error) + "\n")
    else:
        version = validate(arguments.root)
        output = arguments.output or ADDON_ROOT / "dist" / f"ForgePDM-{version}.zip"
        print(build(output, arguments.root))


if __name__ == "__main__":
    main()

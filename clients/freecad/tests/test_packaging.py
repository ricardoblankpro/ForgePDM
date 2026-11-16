"""Check the actual installable archive, including negative manifest cases."""

import hashlib
import shutil
import subprocess
import sys
from zipfile import ZipFile

from lxml import etree
import pytest


def test_reproducible_archive_and_isolated_import(addon_tools, addon_root, tmp_path):
    first = addon_tools.build(tmp_path / "first.zip")
    second = addon_tools.build(tmp_path / "second.zip")
    assert (
        hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    )
    installed = tmp_path / "Mod" / "ForgePDM"
    with ZipFile(first) as archive:
        names = set(archive.namelist())
        assert {"package.xml", "freecad/forgepdm/init_gui.py", "LICENSE"} <= names
        assert "freecad/__init__.py" not in names
        assert not any(
            name.startswith(("src/", "tests/", "tools/", "references/", "."))
            or "__pycache__" in name
            or name.endswith((".pyc", ".sqlite3"))
            for name in names
        )
        archive.extractall(installed)
    # No site-packages, editable installation, backend, FreeCAD, or Qt available.
    script = """
import sys
sys.path.insert(0, sys.argv[1])
import freecad
import freecad.forgepdm
import freecad.forgepdm.api
import freecad.forgepdm.session
import freecad.forgepdm.fcstd
import freecad.forgepdm.workspace
import freecad.forgepdm.part_checkin
import freecad.forgepdm.cad
from freecad.forgepdm.resources import icon_path
from pathlib import Path
assert freecad.__file__ is None
assert Path(icon_path()).is_file()
assert not {'FreeCAD', 'FreeCADGui', 'PySide', 'PySide6', 'forgepdm', 'sqlite3'} & set(sys.modules)
"""
    subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(installed)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    # Validation also works against the extracted distribution, not just source.
    assert addon_tools.validate(installed) == addon_tools.validate(addon_root)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<version>", "<version>invalid-"),
        ("<format-does-not-exist/>", ""),
        ("<classname>ForgePDMWorkbench</classname>", "<classname>DifferentWorkbench</classname>"),
        ("<name>ForgePDM</name>", ""),
        ("<pythonmin>3.11.0</pythonmin>", "<pythonmin>3.10.0</pythonmin>"),
        ("<tag>PDM</tag>", "<unexpected>PDM</unexpected>"),
        ("<date>", "<date>invalid-"),
        ("<icon>resources/icons/forgepdm.svg</icon>", "<icon>missing.svg</icon>"),
        ("freecad/forgepdm/resources/icons/forgepdm.svg", "../outside.svg"),
    ],
)
def test_invalid_manifest_rejected(addon_tools, addon_root, tmp_path, old, new):
    source = tmp_path / "addon"
    shutil.copytree(
        addon_root, source, ignore=shutil.ignore_patterns(".venv", "dist", "__pycache__")
    )
    manifest = source / "package.xml"
    text = manifest.read_text()
    if old == "<format-does-not-exist/>":
        text = text.replace('format="1"', 'format="2"')
    else:
        assert old in text
        text = text.replace(old, new, 1)
    manifest.write_text(text)
    with pytest.raises((ValueError, etree.DocumentInvalid)):
        addon_tools.build(tmp_path / "invalid.zip", source)
    assert not (tmp_path / "invalid.zip").exists()


def test_missing_icon_and_duplicate_legacy_loader_rejected(addon_tools, addon_root, tmp_path):
    source = tmp_path / "addon"
    shutil.copytree(
        addon_root, source, ignore=shutil.ignore_patterns(".venv", "dist", "__pycache__")
    )
    loader = source / "InitGui.py"
    loader.write_text("raise RuntimeError('old loader')")
    with pytest.raises(ValueError, match="legacy"):
        addon_tools.validate(source)
    loader.unlink()
    (source / "freecad/forgepdm/resources/icons/forgepdm.svg").unlink()
    with pytest.raises(ValueError, match="resource"):
        addon_tools.validate(source)


def test_symlink_and_source_overwrite_rejected(addon_tools, addon_root, tmp_path):
    source = tmp_path / "addon"
    shutil.copytree(
        addon_root, source, ignore=shutil.ignore_patterns(".venv", "dist", "__pycache__")
    )
    with pytest.raises(ValueError, match="source file"):
        addon_tools.build(source / "package.xml", source)
    link = source / "freecad/forgepdm/leak.py"
    link.symlink_to(addon_root / "tools/addon.py")
    with pytest.raises(ValueError, match="symlink"):
        addon_tools.build(tmp_path / "linked.zip", source)


def test_translation_sources_cover_command_resources(addon_root):
    import ast

    tree = ast.parse((addon_root / "freecad/forgepdm/commands.py").read_text())
    strings = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and any(
            isinstance(target, ast.Name) and target.id in {"menu_text", "tooltip"}
            for target in node.targets
        )
        and node.value.value
    }
    assert len(strings) >= 15
    catalog = etree.parse(
        str(addon_root / "freecad/forgepdm/resources/translations/ForgePDM_en.ts")
    )
    assert strings <= set(catalog.xpath("//message/source/text()"))
    for icon in (addon_root / "freecad/forgepdm/resources/icons").glob("*.svg"):
        assert etree.parse(str(icon)).getroot().tag == "{http://www.w3.org/2000/svg}svg"


def test_archive_contains_canonical_guides_with_local_links(addon_tools, tmp_path):
    import posixpath
    import re

    archive_path = addon_tools.build(tmp_path / "docs.zip")
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "Documentation/user/bom.md" in names
        assert "Documentation/user/examples/supplier-reference-mass.csv" in names
        assert "Documentation/operations/server.md" in names
        assert not any(name.startswith("Documentation/history/") for name in names)
        for name in names:
            if not name.endswith(".md"):
                continue
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", archive.read(name).decode()):
                if target.startswith("#") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                    continue
                destination = posixpath.normpath(
                    posixpath.join(posixpath.dirname(name), target.split("#")[0])
                )
                assert destination in names, (name, target)
        readme = archive.read("README.md").decode()
        assert "Documentation/user/install.md" in readme
        assert "https://github.com/ricardoblankpro/ForgePDM/blob/master/CONTRIBUTING.md" in readme


def test_missing_or_linked_canonical_documentation_is_rejected(addon_tools, tmp_path):
    with pytest.raises(ValueError, match="documentation is missing"):
        addon_tools.build(tmp_path / "missing.zip", documentation_root=tmp_path / "absent")
    docs = tmp_path / "docs"
    (docs / "user").mkdir(parents=True)
    (docs / "operations").mkdir()
    (docs / "operations/server.md").write_text("# Server")
    (docs / "user/leak.md").symlink_to(__file__)
    with pytest.raises(ValueError, match="linked resource|escapes addon root"):
        addon_tools.build(tmp_path / "linked-docs.zip", documentation_root=docs)


def test_release_check_rejects_incomplete_preview_metadata(addon_tools, addon_root, tmp_path):
    root = tmp_path / "addon"
    shutil.copytree(addon_root, root, ignore=shutil.ignore_patterns(".venv", "dist", "__pycache__"))
    manifest = root / "package.xml"
    tree = etree.parse(str(manifest))
    for maintainer in tree.findall("m:maintainer", addon_tools.NS):
        maintainer.attrib.pop("email", None)
    tree.write(str(manifest), encoding="UTF-8", xml_declaration=True)
    with pytest.raises(ValueError, match="maintainer email"):
        addon_tools.release_check(root)


def test_copying_an_archive_does_not_approve_the_monorepo_distribution_source(
    addon_tools, tmp_path
):
    archive = addon_tools.build(tmp_path / "preview.zip")
    extracted = tmp_path / "preview"
    with ZipFile(archive) as bundle:
        bundle.extractall(extracted)
    with pytest.raises(ValueError, match="addon-only distribution source"):
        addon_tools.release_check(extracted)

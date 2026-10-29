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
    assert addon_tools.validate(installed) == "0.1.0"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<version>0.1.0</version>", "<version>0.1.1</version>"),
        ("<format-does-not-exist/>", ""),
        ("<classname>ForgePDMWorkbench</classname>", "<classname>DifferentWorkbench</classname>"),
        ("<name>ForgePDM</name>", ""),
        ("<pythonmin>3.11.0</pythonmin>", "<pythonmin>3.10.0</pythonmin>"),
        ("<tag>PDM</tag>", "<unexpected>PDM</unexpected>"),
        ("<date>2026-10-29</date>", "<date>invalid</date>"),
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
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "translate"
        and isinstance(node.args[1], ast.Constant)
    }
    catalog = etree.parse(
        str(addon_root / "freecad/forgepdm/resources/translations/ForgePDM_en.ts")
    )
    assert strings <= set(catalog.xpath("//message/source/text()"))
    for icon in (addon_root / "freecad/forgepdm/resources/icons").glob("*.svg"):
        assert etree.parse(str(icon)).getroot().tag == "{http://www.w3.org/2000/svg}svg"

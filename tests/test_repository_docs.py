"""Contributor checks catch missing installed/source documentation and metadata drift."""

import importlib.util
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repository_docs", ROOT / "tools/check_docs.py")
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


def test_repository_links_versions_and_native_paths():
    assert DOCS.check(ROOT) == []


def test_link_checker_accepts_external_and_detects_missing_target_and_anchor(tmp_path):
    (tmp_path / "guide.md").write_text("# Guide\n\n## Details\n")
    source = tmp_path / "README.md"
    source.write_text("# Read\n[ok](guide.md#details) [web](https://example.invalid/x)\n")
    assert DOCS.link_errors(tmp_path) == []
    source.write_text(source.read_text() + "[missing](gone.md) [bad](guide.md#unknown)\n")
    errors = DOCS.link_errors(tmp_path)
    assert len(errors) == 2
    assert "Missing link target" in errors[0] and "Missing heading anchor" in errors[1]


def test_handoff_drift_is_rejected_without_initializing_a_database(tmp_path):
    for relative in [
        "pyproject.toml",
        "clients/freecad/pyproject.toml",
        "clients/freecad/package.xml",
        "clients/freecad/freecad/forgepdm/__init__.py",
        "src/forgepdm/infrastructure/database.py",
        "DEVELOPMENT_STATUS.md",
    ]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    assert DOCS.version_errors(tmp_path) == []
    status = tmp_path / "DEVELOPMENT_STATUS.md"
    content = status.read_text()
    schema = re.search(r"- Database schema: \*\*([0-9]+)\*\*", content).group(1)
    status.write_text(
        content.replace(f"- Database schema: **{schema}**", "- Database schema: **0**")
    )
    assert DOCS.version_errors(tmp_path) == [
        f"Current handoff does not declare Database schema {schema}"
    ]
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_approved_package_license_and_contact_boundaries():
    import tomllib
    from xml.etree import ElementTree

    backend = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    addon = tomllib.loads((ROOT / "clients/freecad/pyproject.toml").read_text())["project"]
    manifest = ElementTree.parse(ROOT / "clients/freecad/package.xml").getroot()
    namespace = "{https://wiki.freecad.org/Package_Metadata}"
    assert backend["license"] == "AGPL-3.0-or-later"
    assert addon["license"] == manifest.findtext(namespace + "license") == "LGPL-2.1-or-later"
    assert manifest.find(namespace + "maintainer").get("email") == "ricardoblankpro@gmail.com"
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in (ROOT / "clients/freecad/LICENSE").read_text()
    assert (ROOT / "LICENSE").stat().st_size > 30000
    assert (ROOT / "clients/freecad/LICENSE").stat().st_size > 20000

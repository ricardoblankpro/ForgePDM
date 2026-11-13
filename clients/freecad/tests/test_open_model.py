"""Exact snapshot defaults and workspace validation without a CAD runtime."""

import json

import pytest

from freecad.forgepdm import settings
from freecad.forgepdm.open_model import snapshots, validate_workspace
from freecad.forgepdm.workspace import WorkspaceError


def test_snapshot_default_is_explicit_newest_and_ignores_non_cad():
    def dataset(key, date, kind="native_cad"):
        return {"id": key, "created_at": date, "dataset_type": kind, "files": [{"id": key}]}

    old = dataset("old", "2026-01-01")
    new = dataset("new", "2026-05-01")
    assert snapshots([new, old, dataset("pdf", "2026-06-01", "drawing")]) == [
        (new, new["files"][0]),
        (old, old["files"][0]),
    ]
    assert snapshots([]) == []


def test_workspace_rejects_wrong_server_corruption_and_configuration_folder(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert validate_workspace(str(root), "http://server") == str(root)
    admin = root / ".forgepdm"
    admin.mkdir()
    identity = admin / "identity.json"
    identity.write_text(json.dumps({"server_url": "http://other"}))
    with pytest.raises(WorkspaceError, match="another server"):
        validate_workspace(root, "http://server")
    identity.write_text("invalid")
    with pytest.raises(WorkspaceError, match="inspection"):
        validate_workspace(root, "http://server")
    identity.write_text(json.dumps({"server_url": "http://server"}))
    assert validate_workspace(root, "http://server") == str(root)
    (root / "forgepdm-workspace.json").write_text("{}")
    with pytest.raises(WorkspaceError, match="workspace root"):
        validate_workspace(root, "http://server")


def test_missing_and_linked_metadata_never_repair_or_overwrite(tmp_path):
    with pytest.raises(WorkspaceError, match="once"):
        validate_workspace("", "http://server")
    with pytest.raises(WorkspaceError, match="missing"):
        validate_workspace(tmp_path / "missing", "http://server")
    target = tmp_path / "outside"
    target.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / ".forgepdm").symlink_to(target, target_is_directory=True)
    with pytest.raises(WorkspaceError, match="linked"):
        validate_workspace(root, "http://server")
    assert list(target.iterdir()) == []


def test_workspaces_are_remembered_per_server_and_actor(monkeypatch):
    class Parameters:
        def __init__(self):
            self.values, self.children = {}, {}

        def GetGroup(self, key):
            return self.children.setdefault(key, Parameters())

        def SetString(self, key, value):
            self.values[key] = value

        def GetString(self, key, default):
            return self.values.get(key, default)

    parameters = Parameters()
    monkeypatch.setattr(settings, "_parameters", lambda: parameters)
    settings.save_workspace("/legacy")
    settings.save_workspace("/one", "http://one", "alice")
    settings.save_workspace("/two", "http://one", "bob")
    assert settings.workspace_root("http://one/", "alice") == "/one"
    assert settings.workspace_root("http://one", "bob") == "/two"
    assert settings.workspace_root("http://two", "alice") == ""
    assert settings.workspace_root() == "/legacy"

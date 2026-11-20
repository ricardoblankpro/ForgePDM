"""Only inspectable stale paths may trigger native link-cache refresh."""

from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import cad, fcstd


@pytest.mark.parametrize("property_name", ["LinkedObject", "BaseObject"])
@pytest.mark.parametrize("stale", [False, True])
def test_saved_paths_select_only_moved_targets(monkeypatch, tmp_path, property_name, stale):
    child = NS(FileName=str(tmp_path / "configuration" / "part.FCStd"))
    target = NS(Name="Body", Document=child)
    obj = NS(Name="Component", LinkedObject=target)
    document = NS(FileName=str(tmp_path / "working" / "model.FCStd"), getObject=lambda _: obj)
    references = [
        dict(
            object_name=obj.Name,
            property_name=property_name,
            target_object_name=target.Name,
            file="part.FCStd" if stale else "../configuration/part.FCStd",
        )
    ]
    monkeypatch.setattr(fcstd, "inspect", lambda _: (None, references))
    monkeypatch.setattr(cad.fasteners, "attachment", lambda _: (target, "Edge1"))
    calls = []
    monkeypatch.setattr(cad, "rebase_links", lambda doc, names: calls.append((doc, names)))
    assert cad.repair_saved_link_paths(document) is stale
    assert calls == ([(document, {"Component"})] if stale else [])


@pytest.mark.parametrize("target_kind", ["unresolved", "different_object", "internal", "tuple"])
def test_path_repair_does_not_hide_other_reference_mismatches(monkeypatch, tmp_path, target_kind):
    target = NS(Name="Body", Document=NS(FileName=str(tmp_path / "child.FCStd")))
    obj = NS(Name="Component", LinkedObject=target)
    document = NS(FileName=str(tmp_path / "model.FCStd"), getObject=lambda _: obj)
    if target_kind == "unresolved":
        obj.LinkedObject = None
    elif target_kind == "different_object":
        target.Name = "Other"
    elif target_kind == "internal":
        target.Document = document
    else:
        obj.LinkedObject = (target, ["Face1"])
    monkeypatch.setattr(
        fcstd,
        "inspect",
        lambda _: (
            None,
            [
                dict(
                    object_name=obj.Name,
                    property_name="LinkedObject",
                    target_object_name="Body",
                    file="old.FCStd",
                )
            ],
        ),
    )
    monkeypatch.setattr(cad, "rebase_links", lambda *a, **k: pytest.fail("unexpected repair"))
    assert not cad.repair_saved_link_paths(document)


def test_unsupported_archive_is_left_for_strict_transfer_validation(monkeypatch, tmp_path):
    document = NS(FileName=str(tmp_path / "unsupported.FCStd"))

    def reject(_):
        raise fcstd.CADIntegrityError("Unsupported external CAD reference")

    monkeypatch.setattr(fcstd, "inspect", reject)
    monkeypatch.setattr(cad, "rebase_links", lambda *a, **k: pytest.fail("unexpected repair"))
    assert not cad.repair_saved_link_paths(document)
    with pytest.raises(fcstd.CADIntegrityError, match="Unsupported"):
        fcstd.validate(document.FileName, [])

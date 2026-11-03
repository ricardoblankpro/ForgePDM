"""Explicit revision replacement, repeat isolation and joint-safe rollback."""

from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import replacement
from freecad.forgepdm.workspace import WorkspaceError


def fixture():
    meta = NS(ItemId="part", RevisionId="B", ServerUrl="http://server")
    target_doc = NS(
        Name="B", getObject=lambda name: meta if name == "ForgePDM_Metadata" else target
    )
    old_doc = NS(Name="A")
    old = NS(Name="Body", TypeId="PartDesign::Body", Document=old_doc)
    target = NS(Name="Body", TypeId="PartDesign::Body", Document=target_doc)
    root = NS(Name="Root", HasPendingTransaction=False)
    links = [
        NS(
            Name=name,
            TypeId="App::Link",
            LinkedObject=old,
            Placement=index,
            ForgePDMOccurrenceId="uuid-" + name,
        )
        for index, name in enumerate(("First", "Second"))
    ]
    for link in links:
        link.setLink = lambda value, link=link: setattr(link, "LinkedObject", value)
        link.Document = root
    joint = NS(
        Name="Grounded",
        TypeId="App::FeaturePython",
        Proxy=type("GroundedJoint", (), {"__module__": "JointObject"})(),
        PropertiesList=["ObjectToGround"],
        ObjectToGround=links[0],
        getTypeIdOfProperty=lambda name: "App::PropertyLinkGlobal",
    )
    root.Objects = links + [joint]
    root.getObject = lambda name: (
        NS(ServerUrl="http://server", ItemId="assembly")
        if name == "ForgePDM_Metadata"
        else next((o for o in root.Objects if o.Name == name), None)
    )
    root.recompute = lambda: None
    events = []

    def begin(name):
        root.HasPendingTransaction = True
        events.append("open")

    def abort():
        for link in links:
            link.LinkedObject = old
        root.HasPendingTransaction = False
        events.append("abort")

    def commit():
        root.HasPendingTransaction = False
        events.append("commit")

    root.openTransaction, root.abortTransaction, root.commitTransaction = begin, abort, commit
    refs = [
        {
            "object_name": o.Name,
            "target_item_id": "part",
            "target_revision_id": "A",
            "target_object_name": "Body",
        }
        for o in links
    ]
    return root, links, target_doc, target, refs, events, joint


def test_replaces_only_selected_occurrence_preserving_names_placements_and_grounding(monkeypatch):
    root, links, doc, target, refs, events, joint = fixture()
    calls = []
    monkeypatch.setattr(replacement.tree_labels, "refresh", lambda d, **kw: calls.append(kw))
    assert replacement.apply(root, refs, ["First"], doc, {"id": "B", "item_id": "part"}) == 1
    assert links[0].LinkedObject is target
    assert links[1].LinkedObject is not target
    assert [o.Placement for o in links] == [0, 1]
    assert [o.ForgePDMOccurrenceId for o in links] == ["uuid-First", "uuid-Second"]
    assert joint.ObjectToGround is links[0]
    assert calls == [{"within_transaction": True}]
    assert events == ["open", "commit"]


def test_same_revision_snapshot_update_preserves_occurrences_and_unselected_target(monkeypatch):
    root, links, doc, target, refs, events, joint = fixture()
    for ref in refs:
        ref.update(target_revision_id="B", target_dataset_id="old", target_file_id="old-file")
    monkeypatch.setattr(replacement.tree_labels, "refresh", lambda *a, **kw: None)
    assert (
        replacement.apply(
            root,
            refs,
            ["First"],
            doc,
            {"id": "B", "item_id": "part"},
            target_snapshot=dict(dataset_id="new", file_id="new-file"),
        )
        == 1
    )
    assert links[0].LinkedObject is target and links[1].LinkedObject is not target
    assert [o.ForgePDMOccurrenceId for o in links] == ["uuid-First", "uuid-Second"]
    assert [o.Placement for o in links] == [0, 1]
    assert joint.ObjectToGround is links[0] and events == ["open", "commit"]


@pytest.mark.parametrize(
    "fault", ["same_pin", "missing_source_pin", "new_revision", "missing_target_pin", "mapping"]
)
def test_snapshot_mode_rejects_invalid_identity_or_pins(monkeypatch, fault):
    root, links, doc, target, refs, events, joint = fixture()
    refs[0].update(target_revision_id="B", target_dataset_id="old", target_file_id="old-file")
    snapshot = dict(dataset_id="new", file_id="new-file")
    kwargs = {}
    if fault == "same_pin":
        snapshot = dict(dataset_id="old", file_id="old-file")
    elif fault == "missing_source_pin":
        refs[0].pop("target_file_id")
    elif fault == "new_revision":
        refs[0]["target_revision_id"] = "A"
    elif fault == "missing_target_pin":
        snapshot.pop("file_id")
    else:
        kwargs["target_names"] = {"First": "Body"}
    with pytest.raises(WorkspaceError):
        replacement.apply(
            root,
            refs,
            ["First"],
            doc,
            {"id": "B", "item_id": "part"},
            target_snapshot=snapshot,
            **kwargs,
        )
    assert not events and links[0].LinkedObject is not target


def test_snapshot_mode_rolls_back_joint_failure(monkeypatch):
    root, links, doc, target, refs, events, joint = fixture()
    refs[0].update(target_revision_id="B", target_dataset_id="old", target_file_id="old-file")

    def recompute():
        if links[0].LinkedObject is target:
            joint.ObjectToGround = links[1]

    root.recompute = recompute
    with pytest.raises(WorkspaceError, match="Joint references changed"):
        replacement.apply(
            root,
            refs,
            ["First"],
            doc,
            {"id": "B", "item_id": "part"},
            target_snapshot=dict(dataset_id="new", file_id="new-file"),
        )
    assert events == ["open", "abort"] and links[0].LinkedObject is not target


@pytest.mark.parametrize(
    "fault", ["other_item", "same_revision", "missing", "array", "duplicate", "pending"]
)
def test_invalid_replacement_is_rejected_before_local_changes(monkeypatch, fault):
    root, links, doc, target, refs, events, joint = fixture()
    revision = {"id": "B", "item_id": "part"}
    names = ["First"]
    if fault == "other_item":
        refs[0]["target_item_id"] = "other"
    elif fault == "same_revision":
        refs[0]["target_revision_id"] = "B"
    elif fault == "missing":
        doc.getObject = lambda name: (
            NS(ItemId="part", RevisionId="B", ServerUrl="http://server")
            if name == "ForgePDM_Metadata"
            else None
        )
    elif fault == "array":
        links[0].ElementCount = 3
    elif fault == "duplicate":
        names.append("First")
    else:
        root.HasPendingTransaction = True
    with pytest.raises(WorkspaceError):
        replacement.apply(root, refs, names, doc, revision)
    assert not events
    assert links[0].LinkedObject is not target


@pytest.mark.parametrize("fault", ["geometry", "joint", "labels"])
def test_postreplacement_failure_aborts_transaction(monkeypatch, fault):
    root, links, doc, target, refs, events, joint = fixture()

    def recompute():
        if links[0].LinkedObject is target:
            if fault == "geometry":
                links[0].State = ["Invalid"]
            elif fault == "joint":
                joint.ObjectToGround = links[1]

    root.recompute = recompute

    def refresh(*args, **kwargs):
        if fault == "labels":
            raise WorkspaceError("label conflict")

    monkeypatch.setattr(replacement.tree_labels, "refresh", refresh)
    with pytest.raises(WorkspaceError):
        replacement.apply(root, refs, ["First"], doc, {"id": "B", "item_id": "part"})
    assert links[0].LinkedObject is not target
    assert events == ["open", "abort"]


def test_native_subassembly_uses_property_not_broken_setlink_binding(monkeypatch):
    root, links, doc, target, refs, events, joint = fixture()
    links[0].TypeId = "Assembly::AssemblyLink"
    links[0].LinkedObject.TypeId = target.TypeId = "Assembly::AssemblyObject"
    links[0].setLink = lambda target: pytest.fail("native setLink is not supported")
    monkeypatch.setattr(replacement.tree_labels, "refresh", lambda *args, **kwargs: None)
    replacement.apply(root, refs, ["First"], doc, {"id": "B", "item_id": "part"})
    assert links[0].LinkedObject is target


def test_recompute_moving_unselected_occurrence_rolls_back(monkeypatch):
    root, links, doc, target, refs, events, joint = fixture()

    def recompute():
        if links[0].LinkedObject is target:
            links[1].Placement = 25

    root.recompute = recompute
    monkeypatch.setattr(replacement.tree_labels, "refresh", lambda *args, **kwargs: None)
    with pytest.raises(WorkspaceError, match="unselected"):
        replacement.apply(root, refs, ["First"], doc, {"id": "B", "item_id": "part"})
    assert events == ["open", "abort"]


def test_joint_pointing_directly_to_external_source_requires_manual_mapping(monkeypatch):
    root, links, doc, target, refs, events, joint = fixture()
    joint.ObjectToGround = links[0].LinkedObject
    with pytest.raises(WorkspaceError, match="external source"):
        replacement.apply(root, refs, ["First"], doc, {"id": "B", "item_id": "part"})
    assert not events


def general_fixture():
    root, links, doc, target, refs, events, joint = fixture()
    parent_meta = NS(ItemId="parent", ServerUrl="http://server")
    root.getObject = lambda name: (
        parent_meta
        if name == "ForgePDM_Metadata"
        else next((o for o in root.Objects if o.Name == name), None)
    )
    target.Name = "ReplacementBox"
    target.TypeId = "Part::Box"
    target.Shape = NS(isNull=lambda: False)
    target.isDerivedFrom = lambda kind: kind == "Part::Feature"
    doc.Objects = [target]
    meta = NS(ItemId="different-item", RevisionId="different-A", ServerUrl="http://server")
    doc.getObject = lambda name: (
        meta
        if name == "ForgePDM_Metadata"
        else next((o for o in doc.Objects if o.Name == name), None)
    )
    return root, links, doc, target, refs, events, joint, meta


def test_general_replacement_maps_different_item_name_and_feature_type(monkeypatch):
    root, links, doc, target, refs, events, joint, meta = general_fixture()
    monkeypatch.setattr(replacement.tree_labels, "refresh", lambda *args, **kwargs: None)
    replacement.apply(
        root,
        refs,
        ["First"],
        doc,
        {"id": "different-A", "item_id": "different-item"},
        target_names={"First": "ReplacementBox"},
    )
    assert links[0].LinkedObject is target
    assert links[1].LinkedObject is not target
    assert links[0].ForgePDMOccurrenceId == "uuid-First"
    assert joint.ObjectToGround is links[0]
    assert [o.Placement for o in links] == [0, 1]
    assert events == ["open", "commit"]


@pytest.mark.parametrize(
    "fault",
    ["mapping_missing", "internal_feature", "self_item", "native_to_part", "different_sources"],
)
def test_general_replacement_rejects_unsafe_mapping_before_mutation(monkeypatch, fault):
    root, links, doc, target, refs, events, joint, meta = general_fixture()
    names = ["First"]
    mapping = {"First": "ReplacementBox"}
    if fault == "mapping_missing":
        mapping = {}
    elif fault == "internal_feature":
        mapping = {"First": "NoSuchFeature"}
    elif fault == "self_item":
        root.getObject("ForgePDM_Metadata").ItemId = "different-item"
    elif fault == "native_to_part":
        links[0].TypeId = "Assembly::AssemblyLink"
    else:
        refs[1]["target_item_id"] = "another-source"
        names.append("Second")
        mapping["Second"] = "ReplacementBox"
    with pytest.raises(WorkspaceError):
        replacement.apply(
            root,
            refs,
            names,
            doc,
            {"id": "different-A", "item_id": "different-item"},
            target_names=mapping,
        )
    assert not events
    assert links[0].LinkedObject is not target


def test_mapping_candidates_exclude_container_internals_and_links():
    document = NS()
    pad = NS(
        Name="Pad",
        TypeId="PartDesign::Feature",
        Document=document,
        isDerivedFrom=lambda kind: True,
        Shape=NS(isNull=lambda: False),
    )
    body = NS(Name="Body", TypeId="PartDesign::Body", Document=document, Group=[pad])
    link = NS(Name="Link", TypeId="App::Link", Document=document)
    document.Objects = [pad, body, link]
    assert replacement.target_objects(document) == [body]


def test_general_replacement_rolls_back_on_joint_error(monkeypatch):
    root, links, doc, target, refs, events, joint, meta = general_fixture()

    def recompute():
        if links[0].LinkedObject is target:
            links[0].State = ["Invalid"]

    root.recompute = recompute
    with pytest.raises(WorkspaceError):
        replacement.apply(
            root,
            refs,
            ["First"],
            doc,
            {"id": "different-A", "item_id": "different-item"},
            target_names={"First": "ReplacementBox"},
        )
    assert events == ["open", "abort"]
    assert links[0].LinkedObject is not target


def test_unselected_internal_occurrence_cannot_silently_follow_replaced_link(monkeypatch):
    root, links, doc, target, refs, events, joint, meta = general_fixture()
    links[1].LinkedObject = links[0]
    with pytest.raises(WorkspaceError, match="depends on a selected"):
        replacement.apply(
            root,
            refs,
            ["First"],
            doc,
            {"id": "different-A", "item_id": "different-item"},
            target_names={"First": "ReplacementBox"},
        )
    assert not events


def test_selected_internal_occurrence_can_be_replaced_independently(monkeypatch):
    root, links, doc, target, refs, events, joint, meta = general_fixture()
    old = links[0].LinkedObject
    links[1].LinkedObject = links[0]
    monkeypatch.setattr(replacement.tree_labels, "refresh", lambda *args, **kwargs: None)
    replacement.apply(
        root,
        refs,
        ["Second"],
        doc,
        {"id": "different-A", "item_id": "different-item"},
        target_names={"Second": "ReplacementBox"},
    )
    assert links[0].LinkedObject is old
    assert links[1].LinkedObject is target

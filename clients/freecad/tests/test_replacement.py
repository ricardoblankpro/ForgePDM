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
        NS(ServerUrl="http://server")
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
    root,links,doc,target,refs,events,joint=fixture()
    joint.ObjectToGround=links[0].LinkedObject
    with pytest.raises(WorkspaceError,match='external source'):
        replacement.apply(root,refs,['First'],doc,{'id':'B','item_id':'part'})
    assert not events

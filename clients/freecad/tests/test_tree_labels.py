"""Occurrence identity, allocation history and CAD presentation separation."""

import json
from uuid import uuid4

import pytest

from freecad.forgepdm import tree_labels as labels
from freecad.forgepdm.workspace import WorkspaceError


OWNER = str(uuid4())
ITEM = str(uuid4())
REVISION = str(uuid4())
SERVER = "http://forgepdm.test"


def record(name, scope="Assembly", item=ITEM, revision=REVISION, label="B"):
    return {
        "name": name,
        "scope": scope,
        "item_id": item,
        "revision_id": revision,
        "item_number": "P000001",
        "revision_label": label,
    }


def test_allocation_groups_exact_revision_and_parent_without_parsing_labels():
    rows, state = labels.allocate(
        [
            record("First"),
            record("Repeat"),
            record("OtherScope", "Sub"),
            record("OtherRev", revision=str(uuid4()), label="C"),
        ],
        "",
        OWNER,
    )
    assert [row["label"] for row in rows] == [
        "P000001-B|1",
        "P000001-B|2",
        "P000001-B|1",
        "P000001-C|1",
    ]
    assert len({row["identity"] for row in rows}) == 4
    reordered, same_state = labels.allocate(list(reversed(rows)), state, OWNER)
    assert {row["name"]: row["label"] for row in reordered} == {
        row["name"]: row["label"] for row in rows
    }
    assert same_state == state


def test_deleted_highest_number_is_not_reused_and_existing_numbers_do_not_shift():
    rows, state = labels.allocate([record("First"), record("Second")], "", OWNER)
    survivor, state = labels.allocate([rows[1]], state, OWNER)
    assert survivor[0]["number"] == 2
    # Delete every occurrence: history must remain in the serialized registry.
    _, state = labels.allocate([], state, OWNER)
    new, _ = labels.allocate([record("New")], state, OWNER)
    assert new[0]["number"] == 3


def test_copy_appearing_before_original_gets_fresh_identity_and_number():
    original, state = labels.allocate([record("ZOriginal")], "", OWNER)
    copy = dict(original[0], name="ACopy")
    result, _ = labels.allocate([copy, original[0]], state, OWNER)
    assert result[1]["identity"] == original[0]["identity"]
    assert result[1]["number"] == 1
    assert result[0]["number"] == 2
    assert result[0]["identity"] != original[0]["identity"]


def test_reparent_and_target_revision_change_keep_identity_and_allocate_new_scope():
    rows, state = labels.allocate([record("First")], "", OWNER)
    moved, state = labels.allocate([dict(rows[0], scope="Sub")], state, OWNER)
    assert moved[0]["identity"] == rows[0]["identity"]
    changed, state = labels.allocate(
        [dict(moved[0], revision_id=str(uuid4()), revision_label="C")], state, OWNER
    )
    assert changed[0]["label"] == "P000001-C|1"
    assert changed[0]["identity"] == rows[0]["identity"]
    returned, _ = labels.allocate(rows, state, OWNER)
    assert returned[0]["number"] == 2


def test_new_parent_item_reseeds_ids_while_same_item_revision_copy_keeps_lineage():
    rows, state = labels.allocate([record("First")], "", OWNER)
    same, _ = labels.allocate(rows, state, OWNER)
    assert same[0]["identity"] == rows[0]["identity"]
    fork, _ = labels.allocate(rows, state, str(uuid4()))
    assert fork[0]["identity"] != rows[0]["identity"]
    assert fork[0]["number"] == 1


@pytest.mark.parametrize(
    "state",
    [
        "broken",
        "[]",
        "null",
        '{"version":99}',
        json.dumps({"version": 1, "owner_item_id": OWNER, "owners": {}, "counters": {"bad": -1}}),
    ],
)
def test_invalid_registry_is_rejected_instead_of_silently_reset(state):
    with pytest.raises(WorkspaceError, match="registry"):
        labels.allocate([record("First")], state, OWNER)


class Object:
    def __init__(self, name, kind, document, **values):
        self.Name, self.Label, self.TypeId, self.Document = name, name, kind, document
        self.PropertiesList = []
        self.kinds = {}
        self.__dict__.update(values)
        for name, value in values.items():
            if isinstance(value, str):
                self.PropertiesList.append(name)
                self.kinds[name] = "App::PropertyString"

    def addProperty(self, kind, name, group):
        self.PropertiesList.append(name)
        self.kinds[name] = kind
        setattr(self, name, 0 if kind == "App::PropertyInteger" else "")

    def getTypeIdOfProperty(self, name):
        return self.kinds[name]

    def setEditorMode(self, name, mode):
        pass


class Document:
    def __init__(self, item=OWNER, revision="parent-revision", number="A000001", label="A"):
        self.Label = "Human readable description"
        self.Objects = []
        self.transactions = []
        self.HasPendingTransaction = False
        self.add(
            "ForgePDM_Metadata",
            "App::FeaturePython",
            ItemId=item,
            RevisionId=revision,
            ItemNumber=number,
            RevisionLabel=label,
            ServerUrl=SERVER,
        )

    def add(self, name, kind, **values):
        obj = Object(name, kind, self, **values)
        self.Objects.append(obj)
        return obj

    def getObject(self, name):
        return next((obj for obj in self.Objects if obj.Name == name), None)

    def openTransaction(self, name):
        self.transactions.append("open")

    def commitTransaction(self):
        self.transactions.append("commit")

    def abortTransaction(self):
        self.transactions.append("abort")


def assembly():
    child = Document(ITEM, REVISION, "P000001", "B")
    target = child.add("Body", "PartDesign::Body")
    root = Document()
    first = root.add("First", "App::Link", LinkedObject=target)
    second = root.add("Second", "App::Link", LinkedObject=first)
    group = root.add("Assembly", "Assembly::AssemblyObject", Group=[first, second])
    return root, child, first, second, group


def test_adapter_labels_links_and_retains_names_targets_descriptions_and_noop_state():
    root, child, first, second, group = assembly()
    targets = [first.LinkedObject, second.LinkedObject]
    result = labels.refresh(root)
    assert result["labels"] == ["P000001-B|1", "P000001-B|2"]
    assert root.Label == "A000001-A"
    assert root.getObject("ForgePDM_Metadata").TreeOriginalLabel == "Human readable description"
    assert first.ForgePDMOriginalLabel == "First"
    assert [first.Name, second.Name] == ["First", "Second"]
    assert [first.LinkedObject, second.LinkedObject] == targets
    assert child.Label == "Human readable description"
    before_transactions = list(root.transactions)
    assert not labels.refresh(root)["changed"]
    assert root.transactions == before_transactions


def test_registry_and_link_properties_survive_json_reload_and_duplicate_copy():
    root, child, first, second, group = assembly()
    labels.refresh(root)
    state = root.getObject("ForgePDM_Metadata").TreeOccurrenceState
    copy = root.add("Copy", "App::Link", LinkedObject=first.LinkedObject)
    copy.ForgePDMOccurrenceId = first.ForgePDMOccurrenceId
    group.Group.append(copy)
    labels.refresh(root)
    assert copy.Label == "P000001-B|3"
    assert copy.ForgePDMOccurrenceId != first.ForgePDMOccurrenceId
    assert root.getObject("ForgePDM_Metadata").TreeOccurrenceState != state


def test_organizational_group_does_not_reset_numbering_and_other_part_scope_does():
    root, child, first, second, group = assembly()
    folder = root.add("Folder", "App::DocumentObjectGroup", Group=[first])
    group.Group = [folder, second]
    labels.refresh(root)
    assert [first.Label, second.Label] == ["P000001-B|1", "P000001-B|2"]
    sub = root.add("Sub", "App::Part", Group=[second])
    group.Group = [folder, sub]
    labels.refresh(root)
    assert second.Label == "P000001-B|1"


def test_ambiguous_parents_and_incompatible_properties_leave_labels_unmodified():
    root, child, first, second, group = assembly()
    root.add("Other", "App::Part", Group=[first])
    with pytest.raises(WorkspaceError, match="multiple assembly"):
        labels.refresh(root)
    assert first.Label == "First"
    assert not root.transactions
    root.Objects.pop()
    first.addProperty("App::PropertyInteger", "ForgePDMOccurrenceId", "Other")
    with pytest.raises(WorkspaceError, match="Incompatible"):
        labels.refresh(root)
    assert not root.transactions


def test_foreign_or_unmanaged_links_keep_their_labels_and_get_no_occurrence():
    root, child, first, second, group = assembly()
    child.getObject("ForgePDM_Metadata").ServerUrl = "http://other-server.test"
    result = labels.refresh(root)
    assert result["skipped"] == ["First", "Second"]
    assert first.Label == "First"
    assert not hasattr(first, "ForgePDMOccurrenceNumber")


def test_pending_native_operation_prevents_partial_label_mutation():
    root, child, first, second, group = assembly()
    root.HasPendingTransaction = True
    with pytest.raises(WorkspaceError, match="Finish the current"):
        labels.refresh(root)
    assert first.Label == "First"
    assert not hasattr(first, "ForgePDMOccurrenceId")
    assert not root.transactions

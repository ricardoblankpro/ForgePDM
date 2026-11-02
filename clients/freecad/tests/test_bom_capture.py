"""Mocked document adapter tests; real FreeCAD evidence is separate."""

from types import SimpleNamespace as NS

import pytest

from freecad.forgepdm import cad
from freecad.forgepdm.workspace import WorkspaceError


@pytest.fixture(autouse=True)
def modification_adapter(monkeypatch):
    monkeypatch.setattr(cad, "document_modified", lambda document: document.isTouched())


def documents():
    child = NS(
        FileName="/tmp/child.FCStd",
        isTouched=lambda: False,
        getObject=lambda name: NS(ItemId="item", RevisionId="revision"),
    )
    root = NS(Objects=[])
    target = NS(TypeId="Part::Feature", Name="Box", Document=child)
    first = NS(TypeId="App::Link", Name="First", Document=root, LinkedObject=target)
    second = NS(TypeId="App::Link", Name="Second", Document=root, LinkedObject=first)
    root.Objects = [NS(TypeId="App::Part", Name="Group"), first, second]
    return root, child, first, second


def test_internal_repeated_link_resolves_to_same_exact_external_component():
    root, child, first, second = documents()
    references = cad.capture_bom(root)
    assert [ref["object_name"] for ref in references] == ["First", "Second"]
    assert {ref["target_object_name"] for ref in references} == {"Box"}
    assert {ref["target_revision_id"] for ref in references} == {"revision"}
    # A child document's assembly links are never traversed.
    child.Objects = [NS(TypeId="App::Link", LinkedObject=None)]
    assert cad.capture_bom(root) == references


def test_dirty_component_error_identifies_item_and_revision():
    root, child, first, second = documents()
    child.getObject = lambda name: NS(
        ItemId="item", RevisionId="revision", ItemNumber="P000004", RevisionLabel="B"
    )
    child.isTouched = lambda: True
    with pytest.raises(WorkspaceError, match="Component P000004 Rev B has unsaved changes"):
        cad.capture_bom(root)


@pytest.mark.parametrize(
    "fault", ["array", "cycle", "missing", "subelement", "local", "dirty", "proxy"]
)
def test_ambiguous_or_unpinned_structures_are_rejected(fault):
    root, child, first, second = documents()
    if fault == "array":
        first.ElementCount = 3
    elif fault == "cycle":
        first.LinkedObject = second
    elif fault == "missing":
        first.LinkedObject = None
    elif fault == "subelement":
        first.LinkedObject = (first.LinkedObject, ["Face1"])
    elif fault == "local":
        first.LinkedObject.Document = root
    elif fault == "dirty":
        child.isTouched = lambda: True
    else:
        root.Objects[0].Proxy = object()
    with pytest.raises(WorkspaceError):
        cad.capture_bom(root)


def builtin_document():
    root, child, first, second = documents()
    grounded = NS(
        Name="Grounded",
        TypeId="App::FeaturePython",
        Proxy=type("GroundedJoint", (), {"__module__": "JointObject"})(),
        ObjectToGround=first,
    )
    joint = NS(
        Name="Joint",
        TypeId="App::FeaturePython",
        Proxy=type("Joint", (), {"__module__": "JointObject"})(),
    )
    joints = NS(Name="Joints", TypeId="Assembly::JointGroup", Group=[grounded, joint])
    assembly = NS(
        Name="Assembly",
        TypeId="Assembly::AssemblyObject",
        Group=[joints, first, grounded, second, joint],
    )
    root.Objects = [assembly, joints, grounded, joint, first, second]
    return root, assembly, joints, grounded


def test_builtin_assembly_joints_are_not_components_or_duplicate_occurrences():
    root, assembly, joints, grounded = builtin_document()
    before = list(assembly.Group)
    references = cad.capture_bom(root)
    assert [ref["object_name"] for ref in references] == ["First", "Second"]
    assert assembly.Group == before
    assert grounded.ObjectToGround.Name == "First"


@pytest.mark.parametrize(
    "fault",
    [
        "custom_joint",
        "custom_container",
        "custom_joint_group",
        "unknown_assembly_type",
        "nested_assembly",
        "stray_link",
        "local_member",
    ],
)
def test_builtin_adapter_rejects_ambiguous_members_with_context(fault):
    root, assembly, joints, grounded = builtin_document()
    if fault == "custom_joint":
        grounded.Proxy = type("GroundedJoint", (), {"__module__": "custom_addon"})()
        message = "Unsupported built-in Assembly joint 'Grounded'"
    elif fault == "custom_container":
        assembly.Proxy = object()
        message = "Custom native Assembly container proxies"
    elif fault == "custom_joint_group":
        joints.Proxy = object()
        message = "Custom Assembly joint-group proxies"
    elif fault == "unknown_assembly_type":
        root.Objects.append(NS(Name="Unknown", TypeId="Assembly::Unknown"))
        message = "Unsupported BOM object 'Unknown'"
    elif fault == "nested_assembly":
        root.Objects.append(NS(Name="Nested", TypeId="Assembly::AssemblyObject", Group=[]))
        message = "one built-in Assembly container"
    elif fault == "stray_link":
        assembly.Group = [obj for obj in assembly.Group if obj.Name != "Second"]
        message = "Component link 'Second' is outside"
    else:
        assembly.Group.append(NS(Name="LocalBody", TypeId="PartDesign::Body"))
        message = "Unsupported Assembly member 'LocalBody'"
    with pytest.raises(WorkspaceError, match=message):
        cad.capture_bom(root)


def test_native_subassembly_upload_captures_exact_document_pin():
    root, child, first, second = documents()
    first.TypeId = "Assembly::AssemblyLink"
    first.LinkedObject.TypeId = "Assembly::AssemblyObject"
    references = cad.capture(root)
    assert len(references) == 1
    assert references[0]["object_name"] == "First"
    assert references[0]["target_revision_id"] == "revision"
    assert references[0]["target_path"] == child.FileName


def test_native_subassembly_rebase_uses_property_and_invalidates_cached_path():
    root, child, first, second = documents()
    target = first.LinkedObject
    updates = []

    class NativeLink:
        Name = "Native"
        TypeId = "Assembly::AssemblyLink"
        Placement = object()
        _target = target

        @property
        def LinkedObject(self):
            return self._target

        @LinkedObject.setter
        def LinkedObject(self, value):
            updates.append(value)
            self._target = value

        def setLink(self, value):
            raise AttributeError("<no object bound to built-in method setLink>")

    link = NativeLink()
    placement = link.Placement
    root.Objects = [link]
    root.getObject = lambda name: link
    root.recompute = lambda: None
    cad.rebase_links(root)
    assert updates == [None, target]
    assert link.LinkedObject is target
    assert link.Placement is placement

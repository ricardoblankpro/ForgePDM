"""Selected occurrence changes preserve other grades, geometry and cancellation."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_document_save import commands as commands_fixture

commands = commands_fixture


class Object(SimpleNamespace):
    def addProperty(self, *args):
        pass


@pytest.fixture
def case(commands, monkeypatch):
    from freecad.forgepdm import fasteners

    proxy = type("FSScrewObject", (), {"__module__": "FastenersCmd"})
    old, new = str(uuid4()), str(uuid4())
    document = SimpleNamespace(Name="Assembly", HasPendingTransaction=False, recompute=lambda: None)
    objects = [
        Object(
            Name=name,
            TypeId="Part::FeaturePython",
            Proxy=proxy(),
            Document=document,
            Type="ISO4017",
            Diameter="M8",
            Length="25",
            LeftHanded=False,
            Placement=object(),
            BaseObject=None,
        )
        for name in ("Selected", "Unselected")
    ]
    document.Objects = objects
    document.getObject = lambda name: next((o for o in objects if o.Name == name), None)
    for obj in objects:
        fasteners.associate(obj, old)
    transactions = []
    document.openTransaction = lambda name: transactions.append(name)
    document.commitTransaction = lambda: transactions.append("commit")
    document.abortTransaction = lambda: transactions.append("abort")
    geometry = fasteners.extract(objects[0])
    match = dict(
        number="S000002",
        name="Bolt 10.9",
        revision_label="A",
        current_revision_id=new,
        specification=dict(geometry=geometry, material="steel", grade="10.9", finish="zinc"),
    )
    client = SimpleNamespace(
        token="test",
        standard_capabilities=lambda: dict(version=1, snapshot_evidence=True),
        standard_matches=lambda geometry: {"items": [match]},
    )
    authorizations = []

    def authorize(*args):
        if False:
            yield
        authorizations.append("checkout")

    def editable(*args):
        if False:
            yield
        return dict(item_kind="assembly")

    metadata = SimpleNamespace(RevisionId="revision", ItemId="item")
    monkeypatch.setattr(commands, "_require_metadata", lambda doc: metadata)
    monkeypatch.setattr(commands, "_guard_document", lambda *args: document)
    monkeypatch.setattr(commands, "_authorize_tree_labels", authorize)
    monkeypatch.setattr(commands, "_editable", editable)
    monkeypatch.setattr(commands.cad, "_builtin_bom_context", lambda doc: None)
    monkeypatch.setattr(commands.cad, "validate_fastener_membership", lambda *args: None)
    monkeypatch.setattr(
        commands, "ask_choice", lambda title, prompt, choices, default=None: choices[0]
    )
    monkeypatch.setattr(commands, "information", lambda *args: None)
    monkeypatch.setattr(commands.Session, "client", client)
    monkeypatch.setattr(commands.FreeCAD, "ActiveDocument", document)
    monkeypatch.setattr(
        commands.FreeCADGui,
        "Selection",
        SimpleNamespace(getSelection=lambda: [objects[0]]),
        raising=False,
    )
    return SimpleNamespace(
        document=document,
        objects=objects,
        client=client,
        old=old,
        new=new,
        fasteners=fasteners,
        transactions=transactions,
        authorizations=authorizations,
    )


def drive(workflow):
    result = None
    while True:
        try:
            request = workflow.send(result)
        except StopIteration as done:
            return done.value
        result = request.function(*request.args, **request.kwargs)


def test_selected_grade_changes_without_moving_or_reidentifying_occurrences(commands, case):
    selected, other = case.objects
    original = case.fasteners.association(selected)
    untouched = other.PDMStandardAssociation
    placement = selected.Placement
    drive(commands.ChangeStandardPartAssociationCommand().action())
    current = case.fasteners.association(selected)
    assert current["revision_id"] == case.new
    assert current["occurrence_id"] == original["occurrence_id"]
    assert other.PDMStandardAssociation == untouched
    assert selected.Placement is placement and selected.BaseObject is None
    assert case.transactions[-1] == "commit"
    assert case.authorizations == ["checkout", "checkout"]


def test_cancel_does_not_change_any_association(commands, case, monkeypatch):
    before = [obj.PDMStandardAssociation for obj in case.objects]
    monkeypatch.setattr(commands, "ask_choice", lambda *a, **kw: None)
    drive(commands.ChangeStandardPartAssociationCommand().action())
    assert [obj.PDMStandardAssociation for obj in case.objects] == before
    assert case.transactions == []


def test_checkout_loss_during_review_prevents_application(commands, case, monkeypatch):
    before = case.objects[0].PDMStandardAssociation

    def authorize(*args):
        if False:
            yield
        raise commands.workspace.WorkspaceError("Checkout changed")

    monkeypatch.setattr(commands, "_authorize_tree_labels", authorize)
    with pytest.raises(commands.workspace.WorkspaceError, match="Checkout changed"):
        drive(
            commands._associate_fasteners(case.client, case.document, selected_names={"Selected"})
        )
    assert case.objects[0].PDMStandardAssociation == before
    assert case.transactions == []


def test_stale_association_during_review_is_not_overwritten(commands, case, monkeypatch):
    def choose(title, prompt, choices, default=None):
        case.fasteners.associate(case.objects[0], str(uuid4()))
        return choices[0]

    monkeypatch.setattr(commands, "ask_choice", choose)
    with pytest.raises(commands.workspace.WorkspaceError, match="changed during association"):
        drive(
            commands._associate_fasteners(case.client, case.document, selected_names={"Selected"})
        )
    assert case.transactions == []


def test_selection_must_be_direct_fastener_objects(commands, case, monkeypatch):
    monkeypatch.setattr(commands.FreeCADGui.Selection, "getSelection", lambda: [])
    with pytest.raises(commands.workspace.WorkspaceError, match="Select one or more"):
        drive(commands.ChangeStandardPartAssociationCommand().action())


def test_missing_selected_occurrence_is_rejected(commands, case):
    with pytest.raises(commands.workspace.WorkspaceError, match="changed or disappeared"):
        drive(commands._associate_fasteners(case.client, case.document, selected_names={"Missing"}))


def test_selected_occurrence_can_register_a_different_purchasing_specification(
    commands, case, monkeypatch
):
    original_id = case.fasteners.association(case.objects[0])["occurrence_id"]
    untouched = case.objects[1].PDMStandardAssociation
    monkeypatch.setattr(commands, "ask_choice", lambda *a, **kw: "Register a new S item")
    monkeypatch.setattr(
        commands,
        "ask_text",
        lambda title, prompt, default="": "10.9" if prompt.startswith("Grade") else "steel",
    )
    registered = []

    def register(client, specification, mass_object=None):
        if False:
            yield
        registered.append(specification)
        return {"number": "S000003", "current_revision_id": case.new}

    monkeypatch.setattr(commands, "_register_standard", register)
    drive(commands.ChangeStandardPartAssociationCommand().action())
    assert registered[0]["geometry"]["Type"] == "iso4017"
    assert case.fasteners.association(case.objects[0])["occurrence_id"] == original_id
    assert case.objects[1].PDMStandardAssociation == untouched


def test_fastener_registration_uses_generated_text_without_text_prompts(commands, monkeypatch):
    from freecad.forgepdm import standard_options, ui

    geometry = {"Type": "ISO4016", "Diameter": "M12", "Length": "70"}
    spec = standard_options.selected_spec(
        geometry, "carbon", "ISO 898-1:8.8", "zinc", "SCREW", "HEX HEAD"
    )
    name, description = standard_options.catalog_text(spec, "SCREW", "HEX HEAD")
    monkeypatch.setattr(
        ui,
        "standard_specification_dialog",
        lambda _: dict(specification=spec, name=name, description=description),
    )
    monkeypatch.setattr(
        commands, "ask_text", lambda *a, **kw: pytest.fail("Unexpected free-text prompt")
    )

    def select(*args, **kwargs):
        if False:
            yield
        return {"id": "project"}

    monkeypatch.setattr(commands, "_select_record", select)
    captured = []

    def create(*args, **kwargs):
        captured.append((args, kwargs))
        return {"id": "created"}

    assert drive(
        commands._register_standard(
            SimpleNamespace(
                create_item=create,
                standard_capabilities=lambda: {"shared_library": True, "can_register": True},
            ),
            {"geometry": geometry},
        )
    ) == {"id": "created"}
    args, kwargs = captured[0]
    assert args == ("part", name, None, description)
    assert kwargs == {"number_series": "S", "standard_specification": spec}


def test_canceled_specification_form_does_not_ask_for_project_or_create(commands, monkeypatch):
    from freecad.forgepdm import ui

    monkeypatch.setattr(ui, "standard_specification_dialog", lambda _: None)
    monkeypatch.setattr(
        commands, "_select_record", lambda *a, **kw: pytest.fail("Canceled registration continued")
    )
    assert (
        drive(
            commands._register_standard(
                SimpleNamespace(
                    standard_capabilities=lambda: {"shared_library": True, "can_register": True}
                ),
                {"geometry": {"Type": "ISO4016"}},
            )
        )
        is None
    )


def test_standard_registration_requires_library_maintainer_before_prompts(commands, monkeypatch):
    client = SimpleNamespace(
        standard_capabilities=lambda: {"shared_library": True, "can_register": False}
    )
    monkeypatch.setattr(
        commands,
        "ask_text",
        lambda *a, **kw: pytest.fail("Unauthorized registration opened a prompt"),
    )
    with pytest.raises(commands.workspace.WorkspaceError, match="read-only"):
        drive(commands._register_standard(client))


def test_shared_registration_does_not_fall_back_to_projectless_old_server(commands):
    client = SimpleNamespace(standard_capabilities=lambda: {"version": 1})
    with pytest.raises(commands.workspace.WorkspaceError, match="Update/restart"):
        drive(commands._register_standard(client))


def test_new_standard_cad_upload_skips_project_picker(commands, case, monkeypatch):
    monkeypatch.setattr(commands, "_metadata", lambda *a, **kw: None)
    monkeypatch.setattr(commands, "ask_choice", lambda *a, **kw: "standard/purchased part")
    monkeypatch.setattr(
        commands, "_select_record", lambda *a, **kw: pytest.fail("Unexpected project prompt")
    )
    case.client.standard_capabilities = lambda: {"shared_library": True, "can_register": True}
    case.client.validate_references = lambda *_: None

    def associate(*args):
        if False:
            yield
        return True

    monkeypatch.setattr(commands, "_associate_fasteners", associate)
    monkeypatch.setattr(commands.cad, "capture", lambda *_: [])
    workflow = commands.UploadCommand().action()
    try:
        first = next(workflow)
        assert first.function == case.client.standard_capabilities
        second = workflow.send(first.function())
        assert second.function == case.client.validate_references
    finally:
        workflow.close()


@pytest.mark.parametrize("mass", [{"mass_kg": "0.016"}, {"mass_kg": None}])
def test_reference_lookup_preserves_occurrence_identity(commands, case, monkeypatch, mass):
    calls = []
    case.client.lookup_reference_mass = lambda revision: calls.append(revision) or mass
    monkeypatch.setattr(
        commands.FreeCAD, "Console", SimpleNamespace(PrintMessage=lambda text: None), raising=False
    )
    original = case.fasteners.association(case.objects[0])
    drive(commands.ChangeStandardPartAssociationCommand().action())
    assert calls == [case.new]
    assert case.fasteners.association(case.objects[0])["occurrence_id"] == original["occurrence_id"]
    assert case.fasteners.association(case.objects[0])["revision_id"] == case.new


def test_reference_lookup_failure_does_not_block_association(commands, case):
    def fail(revision):
        raise commands.ForgePDMError("Supplier offline", status=503)

    case.client.lookup_reference_mass = fail
    workflow = commands.ChangeStandardPartAssociationCommand().action()
    try:
        request = next(workflow)
        while True:
            try:
                result = request.function(*request.args, **request.kwargs)
            except commands.ForgePDMError as error:
                request = workflow.throw(error)
            else:
                request = workflow.send(result)
    except StopIteration:
        pass
    assert case.fasteners.association(case.objects[0])["revision_id"] == case.new

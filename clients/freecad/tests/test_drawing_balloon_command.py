"""Authorization and review races must prevent local balloon mutations."""

import json
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace as NS

import pytest
from test_document_save import commands as commands_fixture

commands = commands_fixture


@pytest.fixture
def case(commands, monkeypatch):
    from freecad.forgepdm import drawing_balloons

    document = NS(Name="Assembly", FileName="working.FCStd")
    table = NS(
        Name="BOM",
        Document=document,
        PDMTableData=json.dumps(
            {
                "format": 1,
                "layout": {
                    "view": "direct",
                    "columns": [
                        {"field": "position", "heading": "Pos", "width": 10, "align": "left"}
                    ],
                    "font": 3,
                    "precision": 3,
                },
                "report": {"revision_id": "root"},
                "notes": {},
            }
        ),
    )
    balloon = NS(Name="Balloon", Document=document, Text="literal", ExpressionEngine=[])
    page = NS(
        Name="Page",
        Template=True,
        Document=document,
        Views=[table, balloon],
        isDerivedFrom=lambda kind: kind == "TechDraw::DrawPage",
    )
    document.Objects = [page]
    objects = [table, balloon, page]
    document.getObject = lambda name: next((obj for obj in objects if obj.Name == name), None)
    metadata = NS(RevisionId="root", ItemId="item")
    lease = dict(
        id="lease",
        version=1,
        user_id="actor",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    calls, bindings = [], []
    client = NS(
        base_url="http://fixture",
        token="fixture",
        get_revision=lambda _: dict(item_id="item", lifecycle_state="working"),
        get_checkout=lambda _: lease.copy(),
        bom_snapshot=lambda _: calls.append("edit-permission"),
    )
    monkeypatch.setattr(commands.Session, "client", client)
    monkeypatch.setattr(commands.Session, "user", {"id": "actor"})
    monkeypatch.setattr(commands.FreeCAD, "ActiveDocument", document)
    monkeypatch.setattr(commands, "_require_document", lambda: document)
    monkeypatch.setattr(commands, "_require_metadata", lambda _: metadata)
    monkeypatch.setattr(commands, "_guard_document", lambda *args: document)
    monkeypatch.setattr(commands, "_open_status", lambda *args: None)
    monkeypatch.setattr(commands.workspace, "binding", lambda *args, **kwargs: {})
    monkeypatch.setattr(commands.workspace, "working_path", lambda *args: "working.FCStd")
    gui_document = NS(getInEdit=lambda: False)
    monkeypatch.setattr(commands.FreeCADGui, "getDocument", lambda _: gui_document, raising=False)
    monkeypatch.setattr(
        commands.FreeCADGui, "Selection", NS(getSelection=lambda: []), raising=False
    )
    ui = ModuleType("freecad.forgepdm.drawing_balloons_ui")

    def combo(obj):
        return NS(currentData=lambda: obj)

    ui.LinkBalloonDialog = lambda *args: NS(
        page=combo(page), table=combo(table), balloon=combo(balloon), row_key=lambda: "part:5"
    )
    monkeypatch.setitem(sys.modules, ui.__name__, ui)
    monkeypatch.setattr(commands, "execute_dialog", lambda _: True)
    monkeypatch.setattr(drawing_balloons, "bind", lambda *args: bindings.append(args))
    return NS(
        client=client,
        lease=lease,
        bindings=bindings,
        calls=calls,
        document=document,
        table=table,
        balloon=balloon,
        gui=gui_document,
    )


def drive(workflow, after_request=None):
    value = None
    while True:
        try:
            request = workflow.send(value)
        except StopIteration:
            return
        value = request.function(*request.args, **request.kwargs)
        if after_request:
            after_request(request)


def test_frozen_link_requires_edit_permission_and_owned_live_checkout(commands, case):
    drive(commands.LinkBOMBalloonCommand().action())
    assert case.calls == ["edit-permission"] and len(case.bindings) == 1


@pytest.mark.parametrize(
    "change",
    ["lease", "expired", "session", "path", "edit", "table", "balloon", "released", "permission"],
)
def test_changes_during_review_prevent_binding(commands, case, monkeypatch, change):
    def change_state():
        if change == "lease":
            case.lease["version"] += 1
        elif change == "expired":
            case.lease["expires_at"] = "2000-01-01T00:00:00+00:00"
        elif change == "session":
            commands.Session.user = {"id": "other"}
        elif change == "path":
            case.document.FileName = "other.FCStd"
        elif change == "edit":
            case.gui.getInEdit = lambda: True
        elif change == "table":
            case.table.PDMTableData += " "
        elif change == "balloon":
            case.balloon.Text = "other text"
        elif change == "released":
            case.client.get_revision = lambda _: dict(item_id="item", lifecycle_state="released")
        else:

            def denied(_):
                raise commands.workspace.WorkspaceError("Edit denied")

            case.client.bom_snapshot = denied

    # Capture the reviewed local state first; mutate at the subsequent HTTP boundary.
    def after(request):
        if request.label == "Checking revision…" and dialog_seen[0]:
            change_state()

    dialog_seen = [False]
    monkeypatch.setattr(
        commands, "execute_dialog", lambda _: dialog_seen.__setitem__(0, True) or True
    )
    if change == "released":
        monkeypatch.setattr(commands, "execute_dialog", lambda _: change_state() or True)
    with pytest.raises(commands.workspace.WorkspaceError):
        drive(commands.LinkBOMBalloonCommand().action(), after)
    assert not case.bindings


def test_cancellation_does_not_revalidate_or_mutate(commands, case, monkeypatch):
    monkeypatch.setattr(commands, "execute_dialog", lambda _: False)
    drive(commands.LinkBOMBalloonCommand().action())
    assert not case.calls and not case.bindings


@pytest.mark.parametrize("damage", ["none", "lease", "permission", "geometry", "table", "session"])
def test_automatic_workflow_revalidates_before_mutation(commands, case, monkeypatch, damage):
    from freecad.forgepdm import balloon_auto as auto

    case.page = case.document.Objects[0]
    case.page.TypeId = "TechDraw::DrawPage"
    case.balloon.SourceView = object()
    evidence = {"origin": [0, 0]}
    monkeypatch.setattr(auto.geometry, "signature", lambda _: str(evidence))
    monkeypatch.setattr(auto.geometry, "evidence", lambda _: evidence.copy())
    monkeypatch.setattr(
        auto.geometry,
        "candidates",
        lambda *args: [(NS(Name="Part"), {"component_revision_id": "part", "position": 5})],
    )
    changed = [False]

    def after(request):
        if request.label == "Revalidating balloon permission…" and not changed[0]:
            changed[0] = True
            if damage == "lease":
                case.lease["version"] += 1
            elif damage == "geometry":
                evidence["origin"] = [5, 0]
            elif damage == "table":
                case.table.PDMTableData += " "
            elif damage == "session":
                commands.Session.user = {"id": "other"}

    if damage == "permission":

        def denied(_):
            raise commands.workspace.WorkspaceError("Denied")

        case.client.bom_snapshot = denied
    if damage == "none":
        drive(auto.workflow(case.balloon), after)
        assert len(case.bindings) == 1 and len(case.bindings[0]) == 6
    else:
        with pytest.raises((ValueError, commands.workspace.WorkspaceError)):
            drive(auto.workflow(case.balloon), after)
        assert not case.bindings


@pytest.mark.parametrize(
    "description,item_name,expected",
    [
        ("Chapa de aço inoxidável", "Original name", "Chapa de aço inoxidável"),
        ("", "M8 ISO 4017", "M8 ISO 4017"),
        ("", "", "No description"),
    ],
)
def test_automatic_part_choice_includes_frozen_description_and_keeps_target_identity(
    commands, case, monkeypatch, description, item_name, expected
):
    from freecad.forgepdm import balloon_auto as auto

    case.document.Objects[0].TypeId = "TechDraw::DrawPage"
    evidence = {"origin": [0, 0]}
    monkeypatch.setattr(auto.geometry, "signature", lambda _: str(evidence))
    monkeypatch.setattr(auto.geometry, "evidence", lambda _: evidence.copy())
    options = [
        (
            NS(Name="Part" + str(i), Label="Occurrence" + str(i)),
            dict(
                component_revision_id="part" + str(i),
                position=5 + i,
                item_number="P" + str(i),
                revision_label="A",
                description=description,
                item_name=item_name,
            ),
        )
        for i in range(2)
    ]
    monkeypatch.setattr(auto.geometry, "candidates", lambda *args: options)
    labels = []

    def choose(prompt, choices, ask, candidates):
        labels.extend(choices)
        return 1

    monkeypatch.setattr(auto, "choose", choose)
    drive(auto.workflow(case.balloon))
    assert all(expected in label for label in labels)
    assert labels[1] == f"P1 Rev A — Position 6 — {expected}"
    assert case.bindings[0][4] == "part1:6"
    assert options[1][1]["description"] == description

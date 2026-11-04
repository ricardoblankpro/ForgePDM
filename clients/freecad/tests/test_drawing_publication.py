"""Frozen source/bytes and recovery must survive uncertain PDF publication."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from freecad.forgepdm import drawing_publication as drawings, workspace
from freecad.forgepdm.api import ForgePDMError

PDF = b"%PDF-1.4\nDrawing fixture\n%%EOF\n"


@pytest.fixture
def case(tmp_path):
    server = "http://drawing.test"
    path = Path(workspace.prepare_working(server, tmp_path / "workspace"))
    path.write_bytes(b"native fixture")
    value = workspace.binding(path, server, require_uploaded=False)
    item, revision, actor, dataset, file_id = [str(uuid4()) for _ in range(5)]
    digest = workspace.digest(path)[0]
    entry = value["entry"]
    entry.update(
        item_id=item,
        revision_id=revision,
        dataset_id=dataset,
        file_id=file_id,
        working_hash=digest,
        content_hash=digest,
    )
    workspace._atomic_json(value["directory"] / workspace.MANIFEST, value["ledger"])
    lease = dict(
        id=str(uuid4()),
        version=1,
        user_id=actor,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    )
    client = SimpleNamespace(
        base_url=server,
        _checkpoint=lambda: None,
        get_revision=lambda _: dict(
            item_id=item, lifecycle_state="working", item_number="P1", label="A"
        ),
        get_checkout=lambda _: lease,
        list_datasets=lambda _: [
            dict(
                id=dataset,
                dataset_type="native_cad",
                created_at="2026-11-03",
                files=[dict(id=file_id, content_hash=digest)],
            )
        ],
    )
    results, uploads = {}, []
    client.drawing_publication_status = lambda rev, op: results.get(op)

    def upload(rev, bundle, intent):
        uploads.append(bundle)
        result = dict(
            intent,
            id=str(uuid4()),
            revision_id=rev,
            pages=[dict(p, file_id=str(uuid4()), dataset_id=str(uuid4())) for p in intent["pages"]],
        )
        results[intent["operation_id"]] = result
        return result

    client.upload_drawing_publication = upload
    return SimpleNamespace(
        client=client,
        path=path,
        revision=revision,
        item=item,
        actor=actor,
        value=value,
        lease=lease,
        uploads=uploads,
        results=results,
    )


def frozen(case):
    plan = drawings.prepare(case.client, str(case.path), case.revision, case.item, case.actor)
    (Path(plan["directory"]) / "page_0001.pdf").write_bytes(PDF)
    pages = [dict(page_name="Page", page_label="Drawing", filename="P1-A-Page.pdf")]
    operation = drawings.freeze(case.client, plan, pages)
    return plan, operation


def test_lost_response_recovers_exact_publication_without_reexport_or_duplicate(case):
    plan, operation = frozen(case)
    send = case.client.upload_drawing_publication

    def lose_response(*args):
        send(*args)
        raise ForgePDMError("Injected response loss", code="connection_failed")

    case.client.upload_drawing_publication = lose_response
    args = (case.client, str(case.path), case.revision, case.item, case.actor)
    with pytest.raises(ForgePDMError):
        drawings.resume(*args)
    case.path.write_bytes(b"later local edits preserved")
    result = drawings.resume(*args)
    assert len(case.uploads) == 1
    assert result["source_file_id"] == plan["intent"]["source_file_id"]
    assert case.path.read_bytes() == b"later local edits preserved"
    assert (
        json.loads((case.value["directory"] / drawings.JOURNAL).read_text())["state"]
        == "acknowledged"
    )
    assert drawings.resume(*args) is None


def test_changed_frozen_bundle_is_not_sent(case):
    plan, operation = frozen(case)
    bundle = Path(plan["directory"]) / "publication.zip"
    bundle.chmod(0o600)
    bundle.write_bytes(b"changed bytes")
    with pytest.raises(workspace.WorkspaceError, match="Frozen PDF bundle changed"):
        drawings.resume(case.client, str(case.path), case.revision, case.item, case.actor)
    assert not case.uploads


def test_other_actor_cannot_reuse_pending_journal(case):
    frozen(case)
    with pytest.raises(workspace.WorkspaceError, match="another user"):
        drawings.resume(case.client, str(case.path), case.revision, case.item, str(uuid4()))
    assert not case.uploads


def test_source_edit_during_export_rejects_freeze(case):
    plan = drawings.prepare(case.client, str(case.path), case.revision, case.item, case.actor)
    (Path(plan["directory"]) / "page_0001.pdf").write_bytes(PDF)
    case.path.write_bytes(b"changed native")
    with pytest.raises(workspace.WorkspaceError, match="local changes"):
        drawings.freeze(
            case.client,
            plan,
            [dict(page_name="Page", page_label="Drawing", filename="drawing.pdf")],
        )
    assert not (case.value["directory"] / drawings.JOURNAL).exists()


def test_stale_publication_can_be_archived_only_when_not_committed(case):
    plan, operation = frozen(case)

    def stale(*args):
        raise ForgePDMError("checkout changed", 409)

    case.client.upload_drawing_publication = stale
    args = (case.client, str(case.path), case.revision, case.item, case.actor)
    with pytest.raises(ForgePDMError):
        drawings.resume(*args)
    drawings.abandon(*args)
    assert not (case.value["directory"] / drawings.JOURNAL).exists()
    assert list(case.value["directory"].glob("drawing-publication-*.archived.json"))
    assert (Path(plan["directory"]) / "publication.zip").exists()


def test_unfinished_native_checkin_blocks_new_pdf_publication(case):
    (case.value["directory"] / "part-checkin.json").write_text('{"state":"prepared"}')
    with pytest.raises(workspace.WorkspaceError, match="pending Check In"):
        drawings.prepare(case.client, str(case.path), case.revision, case.item, case.actor)


def test_truncated_pdf_is_rejected_before_journaling_or_upload(case):
    plan = drawings.prepare(case.client, str(case.path), case.revision, case.item, case.actor)
    (Path(plan["directory"]) / "page_0001.pdf").write_bytes(b"%PDF-1.4 incomplete")
    with pytest.raises(workspace.WorkspaceError, match="incomplete PDF"):
        drawings.freeze(
            case.client,
            plan,
            [dict(page_name="Page", page_label="Drawing", filename="drawing.pdf")],
        )
    assert not case.uploads and not (case.value["directory"] / drawings.JOURNAL).exists()

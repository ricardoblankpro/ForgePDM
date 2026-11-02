"""Disposable real API fixture for browser QA; credentials stay outside the repo."""

from datetime import UTC


def serve(directory):
    import io
    import json
    import os
    import secrets
    import socket
    from datetime import datetime
    from pathlib import Path
    from uuid import uuid4

    case = Path(directory)
    case.mkdir(parents=True, exist_ok=False)
    os.environ["FORGEPDM_DATABASE"] = str(case / "metadata.sqlite3")
    os.environ["FORGEPDM_FILE_ROOT"] = str(case / "files")
    import uvicorn

    from forgepdm.application.auth import hash_password
    from forgepdm.domain.entities import DatasetType, ItemKind, LifecycleState, User
    from forgepdm.main import create_app

    app = create_app()
    password = secrets.token_urlsafe(24)
    now = datetime.now(UTC).isoformat()
    admin_id, viewer_id = str(uuid4()), str(uuid4())
    projects = {name: str(uuid4()) for name in ("design", "tools", "private")}
    with app.state.database.transaction() as connection:
        for identifier, username, role in [
            (admin_id, "web-admin", "admin"),
            (viewer_id, "web-viewer", "user"),
        ]:
            connection.execute(
                "INSERT INTO users(id,username,display_name,enabled,created_at,password_hash,role) VALUES (?,?,?,1,?,?,?)",
                (
                    identifier,
                    username,
                    "Morgan Ellis" if role == "user" else "QA Administrator",
                    now,
                    hash_password(password),
                    role,
                ),
            )
        for key, number, name in [
            ("design", "PRJ-DESIGN", "Assembly development"),
            ("tools", "PRJ-TOOLS", "Tooling & fixtures"),
            ("private", "PRJ-PRIVATE", "Restricted program"),
        ]:
            connection.execute(
                "INSERT INTO projects(id,project_number,name,archived,created_at) VALUES (?,?,?,0,?)",
                (projects[key], number, name, now),
            )
            if key != "private":
                connection.execute(
                    "INSERT INTO project_memberships(project_id,user_id,role,granted_at) VALUES (?,?,'viewer',?)",
                    (projects[key], viewer_id, now),
                )
    admin = User(
        id=admin_id,
        username="web-admin",
        display_name="QA Administrator",
        enabled=True,
        role="admin",
    )

    def item(kind, name, project="design", description=""):
        return app.state.item_service.create_item(
            kind=ItemKind(kind),
            name=name,
            description=description,
            created_by=admin_id,
            project_id=projects[project],
        )

    part = item("part", "Housing bracket", description="Precision bracket for the drive housing.")
    _dataset, file = app.state.dataset_service.attach_file(
        user=admin,
        revision_id=part.current_revision_id,
        dataset_type=DatasetType.DOCUMENT,
        dataset_name="Inspection sheet",
        filename="inspection.txt",
        media_type="text/plain",
        source=io.BytesIO(b"ForgePDM browser download verified.\n"),
    )
    app.state.revision_service.check_in(admin, part.current_revision_id, "Initial design approved")
    app.state.revision_service.transition_lifecycle(
        admin, part.current_revision_id, LifecycleState.RELEASED
    )
    part_b, _ = app.state.revision_service.create_next_revision(
        admin, part.id, "Add a mounting hole"
    )
    sub = item("assembly", "Drive module")
    root = item("assembly", "Positioning assembly")
    app.state.bom_service.replace_bom(
        admin,
        sub.current_revision_id,
        [{"component_revision_id": part.current_revision_id, "quantity": "4", "position": 1}],
    )
    app.state.bom_service.replace_bom(
        admin,
        root.current_revision_id,
        [
            {"component_revision_id": sub.current_revision_id, "quantity": "3", "position": 1},
            {"component_revision_id": part.current_revision_id, "quantity": "2", "position": 2},
        ],
    )
    tool = item("part", "Alignment fixture", "tools")
    private = item("part", "Confidential component", "private")
    injection = item(
        "part",
        '<img src=x onerror="window.webInjected=true">',
        description="A name rendered as plain text.",
    )
    for index in range(23):
        item("part", f"Mounting component {index + 1:02}")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    config = {
        "url": "http://127.0.0.1:" + str(listener.getsockname()[1]),
        "username": "web-viewer",
        "password": password,
        "root": {"id": root.id, "number": root.number, "revision": root.current_revision_id},
        "sub": {"id": sub.id, "number": sub.number, "revision": sub.current_revision_id},
        "part": {
            "id": part.id,
            "number": part.number,
            "revision": part.current_revision_id,
            "new_revision": part_b.id,
        },
        "tool": {"id": tool.id, "number": tool.number},
        "private": {"id": private.id, "number": private.number},
        "injection": {"id": injection.id, "number": injection.number},
        "projects": projects,
        "file_id": file.id,
    }
    connection_file = case / "connection.json"
    connection_file.write_text(json.dumps(config))
    connection_file.chmod(0o600)
    print("Disposable browser fixture ready", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    serve(parser.parse_args().case)

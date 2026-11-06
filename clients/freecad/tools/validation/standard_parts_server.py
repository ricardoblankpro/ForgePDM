"""Disposable loopback server for the live standard-parts acceptance fixture."""
# ruff: noqa: E402 -- isolate the server / select repository code before imports.

import json
import os
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

root = Path(tempfile.mkdtemp(prefix="forgepdm-standard-live-"))
os.environ["FORGEPDM_DATABASE"] = str(root / "db.sqlite3")
os.environ["FORGEPDM_FILE_ROOT"] = str(root / "files")
import uvicorn
from forgepdm.application.auth import hash_password
from forgepdm.main import create_app

app = create_app(root / "db.sqlite3")
uid, project = str(uuid4()), str(uuid4())
now = datetime.now(timezone.utc).isoformat()
with app.state.database.transaction() as connection:
    connection.execute(
        "INSERT INTO users(id,username,display_name,enabled,created_at,password_hash,role) VALUES (?,'pilot','Pilot',1,?,?,'admin')",
        (uid, now, hash_password("isolated-test-password")),
    )
    connection.execute(
        "INSERT INTO projects(id,project_number,name,archived,created_at) VALUES (?,'TEST-S','Disposable standard parts pilot',0,?)",
        (project, now),
    )
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen()
config = dict(
    repository=str(Path(__file__).resolve().parents[4]),
    root=str(root),
    url="http://127.0.0.1:" + str(sock.getsockname()[1]),
    project=project,
    user=uid,
)
Path("/tmp/forgepdm-standard-live-config.json").write_text(json.dumps(config))
uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])

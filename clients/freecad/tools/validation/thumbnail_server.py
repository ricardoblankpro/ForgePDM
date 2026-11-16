"""Disposable loopback server for native and browser thumbnail acceptance."""

import argparse
import json
import os
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def serve(directory):
    case = Path(directory).absolute()
    case.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.environ["FORGEPDM_DATABASE"] = str(case / "metadata.sqlite3")
    os.environ["FORGEPDM_FILE_ROOT"] = str(case / "files")
    os.environ["FORGEPDM_SUPPLIER_LOOKUP"] = "0"
    import uvicorn

    from forgepdm.application.auth import hash_password
    from forgepdm.main import create_app

    app = create_app()
    password, identifier, project = secrets.token_urlsafe(24), str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with app.state.database.transaction() as c:
        c.execute(
            "INSERT INTO users(id,username,display_name,enabled,created_at,password_hash,role) "
            "VALUES (?,'thumbnail-pilot','Thumbnail acceptance',1,?,?,'admin')",
            (identifier, now, hash_password(password)),
        )
        c.execute(
            "INSERT INTO projects(id,project_number,name,archived,created_at) VALUES (?,'QA-THUMB','Disposable thumbnail acceptance',0,?)",
            (project, now),
        )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    config = {
        "base_url": "http://127.0.0.1:" + str(listener.getsockname()[1]),
        "username": "thumbnail-pilot",
        "password": password,
    }
    path = case / "connection.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    print("Disposable thumbnail fixture ready", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    serve(parser.parse_args().case)

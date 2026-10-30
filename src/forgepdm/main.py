"""FastAPI application factory."""

import os
from pathlib import Path

from fastapi import FastAPI

from forgepdm.api.v1 import routes
from forgepdm.application.auth import AuthService
from forgepdm.application.authorization import AuthorizationService
from forgepdm.application.bom import BOMService
from forgepdm.application.catalog import CatalogService
from forgepdm.application.datasets import DatasetService
from forgepdm.application.items import ItemService
from forgepdm.application.manifests import ManifestService
from forgepdm.application.revisions import RevisionService
from forgepdm.infrastructure.database import Database
from forgepdm.infrastructure.storage import DEFAULT_MAX_UPLOAD_BYTES, FileStorage


def create_app(database_path: str | Path | None = None) -> FastAPI:
    path = Path(database_path or os.environ.get("FORGEPDM_DATABASE", "var/forgepdm.sqlite3"))
    database = Database(path)
    database.initialize()
    storage_root = Path(os.environ.get("FORGEPDM_FILE_ROOT", "var/files"))
    max_upload_bytes = int(
        os.environ.get("FORGEPDM_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    )
    storage = FileStorage(storage_root, max_upload_bytes)
    authorization = AuthorizationService(database)
    revisions = RevisionService(database, authorization)
    app = FastAPI(title="ForgePDM API", version="0.1.0")
    app.state.database = database
    app.state.auth_service = AuthService(database)
    app.state.authorization_service = authorization
    app.state.catalog_service = CatalogService(database, authorization)
    app.state.bom_service = BOMService(database, authorization, revisions)
    app.state.item_service = ItemService(database)
    app.state.revision_service = revisions
    app.state.manifest_service = ManifestService(database, authorization, revisions)
    app.state.dataset_service = DatasetService(database, storage, authorization, revisions)
    app.state.file_storage = storage
    app.include_router(routes.router)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "forgepdm"}

    return app


app = create_app()

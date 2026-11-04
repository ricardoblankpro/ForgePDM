"""FastAPI application factory."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from forgepdm.api.v1 import drawings, management, routes, tree_status
from forgepdm.application.auth import AuthService
from forgepdm.application.authorization import AuthorizationService
from forgepdm.application.bom import BOMService
from forgepdm.application.catalog import CatalogService
from forgepdm.application.checkins import CheckInService
from forgepdm.application.datasets import DatasetService
from forgepdm.application.drawings import DrawingService
from forgepdm.application.items import ItemService
from forgepdm.application.management import ManagementService
from forgepdm.application.manifests import ManifestService
from forgepdm.application.revisions import RevisionService
from forgepdm.application.tree_status import TreeStatusService
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
    app.state.management_service = ManagementService(database)
    app.state.auth_service = AuthService(database)
    app.state.authorization_service = authorization
    app.state.catalog_service = CatalogService(database, authorization)
    app.state.tree_status_service = TreeStatusService(database, authorization)
    app.state.bom_service = BOMService(database, authorization, revisions)
    app.state.item_service = ItemService(database)
    app.state.revision_service = revisions
    app.state.checkin_service = CheckInService(database, storage, authorization, revisions)
    app.state.manifest_service = ManifestService(database, authorization, revisions)
    app.state.dataset_service = DatasetService(database, storage, authorization, revisions)
    app.state.drawing_service = DrawingService(database, storage, authorization, revisions)
    app.state.file_storage = storage
    app.include_router(routes.router)
    app.include_router(management.router)
    app.include_router(tree_status.router)
    app.include_router(drawings.router)
    app.mount("/app", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")

    @app.middleware("http")
    async def web_headers(request, call_next):
        response = await call_next(request)
        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self'; connect-src 'self'; frame-src blob:; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "forgepdm"}

    return app


app = create_app()

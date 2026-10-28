"""Versioned API routes for the initial item workflow."""

from decimal import Decimal
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File as MultipartFile,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from forgepdm.application.auth import AuthService, AuthenticationError
from forgepdm.application.authorization import AuthorizationService
from forgepdm.application.bom import BOMService
from forgepdm.application.datasets import DatasetService
from forgepdm.application.items import ItemService
from forgepdm.application.revisions import RevisionService
from forgepdm.domain.entities import (
    Checkout,
    Conflict,
    DatasetType,
    Forbidden,
    ItemKind,
    LifecycleState,
    NotFound,
    User,
)
from forgepdm.infrastructure.storage import (
    BlobIntegrityError,
    BlobNotFound,
    EmptyUpload,
    FileStorage,
    UploadTooLarge,
)


router = APIRouter(prefix="/api/v1")
bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_bom_service(request: Request) -> BOMService:
    return request.app.state.bom_service


def get_authorization_service(request: Request) -> AuthorizationService:
    return request.app.state.authorization_service


def get_dataset_service(request: Request) -> DatasetService:
    return request.app.state.dataset_service


def get_item_service(request: Request) -> ItemService:
    return request.app.state.item_service


def get_revision_service(request: Request) -> RevisionService:
    return request.app.state.revision_service


def get_file_storage(request: Request) -> FileStorage:
    return request.app.state.file_storage


class CreateItemRequest(BaseModel):
    kind: ItemKind
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    project_id: UUID | None = None
    change_note: str = Field(default="Initial revision", max_length=2000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1024)


class CheckInRequest(BaseModel):
    change_note: str = Field(min_length=1, max_length=2000)


class LifecycleTransitionRequest(BaseModel):
    target: LifecycleState


class NewRevisionRequest(BaseModel):
    change_note: str = Field(min_length=1, max_length=2000)


class BOMLineRequest(BaseModel):
    component_revision_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    position: int = Field(gt=0)


class ReplaceBOMRequest(BaseModel):
    lines: list[BOMLineRequest]


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return auth_service.authenticate(credentials.credentials)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


@router.post("/auth/login")
def login(payload: LoginRequest, auth_service: AuthService = Depends(get_auth_service)):
    try:
        token, user, expires_at = auth_service.login(payload.username, payload.password)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": _user_response(user),
    }


@router.get("/auth/me")
def get_current_user(user: User = Depends(current_user)):
    return _user_response(user)


@router.post(
    "/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: User = Depends(current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    auth_service.logout(credentials.credentials, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(
    payload: CreateItemRequest,
    user: User = Depends(current_user),
    service: ItemService = Depends(get_item_service),
    authorization: AuthorizationService = Depends(get_authorization_service),
    revisions: RevisionService = Depends(get_revision_service),
):
    """Create an Item and its initial Working revision atomically."""
    try:
        project_id = str(payload.project_id) if payload.project_id else None
        authorization.require_create_item(user, project_id)
        item = service.create_item(
            kind=payload.kind,
            name=payload.name,
            description=payload.description,
            project_id=project_id,
            created_by=user.id,
            change_note=payload.change_note,
        )
        checkout = revisions.current_checkout(user, item.current_revision_id)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {**_item_response(item), "current_checkout": _checkout_response(checkout)}


@router.get("/items/{item_id}")
def get_item(
    item_id: UUID,
    user: User = Depends(current_user),
    service: ItemService = Depends(get_item_service),
    authorization: AuthorizationService = Depends(get_authorization_service),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        authorization.require_read_item(user, str(item_id))
        item, revision = service.get_item(str(item_id))
        checkout = revisions.current_checkout(user, revision.id)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=404, detail="item not found") from error
    return {
        **_item_response(item),
        "current_revision": {
            "id": revision.id,
            "label": revision.label,
            "sequence": revision.sequence,
            "lifecycle_state": revision.lifecycle_state.value,
            "change_note": revision.change_note,
        },
        "current_checkout": _checkout_response(checkout),
    }


@router.post("/revisions/{revision_id}/checkout")
def acquire_checkout(
    revision_id: UUID,
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        checkout = revisions.acquire_checkout(user, str(revision_id))
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _checkout_response(checkout)


@router.post("/revisions/{revision_id}/checkout/renew")
def renew_checkout(
    revision_id: UUID,
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        checkout = revisions.renew_checkout(user, str(revision_id))
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _checkout_response(checkout)


@router.get("/revisions/{revision_id}/checkout")
def get_checkout(
    revision_id: UUID,
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        checkout = revisions.current_checkout(user, str(revision_id))
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=404, detail="item revision not found") from error
    return _checkout_response(checkout)


@router.post("/revisions/{revision_id}/checkout/release")
def release_checkout(
    revision_id: UUID,
    reason: str = Query(default="", max_length=500),
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        checkout = revisions.release_checkout(user, str(revision_id), reason)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _checkout_response(checkout)


@router.post(
    "/revisions/{revision_id}/checkin",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def check_in(
    revision_id: UUID,
    payload: CheckInRequest,
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        revisions.check_in(user, str(revision_id), payload.change_note)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/revisions/{revision_id}/lifecycle",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def transition_lifecycle(
    revision_id: UUID,
    payload: LifecycleTransitionRequest,
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        revisions.transition_lifecycle(user, str(revision_id), payload.target)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/items/{item_id}/revisions", status_code=status.HTTP_201_CREATED)
def create_next_revision(
    item_id: UUID,
    payload: NewRevisionRequest,
    user: User = Depends(current_user),
    revisions: RevisionService = Depends(get_revision_service),
):
    try:
        revision, checkout = revisions.create_next_revision(
            user, str(item_id), payload.change_note
        )
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "id": revision.id,
        "item_id": revision.item_id,
        "label": revision.label,
        "sequence": revision.sequence,
        "lifecycle_state": revision.lifecycle_state.value,
        "change_note": revision.change_note,
        "created_by": revision.created_by,
        "created_at": revision.created_at.isoformat(),
        "checkout": _checkout_response(checkout),
    }


@router.get("/revisions/{revision_id}/bom")
def get_bom(
    revision_id: UUID,
    recursive: bool = Query(default=False),
    user: User = Depends(current_user),
    bom: BOMService = Depends(get_bom_service),
):
    try:
        return bom.get_bom(user, str(revision_id), recursive)
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=404, detail="item revision not found") from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/revisions/{revision_id}/bom")
def replace_bom(
    revision_id: UUID,
    payload: ReplaceBOMRequest,
    user: User = Depends(current_user),
    bom: BOMService = Depends(get_bom_service),
):
    try:
        return bom.replace_bom(
            user,
            str(revision_id),
            [
                {
                    "component_revision_id": str(line.component_revision_id),
                    "quantity": line.quantity,
                    "position": line.position,
                }
                for line in payload.lines
            ],
        )
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/items/{item_id}/where-used")
def where_used(
    item_id: UUID,
    user: User = Depends(current_user),
    bom: BOMService = Depends(get_bom_service),
):
    try:
        return bom.where_used(user, str(item_id))
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=404, detail="item not found") from error


@router.post("/revisions/{revision_id}/datasets", status_code=status.HTTP_201_CREATED)
def attach_dataset_file(
    revision_id: UUID,
    file: UploadFile = MultipartFile(...),
    dataset_type: DatasetType = Form(...),
    name: str | None = Form(default=None, max_length=200),
    user: User = Depends(current_user),
    authorization: AuthorizationService = Depends(get_authorization_service),
    revisions: RevisionService = Depends(get_revision_service),
    datasets: DatasetService = Depends(get_dataset_service),
):
    try:
        authorization.require_edit_revision(user, str(revision_id))
        revisions.require_checkout_owner(user, str(revision_id))
        fallback_name = PurePosixPath((file.filename or "").replace("\\", "/")).stem
        dataset, file_record = datasets.attach_file(
            user=user,
            revision_id=str(revision_id),
            dataset_type=dataset_type,
            dataset_name=name if name is not None else fallback_name,
            filename=file.filename,
            media_type=file.content_type,
            source=file.file,
        )
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UploadTooLarge as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except EmptyUpload as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        file.file.close()
    return {
        "id": dataset.id,
        "revision_id": dataset.revision_id,
        "dataset_type": dataset.dataset_type.value,
        "name": dataset.name,
        "created_by": dataset.created_by,
        "created_at": dataset.created_at.isoformat(),
        "files": [
            {
                "id": file_record.id,
                "original_filename": file_record.original_filename,
                "media_type": file_record.media_type,
                "byte_size": file_record.byte_size,
                "content_hash": file_record.content_hash,
                "download_url": f"/api/v1/files/{file_record.id}",
            }
        ],
    }


@router.get("/revisions/{revision_id}/datasets")
def list_datasets(
    revision_id: UUID,
    user: User = Depends(current_user),
    datasets: DatasetService = Depends(get_dataset_service),
):
    try:
        return datasets.list_revision(user, str(revision_id))
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=404, detail="item revision not found") from error


@router.get("/files/{file_id}", response_class=FileResponse)
def download_file(
    file_id: UUID,
    user: User = Depends(current_user),
    datasets: DatasetService = Depends(get_dataset_service),
    storage: FileStorage = Depends(get_file_storage),
):
    try:
        file_record = datasets.get_file(user, str(file_id))
    except NotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Forbidden as error:
        raise HTTPException(status_code=404, detail="file not found") from error
    try:
        path = storage.verify(
            file_record.storage_key, file_record.content_hash, file_record.byte_size
        )
    except (BlobNotFound, BlobIntegrityError) as error:
        raise HTTPException(status_code=500, detail="stored file integrity check failed") from error
    return FileResponse(path, media_type=file_record.media_type, filename=file_record.original_filename)


def _item_response(item):
    return {
        "id": item.id,
        "number": item.number,
        "kind": item.kind.value,
        "name": item.name,
        "description": item.description,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat(),
        "current_revision_id": item.current_revision_id,
    }


def _user_response(user: User):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


def _checkout_response(checkout: Checkout | None):
    if checkout is None:
        return None
    return {
        "id": checkout.id,
        "revision_id": checkout.revision_id,
        "user_id": checkout.user_id,
        "acquired_at": checkout.acquired_at.isoformat(),
        "expires_at": checkout.expires_at.isoformat(),
        "version": checkout.version,
    }

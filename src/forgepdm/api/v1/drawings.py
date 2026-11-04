"""Explicit publication/read APIs for source-pinned drawing PDFs."""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile

from forgepdm.api.v1.routes import current_user
from forgepdm.domain.entities import Conflict, Forbidden, NotFound, User
from forgepdm.infrastructure.storage import EmptyUpload, UploadTooLarge

router = APIRouter(prefix="/api/v1/revisions")


def invoke(function, *args):
    try:
        return function(*args)
    except (Forbidden, NotFound) as error:
        raise HTTPException(404, "drawing revision or operation is not available") from error
    except Conflict as error:
        raise HTTPException(409, str(error)) from error
    except UploadTooLarge as error:
        raise HTTPException(413, str(error)) from error
    except (ValueError, TypeError, AttributeError, EmptyUpload) as error:
        raise HTTPException(422, str(error)) from error


@router.post("/{revision_id}/drawings", status_code=201)
def publish(
    revision_id: UUID,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    file: Annotated[UploadFile, File()],
    intent_json: Annotated[str, Form(max_length=65536)],
):
    try:
        try:
            intent = json.loads(intent_json)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, "invalid drawing intent JSON") from error
        return invoke(
            request.app.state.drawing_service.publish, user, str(revision_id), intent, file.file
        )
    finally:
        file.file.close()


@router.get("/{revision_id}/drawings")
def drawings(
    revision_id: UUID,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
):
    response.headers["Cache-Control"] = "no-store"
    return invoke(request.app.state.drawing_service.list_revision, user, str(revision_id))


@router.get("/{revision_id}/drawing-operations/{operation_id}")
def operation(
    revision_id: UUID,
    operation_id: UUID,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
):
    response.headers["Cache-Control"] = "no-store"
    return invoke(
        request.app.state.drawing_service.status, user, str(revision_id), str(operation_id)
    )

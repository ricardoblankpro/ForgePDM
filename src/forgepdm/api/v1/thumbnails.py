"""Authorized thumbnail ingress and exact-source image retrieval."""

import base64
import binascii
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from forgepdm.api.v1.routes import current_user
from forgepdm.application.thumbnails import PROFILE
from forgepdm.domain.entities import Conflict, Forbidden, NotFound
from forgepdm.infrastructure.storage import StorageError

router = APIRouter(prefix="/api/v1/files", tags=["thumbnails"])


class ThumbnailUpload(BaseModel):
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_profile: str = Field(default=PROFILE, max_length=40)
    png_base64: str = Field(min_length=1, max_length=1398104)


@router.post("/{file_id}/thumbnail", status_code=201)
def attach_thumbnail(
    file_id: UUID, payload: ThumbnailUpload, request: Request, user=Depends(current_user)
):
    try:
        raw = base64.b64decode(payload.png_base64, validate=True)
        return request.app.state.thumbnail_service.attach(
            user, str(file_id), payload.source_content_hash, raw, payload.render_profile
        )
    except (NotFound, Forbidden) as error:
        raise HTTPException(status_code=404, detail="source file unavailable") from error
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, binascii.Error) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{file_id}/thumbnail")
def get_thumbnail(file_id: UUID, request: Request, user=Depends(current_user)):
    try:
        path, metadata = request.app.state.thumbnail_service.get(user, str(file_id))
    except (NotFound, Forbidden) as error:
        raise HTTPException(status_code=404, detail="preview unavailable") from error
    except (StorageError, Conflict) as error:
        raise HTTPException(
            status_code=500, detail="stored preview integrity check failed"
        ) from error
    return FileResponse(
        path,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-ForgePDM-Source-Hash": metadata["source_content_hash"],
            "X-Content-SHA256": metadata["content_hash"],
        },
    )

"""Bounded status reads; unavailable IDs do not disclose item membership."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from forgepdm.api.v1.routes import current_user
from forgepdm.domain.entities import User

router = APIRouter(prefix="/api/v1/status")


class RevisionStatusRequest(BaseModel):
    model_config = {"extra": "forbid"}
    revision_ids: list[UUID] = Field(min_length=1, max_length=200)


@router.post("/revisions")
def revision_status(
    payload: RevisionStatusRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(current_user)],
):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.tree_status_service.revisions(
        user, [str(value) for value in payload.revision_ids]
    )

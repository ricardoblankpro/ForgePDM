"""Simple revision description API used by the web and CAD clients."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from forgepdm.api.v1.materials import invoke
from forgepdm.api.v1.routes import current_user
from forgepdm.application.descriptions import DescriptionService
from forgepdm.domain.entities import User

router = APIRouter(prefix="/api/v1")


def service(request: Request):
    return DescriptionService(
        request.app.state.database,
        request.app.state.authorization_service,
        request.app.state.revision_service,
    )


class DescriptionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    description: str = Field(default="", max_length=1000)
    material_revision_id: UUID | None = None
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("/revisions/{revision_id}/description")
def read(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[DescriptionService, Depends(service)],
):
    return invoke(lambda: svc.read(user, str(revision_id)))


@router.put("/revisions/{revision_id}/description")
def save(
    revision_id: UUID,
    payload: DescriptionRequest,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[DescriptionService, Depends(service)],
):
    return invoke(
        lambda: svc.save(
            user,
            str(revision_id),
            payload.description,
            str(payload.material_revision_id) if payload.material_revision_id else None,
            payload.expected_token,
        )
    )

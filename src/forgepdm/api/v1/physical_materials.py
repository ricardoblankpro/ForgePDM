"""Library physical material links and computed native part mass."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from forgepdm.api.v1.materials import invoke
from forgepdm.api.v1.routes import current_user
from forgepdm.application.physical_materials import PhysicalMaterialService
from forgepdm.domain.entities import User

router = APIRouter(prefix="/api/v1")


def service(request: Request):
    return PhysicalMaterialService(
        request.app.state.database,
        request.app.state.authorization_service,
        request.app.state.revision_service,
    )


class Link(BaseModel):
    physical_material: dict
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("/revisions/{revision_id}/physical-material")
def read(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[PhysicalMaterialService, Depends(service)],
):
    return invoke(lambda: svc.read(user, str(revision_id)))


@router.put("/revisions/{revision_id}/physical-material")
def save(
    revision_id: UUID,
    payload: Link,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[PhysicalMaterialService, Depends(service)],
):
    return invoke(
        lambda: svc.save(user, str(revision_id), payload.physical_material, payload.expected_token)
    )


@router.get("/revisions/{revision_id}/mass")
def mass(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[PhysicalMaterialService, Depends(service)],
):
    return invoke(lambda: svc.mass(user, str(revision_id)))

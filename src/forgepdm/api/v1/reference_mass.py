"""Supplier reference mass and administrator-managed reference feeds."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from forgepdm.api.v1.materials import invoke
from forgepdm.api.v1.routes import current_user
from forgepdm.application.reference_mass import ReferenceMassService
from forgepdm.domain.entities import User

router = APIRouter(prefix="/api/v1")


def service(request: Request):
    return request.app.state.reference_mass_service


@router.get("/revisions/{revision_id}/reference-mass")
def read(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[ReferenceMassService, Depends(service)],
):
    return invoke(lambda: svc.read(user, str(revision_id)))


@router.post("/revisions/{revision_id}/reference-mass/lookup")
def lookup(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[ReferenceMassService, Depends(service)],
):
    return invoke(lambda: svc.lookup(user, str(revision_id)))


class Feed(BaseModel):
    csv_text: str = Field(max_length=1024 * 1024)


@router.post("/reference-masses/import")
def import_feed(
    payload: Feed,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[ReferenceMassService, Depends(service)],
):
    return invoke(lambda: svc.import_csv(user, payload.csv_text))


class ManualMass(BaseModel):
    model_config = {"extra": "forbid"}
    method: Literal["manual"]
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    mass_g: str = Field(max_length=100)
    note: str = Field(default="", max_length=500)


class EstimatedMass(BaseModel):
    model_config = {"extra": "forbid"}
    method: Literal["cad_estimate"]
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    geometry: dict
    volume_mm3: str = Field(max_length=100)
    shape_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    thread_mode: Literal["simplified", "modeled", "unknown"]
    generator_version: str = Field(min_length=1, max_length=100)


@router.put("/revisions/{revision_id}/reference-mass/fallback")
def save_fallback(
    revision_id: UUID,
    payload: ManualMass | EstimatedMass,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[ReferenceMassService, Depends(service)],
):
    return invoke(lambda: svc.save_fallback(user, str(revision_id), payload.model_dump()))

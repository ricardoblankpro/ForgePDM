"""Additive, authorized localization API; old description payloads stay unchanged."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from forgepdm.api.v1.materials import invoke
from forgepdm.api.v1.routes import current_user
from forgepdm.application.localization import LANGUAGES, LocalizationService

router = APIRouter(prefix="/api/v1")


class Change(BaseModel):
    operation: str
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str | None = None
    text: str | None = Field(default=None, max_length=1000)
    translation_id: UUID | None = None


def service(request):
    return LocalizationService(request.app.state.database, request.app.state.authorization_service)


@router.get("/languages")
def languages():
    return {"languages": [{"tag": k, "label": v} for k, v in LANGUAGES.items()]}


@router.get("/items/{item_id}/localized-texts")
def texts(
    item_id: UUID,
    request: Request,
    revision_id: UUID | None = None,
    language: str | None = None,
    user=Depends(current_user),
):
    return invoke(
        lambda: service(request).list(
            user, str(item_id), str(revision_id) if revision_id else None, language
        )
    )


@router.get("/revisions/{revision_id}/localized-texts")
def revision_texts(revision_id: UUID, request: Request, user=Depends(current_user)):
    def read():
        with request.app.state.database.connection() as c:
            request.app.state.authorization_service.require_read_revision(user, str(revision_id), c)
            item = c.execute(
                "SELECT item_id FROM item_revisions WHERE id=?", (str(revision_id),)
            ).fetchone()[0]
        return service(request).list(user, item, str(revision_id))

    return invoke(read)


@router.get("/localized-texts/{source_id}/proposal-availability")
def proposal_availability(
    source_id: str, language: str, request: Request, user=Depends(current_user)
):
    return invoke(lambda: service(request).proposal_availability(user, source_id, language))


@router.post("/localized-texts/{source_id}")
def change(source_id: str, payload: Change, request: Request, user=Depends(current_user)):
    return invoke(
        lambda: service(request).change(
            user,
            source_id,
            payload.operation,
            payload.expected_token,
            payload.language,
            payload.text,
            str(payload.translation_id) if payload.translation_id else None,
        )
    )


@router.post("/description-proposals")
def proposal(payload: dict, user=Depends(current_user)):
    from forgepdm.domain.description_generation import generate

    return invoke(lambda: generate(payload.get("specification"), payload.get("language")))

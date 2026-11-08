"""Material catalog, revision inputs and requirements endpoints."""

import csv
import io
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from forgepdm.api.v1.routes import current_user
from forgepdm.application.materials import MaterialService
from forgepdm.domain.entities import Conflict, Forbidden, NotFound, User

router = APIRouter(prefix="/api/v1")


def service(request: Request):
    return MaterialService(
        request.app.state.database,
        request.app.state.authorization_service,
        request.app.state.revision_service,
    )


def invoke(call):
    try:
        return call()
    except (Conflict, Forbidden, NotFound, ValueError) as error:
        code = (
            409
            if isinstance(error, Conflict)
            else 403
            if isinstance(error, Forbidden)
            else 404
            if isinstance(error, NotFound)
            else 422
        )
        raise HTTPException(code, str(error)) from error


class Specification(BaseModel):
    specification: dict
    expected_token: str


class InputLine(BaseModel):
    component_revision_id: UUID
    quantity: str
    uom: str
    allowance_percent: str = "0"
    note: str = Field(default="", max_length=2000)


class Inputs(BaseModel):
    lines: list[InputLine] = Field(max_length=1000)
    expected_token: str
    readiness: Literal["unreviewed", "complete", "not_applicable"] = "unreviewed"
    reason: str = Field(default="", max_length=2000)


class Root(BaseModel):
    root_revision_id: UUID
    quantity: str
    project_context: str | None = None


class Demand(BaseModel):
    roots: list[Root] = Field(min_length=1, max_length=100)
    approved: bool = False
    save: bool = False


@router.get("/materials/capabilities")
def capabilities(user: Annotated[User, Depends(current_user)]):
    return {
        "version": 1,
        "number_series": "M",
        "physical_material_version": 1,
        "units": ["ea", "mm", "cm", "m", "mm2", "m2", "g", "kg"],
    }


@router.get("/revisions/{revision_id}/material-specification")
def read_spec(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(lambda: svc.specification(user, str(revision_id)))


@router.put("/revisions/{revision_id}/material-specification")
def write_spec(
    revision_id: UUID,
    payload: Specification,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(
        lambda: svc.save_specification(
            user, str(revision_id), payload.specification, payload.expected_token
        )
    )


@router.get("/revisions/{revision_id}/material-bom")
def read_inputs(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(lambda: svc.read(user, str(revision_id)))


@router.put("/revisions/{revision_id}/material-bom")
def write_inputs(
    revision_id: UUID,
    payload: Inputs,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(
        lambda: svc.replace(
            user,
            str(revision_id),
            [line.model_dump(mode="json") for line in payload.lines],
            payload.expected_token,
            payload.readiness,
            payload.reason,
        )
    )


@router.post("/requirements/calculate")
def calculate(
    payload: Demand,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(
        lambda: svc.calculate(
            user,
            [root.model_dump(mode="json") for root in payload.roots],
            payload.approved,
            payload.save,
        )
    )


@router.get("/requirements/snapshots/{snapshot_id}")
def snapshot(
    snapshot_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(lambda: svc.snapshot(user, str(snapshot_id)))


@router.get("/requirements/snapshots/{snapshot_id}/csv")
def export_csv(
    snapshot_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    value = invoke(lambda: svc.snapshot(user, str(snapshot_id)))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Item Code", "Quantity", "UOM"])
    for row in value["totals"]:
        writer.writerow([row["item_code"], row["quantity"], row["uom"]])
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="material-requirements.csv"'},
    )


@router.get("/items/{item_id}/material-where-used")
def where_used(
    item_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    def query():
        svc.authorization.require_read_item(user, str(item_id))
        result = []
        with svc.database.connection() as c:
            c.execute("BEGIN")
            rows = c.execute(
                "SELECT l.*,i.number AS parent_item_number,parent.label AS parent_revision_label FROM material_bom_lines l JOIN item_revisions target ON target.id=l.component_revision_id JOIN item_revisions parent ON parent.id=l.parent_revision_id JOIN items i ON i.id=parent.item_id WHERE target.item_id=? ORDER BY i.number,parent.sequence,l.position",
                (str(item_id),),
            ).fetchall()
            for row in rows:
                try:
                    svc._revision(c, user, row["parent_revision_id"])
                except Forbidden:
                    continue
                result.append({"relationship": "material_input", **dict(row)})
        return result

    return invoke(query)


@router.get("/revisions/{revision_id}/engineering-properties")
def read_properties(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(lambda: svc.specification(user, str(revision_id)))


@router.put("/revisions/{revision_id}/engineering-properties")
def write_properties(
    revision_id: UUID,
    payload: Specification,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(
        lambda: svc.save_properties(
            user, str(revision_id), payload.specification, payload.expected_token
        )
    )


@router.get("/revisions/{revision_id}/material-evidence")
def mass_evidence(
    revision_id: UUID,
    user: Annotated[User, Depends(current_user)],
    svc: Annotated[MaterialService, Depends(service)],
):
    return invoke(lambda: svc.evidence(user, str(revision_id)))

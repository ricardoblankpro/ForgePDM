"""Authenticated web management API; domain policy lives in the application layer."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from forgepdm.api.v1.routes import current_user
from forgepdm.domain.entities import Conflict, Forbidden, NotFound, User

router = APIRouter(prefix="/api/v1")


class UserCreate(BaseModel):
    model_config = {"extra": "forbid"}
    username: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=4, max_length=1024)
    role: Literal["admin", "user"] = "user"


class UserUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    display_name: str = Field(min_length=1, max_length=200)
    enabled: bool
    role: Literal["admin", "user"]


class PasswordReset(BaseModel):
    model_config = {"extra": "forbid"}
    password: str = Field(min_length=4, max_length=1024)


class PasswordChange(BaseModel):
    model_config = {"extra": "forbid"}
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=4, max_length=1024)


class ProjectSave(BaseModel):
    model_config = {"extra": "forbid"}
    project_number: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    customer: str = Field(default="", max_length=200)
    due_date: date | None = None
    description: str = Field(default="", max_length=4000)
    archived: bool = False


class Membership(BaseModel):
    model_config = {"extra": "forbid"}
    role: Literal["owner", "editor", "viewer"]


def call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (Forbidden, NotFound, Conflict, ValueError) as error:
        code = (
            403
            if isinstance(error, Forbidden)
            else 404
            if isinstance(error, NotFound)
            else 409
            if isinstance(error, Conflict)
            else 422
        )
        raise HTTPException(status_code=code, detail=str(error)) from error


def service(request: Request):
    return request.app.state.management_service


@router.get("/admin/users")
def users(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return call(service(request).users, user, q, limit, offset)


@router.post("/admin/users", status_code=201)
def create_user(
    payload: UserCreate, request: Request, user: Annotated[User, Depends(current_user)]
):
    return call(service(request).create_user, user, **payload.model_dump())


@router.put("/admin/users/{identifier}")
def update_user(
    identifier: UUID,
    payload: UserUpdate,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    return call(service(request).update_user, user, str(identifier), **payload.model_dump())


@router.post("/admin/users/{identifier}/reset-password")
def reset_password(
    identifier: UUID,
    payload: PasswordReset,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    return call(service(request).reset_password, user, str(identifier), payload.password)


@router.post("/auth/password")
def change_password(
    payload: PasswordChange, request: Request, user: Annotated[User, Depends(current_user)]
):
    return call(
        service(request).change_password, user, payload.current_password, payload.new_password
    )


@router.get("/management/projects")
def projects(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return call(service(request).projects, user, include_archived, limit, offset)


@router.post("/management/projects", status_code=201)
def create_project(
    payload: ProjectSave, request: Request, user: Annotated[User, Depends(current_user)]
):
    return call(service(request).save_project, user, payload.model_dump(mode="json"))


@router.put("/management/projects/{identifier}")
def update_project(
    identifier: UUID,
    payload: ProjectSave,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    return call(
        service(request).save_project, user, payload.model_dump(mode="json"), str(identifier)
    )


@router.get("/management/projects/{identifier}/members")
def members(identifier: UUID, request: Request, user: Annotated[User, Depends(current_user)]):
    return call(service(request).members, user, str(identifier))


@router.put("/management/projects/{identifier}/members/{user_id}")
def set_member(
    identifier: UUID,
    user_id: UUID,
    payload: Membership,
    request: Request,
    user: Annotated[User, Depends(current_user)],
):
    return call(service(request).membership, user, str(identifier), str(user_id), payload.role)


@router.delete("/management/projects/{identifier}/members/{user_id}")
def remove_member(
    identifier: UUID, user_id: UUID, request: Request, user: Annotated[User, Depends(current_user)]
):
    return call(service(request).membership, user, str(identifier), str(user_id))


@router.get("/me/checkouts")
def checkouts(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return call(service(request).checkouts, user, limit, offset)


@router.get("/activity")
def activity(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    project_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: str = Query(default="", max_length=200),
    q: str = Query(default="", max_length=200),
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return call(
        service(request).activity,
        user,
        project_id=str(project_id) if project_id else None,
        actor_id=str(actor_id) if actor_id else None,
        action=action,
        query=q,
        start=start.isoformat() if start else None,
        end=end.isoformat() if end else None,
        limit=limit,
        offset=offset,
    )


@router.get("/activity/actors")
def activity_actors(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return call(service(request).activity_actors, user, limit, offset)

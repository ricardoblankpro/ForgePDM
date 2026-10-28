"""Core identity and revision entities, independent of the API and persistence."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class ItemKind(StrEnum):
    PART = "part"
    ASSEMBLY = "assembly"

    @property
    def number_prefix(self) -> str:
        return {ItemKind.PART: "P", ItemKind.ASSEMBLY: "A"}[self]


class LifecycleState(StrEnum):
    WORKING = "working"
    RELEASED = "released"
    OBSOLETE = "obsolete"


class DatasetType(StrEnum):
    NATIVE_CAD = "native_cad"
    DRAWING = "drawing"
    NEUTRAL = "neutral"
    DOCUMENT = "document"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class User:
    id: str
    username: str
    display_name: str
    enabled: bool
    role: str = "user"


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    project_number: str
    name: str
    archived: bool


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    number: str
    kind: ItemKind
    name: str
    description: str
    created_by: str
    created_at: datetime
    current_revision_id: str


@dataclass(frozen=True, slots=True)
class ItemRevision:
    id: str
    item_id: str
    label: str
    sequence: int
    lifecycle_state: LifecycleState
    change_note: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class File:
    id: str
    content_hash: str
    byte_size: int
    media_type: str
    original_filename: str
    storage_key: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Dataset:
    id: str
    revision_id: str
    dataset_type: DatasetType
    name: str
    file_ids: tuple[str, ...]
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Checkout:
    id: str
    revision_id: str
    user_id: str
    acquired_at: datetime
    expires_at: datetime
    released_at: datetime | None
    version: int


@dataclass(frozen=True, slots=True)
class BOMLine:
    id: str
    parent_revision_id: str
    component_revision_id: str
    quantity: Decimal
    position: int
    created_by: str
    created_at: datetime


class DomainError(Exception):
    """Base class for expected domain rule failures."""


class NotFound(DomainError):
    """A requested domain record does not exist."""


class Conflict(DomainError):
    """A request conflicts with existing domain state."""


class Forbidden(DomainError):
    """The authenticated user lacks permission for an operation."""

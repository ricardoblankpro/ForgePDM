"""SQLite database adapter and initial schema."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    project_number TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lifecycle_states (
    name TEXT PRIMARY KEY,
    terminal INTEGER NOT NULL CHECK (terminal IN (0, 1))
);
CREATE TABLE IF NOT EXISTS number_counters (
    item_kind TEXT PRIMARY KEY CHECK (item_kind IN ('part', 'assembly')),
    next_value INTEGER NOT NULL CHECK (next_value > 0)
);
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    number TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('part', 'assembly')),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    current_revision_id TEXT NOT NULL REFERENCES item_revisions(id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE IF NOT EXISTS project_items (
    project_id TEXT NOT NULL REFERENCES projects(id),
    item_id TEXT NOT NULL REFERENCES items(id),
    added_at TEXT NOT NULL,
    PRIMARY KEY (project_id, item_id)
);
CREATE TABLE IF NOT EXISTS item_revisions (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id),
    label TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    lifecycle_state TEXT NOT NULL REFERENCES lifecycle_states(name),
    change_note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (item_id, sequence),
    UNIQUE (item_id, label)
);
CREATE INDEX IF NOT EXISTS item_revisions_item_idx ON item_revisions(item_id, sequence);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL REFERENCES users(id),
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS audit_events_entity_idx ON audit_events(entity_type, entity_id, occurred_at);
INSERT OR IGNORE INTO lifecycle_states(name, terminal) VALUES
    ('working', 0), ('released', 0), ('obsolete', 1);
"""

AUTHORIZATION_SCHEMA = """
ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user'));
CREATE TABLE project_memberships (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    granted_at TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE auth_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX auth_sessions_user_idx ON auth_sessions(user_id);
CREATE INDEX project_memberships_user_idx ON project_memberships(user_id, project_id);
"""

DATASET_SCHEMA = """
CREATE TABLE files (
    id TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    media_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX files_hash_idx ON files(content_hash);
CREATE TABLE datasets (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    dataset_type TEXT NOT NULL,
    name TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE INDEX datasets_revision_idx ON datasets(revision_id, created_at);
CREATE TABLE dataset_files (
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    file_id TEXT NOT NULL REFERENCES files(id),
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    PRIMARY KEY (dataset_id, file_id),
    UNIQUE (dataset_id, position)
);
CREATE INDEX dataset_files_file_idx ON dataset_files(file_id);
"""

CHECKOUT_SCHEMA = """
ALTER TABLE item_revisions ADD COLUMN modified_at TEXT;
UPDATE item_revisions SET modified_at = created_at WHERE modified_at IS NULL;
CREATE TABLE checkouts (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);
CREATE UNIQUE INDEX checkout_one_active_revision_idx
    ON checkouts(revision_id) WHERE released_at IS NULL;
CREATE INDEX checkouts_user_idx ON checkouts(user_id, expires_at);
"""

BOM_SCHEMA = """
CREATE TABLE bom_lines (
    id TEXT PRIMARY KEY,
    parent_revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    component_revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    quantity TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position > 0),
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (parent_revision_id, position)
);
CREATE INDEX bom_component_idx ON bom_lines(component_revision_id, parent_revision_id);
"""

MIGRATIONS = (
    (1, SCHEMA),
    (2, AUTHORIZATION_SCHEMA),
    (3, DATASET_SCHEMA),
    (4, CHECKOUT_SCHEMA),
    (5, BOM_SCHEMA),
)


class Database:
    """Small SQLite connection factory; each operation owns its connection."""

    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            for version, sql in MIGRATIONS:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    applied = connection.execute(
                        "SELECT 1 FROM schema_version WHERE version = ?", (version,)
                    ).fetchone()
                    if not applied:
                        for statement in sql.split(";"):
                            if statement.strip():
                                connection.execute(statement)
                        connection.execute(
                            "INSERT INTO schema_version(version, applied_at) VALUES (?, datetime('now'))",
                            (version,),
                        )
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside an explicit write transaction."""
        connection = self.connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


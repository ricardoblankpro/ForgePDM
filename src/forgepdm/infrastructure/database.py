"""SQLite database adapter and initial schema."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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

MANIFEST_SCHEMA = """
CREATE TABLE dataset_manifests (
    dataset_id TEXT PRIMARY KEY REFERENCES datasets(id),
    source_file_id TEXT NOT NULL REFERENCES files(id),
    profile TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);
CREATE TABLE dataset_references (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES dataset_manifests(dataset_id),
    object_name TEXT NOT NULL,
    property_name TEXT NOT NULL,
    target_revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    target_dataset_id TEXT NOT NULL REFERENCES datasets(id),
    target_file_id TEXT NOT NULL REFERENCES files(id),
    target_object_name TEXT NOT NULL,
    UNIQUE(dataset_id, object_name, property_name)
);
CREATE INDEX dataset_reference_target_idx ON dataset_references(target_dataset_id);
"""

ATOMIC_CHECKIN_SCHEMA = """
CREATE TABLE checkin_operations (
    actor_id TEXT NOT NULL REFERENCES users(id),
    operation_id TEXT NOT NULL,
    revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    fingerprint TEXT NOT NULL CHECK(length(fingerprint) = 64),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(actor_id, operation_id)
);
CREATE INDEX checkin_operations_revision_idx ON checkin_operations(revision_id);
"""

MANAGEMENT_SCHEMA = """
ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0,1));
ALTER TABLE projects ADD COLUMN customer TEXT NOT NULL DEFAULT '';
ALTER TABLE projects ADD COLUMN due_date TEXT;
ALTER TABLE projects ADD COLUMN description TEXT NOT NULL DEFAULT '';
CREATE INDEX audit_events_time_idx ON audit_events(occurred_at,id);
"""

DRAWING_SCHEMA = """
CREATE TABLE drawing_publications (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    source_dataset_id TEXT NOT NULL,
    source_file_id TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    result_json TEXT NOT NULL,
    UNIQUE(created_by, operation_id),
    FOREIGN KEY(source_dataset_id,source_file_id) REFERENCES dataset_files(dataset_id,file_id)
);
CREATE TABLE drawing_pages (
    publication_id TEXT NOT NULL REFERENCES drawing_publications(id),
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    file_id TEXT NOT NULL REFERENCES files(id),
    page_name TEXT NOT NULL,
    page_label TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position>0),
    PRIMARY KEY(publication_id,page_name),
    UNIQUE(publication_id,position),
    FOREIGN KEY(dataset_id,file_id) REFERENCES dataset_files(dataset_id,file_id)
);
CREATE INDEX drawing_publications_revision_idx ON drawing_publications(revision_id,created_at,id);
"""

STANDARD_PARTS_SCHEMA = """
CREATE TABLE standard_specifications (
 item_id TEXT PRIMARY KEY REFERENCES items(id),
 scope TEXT NOT NULL,
 geometry_json TEXT NOT NULL,
 specification_json TEXT NOT NULL,
 UNIQUE(scope, specification_json)
);
CREATE TABLE dataset_standard_occurrences (
 dataset_id TEXT NOT NULL REFERENCES datasets(id),
 object_name TEXT NOT NULL,
 occurrence_id TEXT NOT NULL,
 revision_id TEXT NOT NULL REFERENCES item_revisions(id),
 geometry_json TEXT NOT NULL,
 PRIMARY KEY(dataset_id, object_name), UNIQUE(dataset_id, occurrence_id)
);
ALTER TABLE dataset_references ADD COLUMN target_subelement TEXT;
"""

SHARED_STANDARD_LIBRARY_SCHEMA = """
ALTER TABLE projects ADD COLUMN is_standard_library INTEGER NOT NULL DEFAULT 0 CHECK(is_standard_library IN (0,1));
CREATE UNIQUE INDEX projects_standard_library_idx ON projects(is_standard_library) WHERE is_standard_library=1;
CREATE TEMP TABLE _standard_library_seed AS SELECT lower(hex(randomblob(4)))||'-'||lower(hex(randomblob(2)))||'-4'||substr(lower(hex(randomblob(2))),1,3)||'-8'||substr(lower(hex(randomblob(2))),1,3)||'-'||lower(hex(randomblob(6))) AS id;
INSERT INTO projects(id,project_number,name,description,archived,created_at,is_standard_library)
SELECT id,CASE WHEN EXISTS(SELECT 1 FROM projects WHERE project_number='LIB-STANDARD') THEN 'LIB-STANDARD-'||id ELSE 'LIB-STANDARD' END,
'Standard Parts Library','Shared standard and purchased component catalog',0,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),1 FROM _standard_library_seed;
INSERT INTO project_memberships(project_id,user_id,role,granted_at)
SELECT p.id,u.id,CASE WHEN EXISTS(SELECT 1 FROM items i WHERE i.number_series='S' AND i.created_by=u.id) THEN 'editor' ELSE 'viewer' END,
strftime('%Y-%m-%dT%H:%M:%f+00:00','now') FROM projects p JOIN users u ON u.enabled=1 WHERE p.is_standard_library=1;
DELETE FROM project_items WHERE item_id IN (SELECT id FROM items WHERE number_series='S');
INSERT INTO project_items(project_id,item_id,added_at)
SELECT p.id,i.id,strftime('%Y-%m-%dT%H:%M:%f+00:00','now') FROM projects p JOIN items i ON i.number_series='S' WHERE p.is_standard_library=1;
UPDATE standard_specifications SET scope=(SELECT id FROM projects WHERE is_standard_library=1)
WHERE specification_json IN (SELECT specification_json FROM standard_specifications GROUP BY specification_json HAVING count(*)=1);
DROP TABLE _standard_library_seed;
"""

MIGRATIONS = (
    (1, SCHEMA),
    (2, AUTHORIZATION_SCHEMA),
    (3, DATASET_SCHEMA),
    (4, CHECKOUT_SCHEMA),
    (5, BOM_SCHEMA),
    (6, MANIFEST_SCHEMA),
    (7, ATOMIC_CHECKIN_SCHEMA),
    (8, MANAGEMENT_SCHEMA),
    (9, DRAWING_SCHEMA),
    (10, """
ALTER TABLE items ADD COLUMN number_series TEXT NOT NULL DEFAULT 'P' CHECK(number_series IN ('P','A','S'));
UPDATE items SET number_series = 'A' WHERE kind = 'assembly';
CREATE TABLE series_counters (
    series TEXT PRIMARY KEY CHECK(series IN ('P','A','S')),
    next_value INTEGER NOT NULL CHECK(next_value > 0)
);
INSERT INTO series_counters SELECT CASE item_kind WHEN 'part' THEN 'P' ELSE 'A' END, next_value FROM number_counters;
"""),
    (11, STANDARD_PARTS_SCHEMA),
    (12, SHARED_STANDARD_LIBRARY_SCHEMA),
    (13, """
CREATE TABLE dataset_material_evidence (
 dataset_id TEXT PRIMARY KEY REFERENCES datasets(id),
 payload_json TEXT NOT NULL
);
CREATE TABLE material_identities (
 item_id TEXT PRIMARY KEY REFERENCES items(id),
 identity_json TEXT NOT NULL UNIQUE,
 base_uom TEXT NOT NULL
);
CREATE TABLE revision_material_data (
 revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id),
 specification_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE material_boms (
 revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id),
 payload_json TEXT NOT NULL,
 modified_by TEXT NOT NULL REFERENCES users(id),
 modified_at TEXT NOT NULL
);
CREATE TABLE material_bom_lines (
 parent_revision_id TEXT NOT NULL REFERENCES item_revisions(id),
 component_revision_id TEXT NOT NULL REFERENCES item_revisions(id),
 position INTEGER NOT NULL CHECK(position>0),
 quantity TEXT NOT NULL,
 uom TEXT NOT NULL CHECK(uom IN ('ea','mm','cm','m','mm2','m2','g','kg')),
 allowance_percent TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(parent_revision_id,position)
);
CREATE INDEX material_bom_component_idx ON material_bom_lines(component_revision_id);
CREATE TABLE requirement_snapshots (
 id TEXT PRIMARY KEY,
 actor_id TEXT NOT NULL REFERENCES users(id),
 payload_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
"""),
    (14, """
CREATE TABLE revision_descriptions (
 revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id),
 description TEXT NOT NULL DEFAULT '',
 material_revision_id TEXT REFERENCES item_revisions(id)
);
CREATE INDEX description_material_idx ON revision_descriptions(material_revision_id);
CREATE TABLE dataset_descriptions (
 dataset_id TEXT PRIMARY KEY REFERENCES datasets(id),
 payload_json TEXT NOT NULL
);
INSERT INTO revision_descriptions(revision_id,description)
SELECT r.id,COALESCE(NULLIF(json_extract(d.specification_json,'$.description'),''),NULLIF(i.description,''),i.name)
FROM item_revisions r JOIN items i ON i.id=r.item_id LEFT JOIN revision_material_data d ON d.revision_id=r.id
WHERE i.number_series='M';
"""),
    (15, """
CREATE TABLE material_physical_links (revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id), snapshot_json TEXT NOT NULL);
CREATE TABLE part_physical_assignments (revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id), snapshot_json TEXT NOT NULL);
CREATE TABLE dataset_part_mass (dataset_id TEXT PRIMARY KEY REFERENCES datasets(id), payload_json TEXT NOT NULL);
"""),
    (16, """
CREATE TABLE revision_reference_mass (revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id), payload_json TEXT NOT NULL);
CREATE TABLE supplier_mass_feed (specification_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
CREATE TABLE supplier_mass_attempts (revision_id TEXT PRIMARY KEY REFERENCES item_revisions(id), attempted_at TEXT NOT NULL);
"""),
    (17, """
CREATE TABLE revision_operations (
    actor_id TEXT NOT NULL REFERENCES users(id),
    operation_id TEXT NOT NULL,
    item_id TEXT NOT NULL REFERENCES items(id),
    source_revision_id TEXT NOT NULL REFERENCES item_revisions(id),
    change_note TEXT NOT NULL,
    result_json TEXT NOT NULL,
    PRIMARY KEY(actor_id, operation_id)
);
"""),
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
                if version == 13:
                    connection.execute("PRAGMA foreign_keys=OFF")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    applied = connection.execute(
                        "SELECT 1 FROM schema_version WHERE version = ?", (version,)
                    ).fetchone()
                    if not applied:
                        if version == 13:
                            for table in ("items", "series_counters"):
                                original = connection.execute(
                                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                                ).fetchone()[0]
                                replacement = original.replace("('P','A','S')", "('P','A','S','M')")
                                replacement = replacement.replace("CREATE TABLE " + table, "CREATE TABLE " + table + "_new", 1)
                                connection.execute(replacement)
                                connection.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
                                connection.execute(f"DROP TABLE {table}")
                                connection.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
                            connection.execute("UPDATE projects SET name='Shared Item Library' WHERE is_standard_library=1")
                        for statement in sql.split(";"):
                            if statement.strip():
                                connection.execute(statement)
                        connection.execute(
                            "INSERT INTO schema_version(version, applied_at) VALUES (?, datetime('now'))",
                            (version,),
                        )
                    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise RuntimeError("migration foreign key validation failed")
                    connection.commit()
                    connection.execute("PRAGMA foreign_keys=ON")
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

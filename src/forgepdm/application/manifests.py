"""Immutable native-dataset dependency identities; no FreeCAD runtime code."""

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from forgepdm.domain.entities import Conflict, NotFound

PROFILE = "freecad-app-link-v1"
REFERENCE_FIELDS = (
    "object_name",
    "property_name",
    "target_revision_id",
    "target_dataset_id",
    "target_file_id",
    "target_object_name",
)


class ManifestService:
    def __init__(self, database, authorization, revisions):
        self.database = database
        self.authorization = authorization
        self.revisions = revisions

    @staticmethod
    def _dataset(connection, dataset_id, file_id=None):
        row = connection.execute(
            "SELECT d.id, d.revision_id, d.dataset_type FROM datasets d WHERE d.id=?",
            (dataset_id,),
        ).fetchone()
        if row is None:
            raise NotFound("dataset not found")
        if (
            file_id is not None
            and connection.execute(
                "SELECT 1 FROM dataset_files WHERE dataset_id=? AND file_id=?",
                (dataset_id, file_id),
            ).fetchone()
            is None
        ):
            raise Conflict("file does not belong to the specified dataset")
        return row

    @staticmethod
    def _references(references):
        if len(references) > 10000:
            raise ValueError("too many CAD references")
        result, seen = [], set()
        for reference in references:
            if set(reference) != set(REFERENCE_FIELDS):
                raise ValueError("invalid reference fields")
            entry = dict(reference)
            for field in ("object_name", "property_name", "target_object_name"):
                value = entry[field]
                if (
                    not isinstance(value, str)
                    or not value
                    or len(value) > 200
                    or any(character in value for character in "\x00/\\")
                ):
                    raise ValueError("invalid reference object/property name")
            if entry["property_name"] != "LinkedObject":
                raise ValueError("unsupported CAD reference property")
            for field in ("target_revision_id", "target_dataset_id", "target_file_id"):
                entry[field] = str(UUID(entry[field]))
            key = (entry["object_name"], entry["property_name"])
            if key in seen:
                raise ValueError("duplicate reference occurrence")
            seen.add(key)
            result.append(entry)
        return sorted(result, key=lambda value: (value["object_name"], value["property_name"]))

    def attach(self, user, dataset_id, source_file_id, references, profile=PROFILE):
        if profile != PROFILE:
            raise ValueError("unsupported reference manifest profile")
        references = self._references(references)
        with self.database.transaction() as connection:
            source = self._dataset(connection, dataset_id)
            self.authorization.require_edit_revision(user, source["revision_id"], connection)
            self.revisions.require_checkout_owner(user, source["revision_id"], connection)
            if source["dataset_type"] != "native_cad":
                raise Conflict("reference manifests require a native CAD dataset")
            self._dataset(connection, dataset_id, source_file_id)
            existing = connection.execute(
                "SELECT source_file_id, profile FROM dataset_manifests WHERE dataset_id=?",
                (dataset_id,),
            ).fetchone()
            if existing is not None:
                current = self._read(connection, user, dataset_id)
                if (
                    current["source_file_id"] != source_file_id
                    or current["profile"] != profile
                    or current["references"] != references
                ):
                    raise Conflict("dataset reference manifest is immutable; upload a new dataset")
                return current
            for reference in references:
                target = self._dataset(connection, reference["target_dataset_id"])
                self.authorization.require_read_revision(user, target["revision_id"], connection)
                if target["dataset_type"] != "native_cad":
                    raise Conflict("CAD references require a native CAD target dataset")
                self._dataset(
                    connection, reference["target_dataset_id"], reference["target_file_id"]
                )
                if target["revision_id"] != reference["target_revision_id"]:
                    raise Conflict("referenced dataset belongs to a different revision")
                # Traverse immutable dataset edges, rather than substituting an
                # item's current revision or confusing CAD dependencies with BOM.
                cycle = connection.execute(
                    "WITH RECURSIVE descendants(id) AS (SELECT ? UNION SELECT r.target_dataset_id "
                    "FROM dataset_references r JOIN descendants d ON r.dataset_id=d.id) "
                    "SELECT 1 FROM descendants WHERE id=? LIMIT 1",
                    (reference["target_dataset_id"], dataset_id),
                ).fetchone()
                if cycle is not None:
                    raise Conflict("CAD dataset reference cycle is not allowed")
            now = datetime.now(UTC).isoformat()
            connection.execute(
                "INSERT INTO dataset_manifests(dataset_id,source_file_id,profile,created_by,created_at) "
                "VALUES (?,?,?,?,?)",
                (dataset_id, source_file_id, profile, user.id, now),
            )
            for reference in references:
                connection.execute(
                    "INSERT INTO dataset_references(id,dataset_id,object_name,property_name,"
                    "target_revision_id,target_dataset_id,target_file_id,target_object_name) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (str(uuid4()), dataset_id, *(reference[field] for field in REFERENCE_FIELDS)),
                )
            connection.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at,details_json) "
                "VALUES (?,?,'dataset.manifest_attached','Dataset',?,?,?)",
                (
                    str(uuid4()),
                    user.id,
                    dataset_id,
                    now,
                    json.dumps({"reference_count": len(references)}),
                ),
            )
            return self._read(connection, user, dataset_id)

    def _read(self, connection, user, dataset_id):
        row = connection.execute(
            "SELECT dataset_id,source_file_id,profile FROM dataset_manifests WHERE dataset_id=?",
            (dataset_id,),
        ).fetchone()
        if row is None:
            raise NotFound("dataset reference manifest not found")
        references = connection.execute(
            "SELECT object_name,property_name,target_revision_id,target_dataset_id,target_file_id,"
            "target_object_name FROM dataset_references WHERE dataset_id=? ORDER BY object_name,property_name",
            (dataset_id,),
        ).fetchall()
        for reference in references:
            self.authorization.require_read_revision(
                user, reference["target_revision_id"], connection
            )
        return {**dict(row), "references": [dict(reference) for reference in references]}

    def get(self, user, dataset_id):
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            source = self._dataset(connection, dataset_id)
            self.authorization.require_read_revision(user, source["revision_id"], connection)
            return self._read(connection, user, dataset_id)

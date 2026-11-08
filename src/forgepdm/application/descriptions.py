"""Simple revision descriptions: M catalog text, P material selection, A free text."""

import hashlib
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile, is_zipfile

from forgepdm.domain.entities import Conflict


def token(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class DescriptionService:
    def __init__(self, database, authorization, revisions):
        self.database, self.authorization, self.revisions = database, authorization, revisions

    @staticmethod
    def read_in(c, revision_id):
        row = c.execute(
            "SELECT description,material_revision_id FROM revision_descriptions WHERE revision_id=?",
            (revision_id,),
        ).fetchone()
        value = dict(row) if row else {"description": "", "material_revision_id": None}
        physical = c.execute(
            "SELECT snapshot_json FROM part_physical_assignments WHERE revision_id=? UNION ALL SELECT snapshot_json FROM material_physical_links WHERE revision_id=? LIMIT 1",
            (revision_id, revision_id),
        ).fetchone()
        binding = json.loads(physical[0]) if physical else None
        hash_value = {**value, "physical_material": binding} if binding is not None else value
        return {**value, "physical_material": binding, "token": token(hash_value)}

    def read(self, user, revision_id):
        with self.database.connection() as c:
            self.authorization.require_read_revision(user, revision_id, c)
            return self.read_in(c, revision_id)

    def save(
        self,
        user,
        revision_id,
        description,
        material_revision_id,
        expected_token,
        connection=None,
        source_snapshot=False,
        native_physical=None,
    ):
        if not isinstance(description, str) or len(description) > 1000:
            raise ValueError("description must be text of at most 1000 characters")
        description = description.strip()
        with (
            nullcontext(connection) if connection is not None else self.database.transaction()
        ) as c:
            self.authorization.require_edit_revision(user, revision_id, c)
            self.revisions.require_checkout_owner(user, revision_id, c)
            parent = c.execute(
                "SELECT i.number_series FROM items i JOIN item_revisions r ON r.item_id=i.id WHERE r.id=?",
                (revision_id,),
            ).fetchone()[0]
            current = self.read_in(c, revision_id)
            requested = {"description": description, "material_revision_id": material_revision_id}
            if current["token"] != expected_token:
                raise Conflict("description changed; reload or reconcile before saving")
            binding = None
            if parent == "P":
                if material_revision_id:
                    self.authorization.require_read_revision(user, material_revision_id, c)
                    target = c.execute(
                        "SELECT i.number_series,r.lifecycle_state FROM item_revisions r JOIN items i ON i.id=r.item_id WHERE r.id=?",
                        (material_revision_id,),
                    ).fetchone()
                    if target[0] != "M" or target[1] == "obsolete":
                        raise Conflict("select a usable M material")
                    material = self.read_in(c, material_revision_id)["description"]
                    if not material:
                        raise Conflict("selected material has no description")
                    # Existing pinned text remains stable when a Working catalog entry changes.
                    if (
                        source_snapshot
                        and material_revision_id == current["material_revision_id"]
                        and description == current["description"]
                    ):
                        material = description
                    if description and description != material:
                        raise Conflict("material description changed; select it again")
                    requested["description"] = material
                    from forgepdm.application.physical_materials import PhysicalMaterialService

                    binding = PhysicalMaterialService.read_in(c, material_revision_id)[
                        "physical_material"
                    ]
                    if (
                        source_snapshot
                        and material_revision_id == current["material_revision_id"]
                        and description == current["description"]
                        and native_physical == current.get("physical_material")
                    ):
                        binding = current.get("physical_material")
                    if native_physical is not None and native_physical != binding:
                        raise Conflict("physical material link changed; select the material again")
                elif description:
                    raise ValueError("parts select M materials; clear both fields to unassign")
            elif parent in ("A", "M"):
                if material_revision_id is not None:
                    raise ValueError("assemblies and catalog materials use description text")
                if parent == "M" and not description:
                    raise ValueError("a material description is required")
            else:
                raise Conflict("description editing is available for P/A/M items")
            c.execute(
                "INSERT OR REPLACE INTO revision_descriptions VALUES (?,?,?)",
                (revision_id, requested["description"], requested["material_revision_id"]),
            )
            if parent == "P":
                c.execute(
                    "DELETE FROM part_physical_assignments WHERE revision_id=?", (revision_id,)
                )
                if binding is not None:
                    c.execute(
                        "INSERT INTO part_physical_assignments VALUES (?,?)",
                        (revision_id, json.dumps(binding, sort_keys=True)),
                    )
            if parent == "M":
                c.execute(
                    "UPDATE items SET name=?,description=? WHERE current_revision_id=?",
                    (requested["description"][:200], requested["description"], revision_id),
                )
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at) VALUES (?,?,?,'ItemRevision',?,?)",
                (
                    str(uuid4()),
                    user.id,
                    "description.updated",
                    revision_id,
                    datetime.now(UTC).isoformat(),
                ),
            )
            return self.read_in(c, revision_id)


def read_native_description(path):
    if not is_zipfile(path):
        return None
    with ZipFile(path) as archive:
        if "Document.xml" not in archive.namelist():
            return None
        info = archive.getinfo("Document.xml")
        if archive.namelist().count("Document.xml") != 1 or info.file_size > 16 * 1024**2:
            raise ValueError("invalid native document XML")
        data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("unsupported XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("invalid native XML") from error
    values = []
    for obj in root.findall("./ObjectData/Object"):
        for prop in obj.findall("./Properties/Property"):
            if prop.get("name") == "PDMDescriptionData":
                if obj.get("name") != "ForgePDM_Metadata":
                    raise ValueError("description must belong to managed metadata")
                node = prop.find("String")
                raw = node.get("value", "") if node is not None else ""
                if not raw:
                    continue
                if len(raw) > 32000:
                    raise ValueError("description metadata exceeds limits")
                value = json.loads(raw)
                expected_keys = {
                    "version",
                    "revision_id",
                    "description",
                    "material_revision_id",
                    "expected_token",
                }
                if isinstance(value, dict) and value.get("version") == 2:
                    expected_keys.add("physical_material")
                if (
                    not isinstance(value, dict)
                    or set(value) != expected_keys
                    or value["version"] not in (1, 2)
                ):
                    raise ValueError("invalid description metadata")
                if (
                    not isinstance(value["description"], str)
                    or not isinstance(value["expected_token"], str)
                    or (
                        value["material_revision_id"] is not None
                        and not isinstance(value["material_revision_id"], str)
                    )
                ):
                    raise ValueError("invalid description fields")
                values.append(value)
    if len(values) > 1:
        raise ValueError("duplicate description metadata")
    return values[0] if values else None


def persist_native_description(
    c, database, authorization, revisions, user, revision_id, dataset_id, value
):
    if value is None:
        return
    if value["revision_id"] != revision_id:
        raise Conflict("description belongs to another engineering revision")
    svc = DescriptionService(database, authorization, revisions)
    current = svc.read_in(c, revision_id)
    same = all(current[k] == value[k] for k in ("description", "material_revision_id"))
    if value["version"] == 2:
        same = same and current.get("physical_material") == value["physical_material"]
    if not same:
        svc.save(
            user,
            revision_id,
            value["description"],
            value["material_revision_id"],
            value["expected_token"],
            connection=c,
            source_snapshot=True,
            native_physical=value.get("physical_material"),
        )
    c.execute(
        "INSERT INTO dataset_descriptions VALUES (?,?)",
        (dataset_id, json.dumps(svc.read_in(c, revision_id), sort_keys=True)),
    )

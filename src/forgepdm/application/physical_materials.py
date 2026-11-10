"""Library-owned physical links and immutable native mass evidence."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from forgepdm.domain.entities import Conflict
from forgepdm.domain.physical_materials import encode, fingerprint, native_uuid, snapshot


class PhysicalMaterialService:
    def __init__(self, database, authorization, revisions):
        self.database, self.authorization, self.revisions = database, authorization, revisions

    @staticmethod
    def read_in(c, revision_id):
        row = c.execute(
            "SELECT snapshot_json FROM material_physical_links WHERE revision_id=?", (revision_id,)
        ).fetchone()
        value = json.loads(row[0]) if row else None
        return {"physical_material": value, "token": fingerprint(value)}

    def read(self, user, revision_id):
        with self.database.connection() as c:
            self.authorization.require_read_revision(user, revision_id, c)
            return self.read_in(c, revision_id)

    def save(self, user, revision_id, value, expected_token):
        value = snapshot(value)
        with self.database.transaction() as c:
            self.authorization.require_edit_revision(user, revision_id, c)
            self.revisions.require_checkout_owner(user, revision_id, c)
            series = c.execute(
                "SELECT i.number_series FROM item_revisions r JOIN items i ON i.id=r.item_id WHERE r.id=?",
                (revision_id,),
            ).fetchone()[0]
            if series != "M":
                raise Conflict("physical links belong to M catalog revisions")
            if self.read_in(c, revision_id)["token"] != expected_token:
                raise Conflict("physical link changed; reload it")
            c.execute(
                "INSERT OR REPLACE INTO material_physical_links VALUES (?,?)",
                (revision_id, encode(value)),
            )
            c.execute(
                "INSERT INTO audit_events(id,actor_id,event_type,entity_type,entity_id,occurred_at) VALUES (?,?,'material.physical_linked','ItemRevision',?,?)",
                (str(uuid4()), user.id, revision_id, datetime.now(UTC).isoformat()),
            )
        return self.read(user, revision_id)

    def mass(self, user, revision_id):
        with self.database.connection() as c:
            self.authorization.require_read_revision(user, revision_id, c)
            return self.mass_in(c, revision_id)

    @staticmethod
    def mass_in(c, revision_id):
        row = c.execute(
            "SELECT d.id AS dataset_id,f.content_hash,e.payload_json FROM datasets d JOIN dataset_files df ON df.dataset_id=d.id JOIN files f ON f.id=df.file_id LEFT JOIN dataset_part_mass e ON e.dataset_id=d.id WHERE d.revision_id=? AND d.dataset_type='native_cad' ORDER BY d.created_at DESC,d.id DESC LIMIT 1",
            (revision_id,),
        ).fetchone()
        if not row:
            return {"mass_kg": None, "reason": "No uploaded native geometry"}
        value = (
            json.loads(row["payload_json"])
            if row["payload_json"]
            else {"mass_kg": None, "reason": "No physical material mass evidence"}
        )
        current = c.execute(
            "SELECT snapshot_json FROM part_physical_assignments WHERE revision_id=?",
            (revision_id,),
        ).fetchone()
        saved_description = c.execute(
            "SELECT payload_json FROM dataset_descriptions WHERE dataset_id=?",
            (row["dataset_id"],),
        ).fetchone()
        active_description = c.execute(
            "SELECT material_revision_id FROM revision_descriptions WHERE revision_id=?",
            (revision_id,),
        ).fetchone()
        saved_material = (
            json.loads(saved_description[0]).get("material_revision_id")
            if saved_description
            else None
        )
        active_material = active_description[0] if active_description else None
        if saved_material != active_material or value.get("physical_material") != (
            json.loads(current[0]) if current else None
        ):
            return {
                "mass_kg": None,
                "reason": "Material assignment changed; upload updated CAD",
                "dataset_id": row["dataset_id"],
            }
        return {**value, "dataset_id": row["dataset_id"], "content_hash": row["content_hash"]}


def persist_mass(c, revision_id, dataset_id, evidence):
    if evidence is None:
        if c.execute(
            "SELECT 1 FROM part_physical_assignments WHERE revision_id=?", (revision_id,)
        ).fetchone():
            raise Conflict("physical assignment requires native mass evidence; update the addon")
        return
    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {"version", "revision_id", "physical_material", "objects", "mass_kg", "reason"}
        or evidence["version"] != 1
        or evidence["revision_id"] != revision_id
    ):
        raise ValueError("invalid native mass evidence")
    row = c.execute(
        "SELECT snapshot_json FROM part_physical_assignments WHERE revision_id=?", (revision_id,)
    ).fetchone()
    expected = json.loads(row[0]) if row else None
    if evidence["physical_material"] != expected:
        raise Conflict("native physical material differs from the engineering assignment")
    objects = evidence["objects"]
    if not isinstance(objects, list) or len(objects) > 100:
        raise ValueError("invalid mass objects")
    if not isinstance(evidence["reason"], str) or len(evidence["reason"]) > 1000:
        raise ValueError("invalid mass reason")
    if evidence["mass_kg"] is not None:
        if not expected or not objects or evidence["reason"]:
            raise ValueError("mass requires assigned material and valid final solids")
        total = Decimal(0)
        names = set()
        for obj in objects:
            if not isinstance(obj, dict) or set(obj) != {"name", "volume_mm3", "native_uuid"}:
                raise ValueError("invalid solid evidence")
            if (
                not isinstance(obj["name"], str)
                or not obj["name"]
                or len(obj["name"]) > 200
                or obj["name"] in names
            ):
                raise ValueError("invalid or duplicate final solid")
            names.add(obj["name"])
            if obj["native_uuid"] != native_uuid(expected):
                raise Conflict("native solid material does not match the pinned snapshot")
            try:
                volume = Decimal(str(obj["volume_mm3"]))
            except Exception as error:
                raise ValueError("invalid volume") from error
            if (
                not volume.is_finite()
                or not 0 < volume <= Decimal("1e18")
                or volume.adjusted() < -100
            ):
                raise ValueError("invalid volume")
            total += volume
        mass = total * Decimal(expected["density_kg_m3"]) / Decimal(1000000000)
        try:
            given = Decimal(str(evidence["mass_kg"]))
        except Exception as error:
            raise ValueError("invalid mass") from error
        if (
            not given.is_finite()
            or not 0 < given <= Decimal("1e18")
            or abs(mass - given) > max(Decimal("1e-12"), abs(mass) * Decimal("1e-12"))
        ):
            raise ValueError("mass differs from volume times density")
    elif not evidence["reason"]:
        raise ValueError("unavailable mass requires a reason")
    c.execute("INSERT INTO dataset_part_mass VALUES (?,?)", (dataset_id, encode(evidence)))


def read_native_mass(path):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile, is_zipfile

    if not is_zipfile(path):
        return None
    with ZipFile(path) as archive:
        if "Document.xml" not in archive.namelist():
            return None
        info = archive.getinfo("Document.xml")
        if info.file_size > 16 * 1024**2 or archive.namelist().count("Document.xml") != 1:
            raise ValueError("invalid mass XML")
        data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("unsupported XML")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("invalid native XML") from error
    values = []
    for obj in root.findall("./ObjectData/Object"):
        for prop in obj.findall("./Properties/Property"):
            if prop.get("name") == "PDMPartPhysicalData":
                if obj.get("name") != "ForgePDM_Metadata":
                    raise ValueError("invalid mass metadata owner")
                node = prop.find("String")
                raw = node.get("value", "") if node is not None else ""
                if raw:
                    if len(raw) > 64000:
                        raise ValueError("mass metadata too large")
                    values.append(json.loads(raw))
    if len(values) > 1:
        raise ValueError("duplicate mass metadata")
    if values and isinstance(values[0], dict) and values[0].get("mass_kg") is not None:
        objects = {obj.get("name"): obj for obj in root.findall("./ObjectData/Object")}
        records = values[0].get("objects", [])
        if not isinstance(records, list):
            raise ValueError("invalid solid records")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("name"), str):
                raise ValueError("invalid solid record")  # noqa: TRY004
            obj = objects.get(record.get("name"))
            prop = (
                obj.find("./Properties/Property[@name='ShapeMaterial']/PropertyMaterial")
                if obj is not None
                else None
            )
            if prop is None or prop.get("uuid") != record.get("native_uuid"):
                raise Conflict("saved native solid material differs from the mass evidence")
    return values[0] if values else None

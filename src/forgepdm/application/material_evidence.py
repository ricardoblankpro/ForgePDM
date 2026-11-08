"""Bounded native material metadata, committed with its CAD dataset."""

import json
import re
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import ZipFile, is_zipfile

from forgepdm.application.materials import MaterialService, encode
from forgepdm.domain.entities import Conflict
from forgepdm.domain.materials import decimal_quantity, finished_mass


def read_material_evidence(path):
    if not is_zipfile(path):
        return None
    with ZipFile(path) as archive:
        if "Document.xml" not in archive.namelist():
            return None
        info = archive.getinfo("Document.xml")
        if archive.namelist().count("Document.xml") != 1 or info.file_size > 16 * 1024**2:
            raise ValueError("invalid native material document")
        data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("unsupported XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("invalid native XML") from error
    found = []
    for obj in root.findall("./ObjectData/Object"):
        for prop in obj.findall("./Properties/Property"):
            if prop.get("name") == "PDMMaterialInputs":
                if obj.get("name") != "ForgePDM_Metadata":
                    raise ValueError("material evidence must belong to managed metadata")
                node = prop.find("String")
                value = node.get("value", "") if node is not None else ""
                if not value:
                    continue
                if len(value) > 256000:
                    raise ValueError("material evidence exceeds limits")
                found.append(json.loads(value))
    if len(found) > 1:
        raise ValueError("duplicate material evidence")
    if not found:
        return None
    value = found[0]
    if (
        not isinstance(value, dict)
        or not {"version", "revision_id", "expected_token", "lines"} <= value.keys()
        or value.get("version") != 1
        or set(value) - {"version", "revision_id", "expected_token", "lines", "mass_evidence"}
    ):
        raise ValueError("unsupported material evidence")
    if not isinstance(value.get("lines"), list):
        raise ValueError("material lines must be a list")  # noqa: TRY004
    if (
        not isinstance(value["expected_token"], str)
        or re.fullmatch(r"[0-9a-f]{64}", value["expected_token"]) is None
    ):
        raise ValueError("invalid material concurrency token")
    if len(value["lines"]) > 1000:
        raise ValueError("too many material inputs")
    for line in value["lines"]:
        if (
            not isinstance(line, dict)
            or not {"component_revision_id", "quantity", "uom"} <= line.keys()
        ):
            raise ValueError("invalid native material input")
        if not isinstance(line["component_revision_id"], str) or not isinstance(line["uom"], str):
            raise ValueError("invalid native material identity or unit")  # noqa: TRY004
        try:
            UUID(line["component_revision_id"])
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("invalid native material revision") from error
    return value


def persist_material_evidence(
    c, database, authorization, revisions, user, revision_id, dataset_id, evidence
):
    svc = MaterialService(database, authorization, revisions)
    current = svc._read(c, revision_id)
    if evidence is None:
        # Old clients retain their material BOM, but cannot approve geometry they did not review.
        if current["readiness"] != "unreviewed":
            current.pop("token")
            current["readiness"] = "unreviewed"
            c.execute(
                "UPDATE material_boms SET payload_json=? WHERE revision_id=?",
                (encode(current), revision_id),
            )
        return
    parent = svc._revision(c, user, revision_id, True)
    if parent["number_series"] not in ("P", "A"):
        raise Conflict("native material evidence requires P/A parents")
    if evidence["revision_id"] != revision_id:
        raise Conflict("material evidence belongs to a different revision")
    mass_records = evidence.get("mass_evidence", [])
    if not isinstance(mass_records, list) or len(mass_records) > 1000:
        raise ValueError("invalid mass evidence")
    seen = set()
    input_ids = {
        line.get("component_revision_id") for line in evidence["lines"] if isinstance(line, dict)
    }
    for record in mass_records:
        if not isinstance(record, dict) or set(record) != {
            "object_name",
            "material_revision_id",
            "volume_mm3",
            "density_kg_m3",
            "mass_kg",
        }:
            raise ValueError("invalid mass evidence record")
        name = record["object_name"]
        if not isinstance(name, str) or not name or len(name) > 200 or name in seen:
            raise ValueError("invalid or duplicate mass object")
        seen.add(name)
        target = svc._revision(c, user, record["material_revision_id"])
        if target["number_series"] != "M" or target["id"] not in input_ids:
            raise Conflict("mass evidence must reference an assigned raw material")
        spec = c.execute(
            "SELECT specification_json FROM revision_material_data WHERE revision_id=?",
            (target["id"],),
        ).fetchone()
        if not spec or decimal_quantity(json.loads(spec[0])["density_kg_m3"]) != decimal_quantity(
            record["density_kg_m3"]
        ):
            raise Conflict("mass density differs from pinned material specification")
        if finished_mass(record["volume_mm3"], record["density_kg_m3"]) != decimal_quantity(
            record["mass_kg"], allow_zero=True
        ):
            raise ValueError("mass evidence arithmetic differs")
    # Re-upload of the same saved native assignment is safe; web edits are not overwritten.
    requested = evidence["lines"]
    same = requested == current["lines"]
    if not same and evidence["expected_token"] != current["token"]:
        raise Conflict("CAD material assignments conflict with server inputs; reconcile explicitly")
    if not same:
        current = svc.replace(user, revision_id, requested, current["token"], connection=c)
    else:
        current = {**current, "readiness": "unreviewed"}
        c.execute(
            "UPDATE material_boms SET payload_json=? WHERE revision_id=?",
            (encode({k: v for k, v in current.items() if k != "token"}), revision_id),
        )
    stored = {**evidence, "canonical_lines": svc._read(c, revision_id)["lines"]}
    c.execute("INSERT INTO dataset_material_evidence VALUES (?,?)", (dataset_id, encode(stored)))

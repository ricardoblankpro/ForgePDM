"""Catalog matching and source-pinned embedded component evidence."""

import json
from uuid import UUID
from xml.etree import ElementTree as ET
from zipfile import ZipFile, is_zipfile

from forgepdm.domain.entities import Conflict, Forbidden, NotFound
from forgepdm.domain.standard_parts import PARAMETERS, encode, geometry


def read_occurrences(path):
    if not is_zipfile(path):
        return []
    with ZipFile(path) as archive:
        if "Document.xml" not in archive.namelist():
            return []
        if archive.namelist().count("Document.xml") != 1:
            raise ValueError("Duplicate native document XML")
        info = archive.getinfo("Document.xml")
        if info.file_size > 16 * 1024**2:
            raise ValueError("Native document XML exceeds limits")
        data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unsupported XML declarations")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("Invalid native document XML") from error
    result, ids = [], set()
    for obj in root.findall("./ObjectData/Object"):
        props = {p.get("name"): p for p in obj.findall("./Properties/Property")}
        assoc = props.get("PDMStandardAssociation")
        if assoc is None:
            continue
        node = assoc.find("String")
        if node is None or len(node.get("value", "")) > 16000:
            raise ValueError("Invalid standard association")
        record = json.loads(node.get("value", ""))
        if (
            not isinstance(record, dict)
            or set(record) - {"generator_version"}
            != {"version", "occurrence_id", "revision_id", "geometry"}
            or record["version"] != 1
        ):
            raise ValueError("Unsupported standard association version")
        proxy = props.get("Proxy")
        python = proxy.find("Python") if proxy is not None else None
        if (
            python is None
            or python.get("module") != "FastenersCmd"
            or not python.get("class", "").startswith("FS")
        ):
            raise ValueError("Standard association is not on a supported Fasteners object")
        captured = {}
        for name in PARAMETERS:
            prop = props.get(name)
            if prop is None:
                continue
            scalar = next(iter(prop), None)
            if prop.get("type") == "App::PropertyEnumeration":
                values = prop.findall("./CustomEnumList/Enum")
                if scalar is None or scalar.get("value") is None:
                    raise ValueError("Missing fastener enumeration")
                index = int(scalar.get("value"))
                if index < 0 or index >= len(values):
                    raise ValueError("Invalid fastener enumeration")
                captured[name] = values[index].get("value")
            elif scalar is not None:
                captured[name] = (
                    (scalar.get("value") in ("1", "true"))
                    if prop.get("type") == "App::PropertyBool"
                    else scalar.get("value")
                )
        captured = geometry(captured)
        if captured != geometry(record["geometry"]):
            raise Conflict("Fastener specification changed; reassociate before upload")
        if any(not isinstance(record[field], str) for field in ("occurrence_id", "revision_id")):
            raise ValueError("Standard occurrence identities must be UUID strings")
        if (
            not isinstance(record.get("generator_version", "unknown"), str)
            or len(record.get("generator_version", "unknown")) > 100
        ):
            raise ValueError("Invalid Fasteners generator version")
        identifier = str(UUID(record["occurrence_id"]))
        if identifier in ids:
            raise ValueError("Duplicate standard occurrence UUID")
        ids.add(identifier)
        result.append(
            dict(
                object_name=obj.get("name"),
                occurrence_id=identifier,
                revision_id=str(UUID(record["revision_id"])),
                geometry=captured,
            )
        )
    if len(result) > 10000:
        raise ValueError("Too many standard occurrences")
    return result


def persist_occurrences(connection, authorization, user, dataset_id, occurrences):
    for entry in occurrences:
        authorization.require_read_revision(user, entry["revision_id"], connection)
        target = connection.execute(
            "SELECT s.geometry_json,r.lifecycle_state FROM standard_specifications s "
            "JOIN item_revisions r ON r.item_id=s.item_id WHERE r.id=?",
            (entry["revision_id"],),
        ).fetchone()
        if target is None or target["geometry_json"] != encode(entry["geometry"]):
            raise Conflict(
                "Fastener association does not match a registered standard specification"
            )
        if target["lifecycle_state"] == "obsolete":
            raise Conflict("Obsolete standard revision cannot be associated")
        connection.execute(
            "INSERT INTO dataset_standard_occurrences VALUES (?,?,?,?,?)",
            (
                dataset_id,
                entry["object_name"],
                entry["occurrence_id"],
                entry["revision_id"],
                encode(entry["geometry"]),
            ),
        )


class StandardPartsService:
    def __init__(self, database, authorization):
        self.database, self.authorization = database, authorization

    def match(self, user, requested):
        requested = geometry(requested)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT i.id,i.number,i.name,i.current_revision_id,r.label AS revision_label,"
                "r.lifecycle_state,s.specification_json FROM standard_specifications s "
                "JOIN items i ON i.id=s.item_id JOIN item_revisions r ON r.id=i.current_revision_id "
                "WHERE s.geometry_json=? ORDER BY i.number",
                (encode(requested),),
            ).fetchall()
            result = []
            for row in rows:
                try:
                    self.authorization.require_read_revision(
                        user, row["current_revision_id"], connection
                    )
                except (Forbidden, NotFound):
                    continue
                if row["lifecycle_state"] == "obsolete":
                    continue
                item = dict(row)
                item["specification"] = json.loads(item.pop("specification_json"))
                result.append(item)
        return {"items": result}

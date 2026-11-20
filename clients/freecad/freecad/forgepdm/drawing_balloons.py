"""Explicit native balloon links to frozen Direct BOM entries; no CAD inference."""

import json

from . import drawing_bom

EXPRESSION = "PDMBOMPosition"
PROPERTIES = {
    "PDMBOMTable": "App::PropertyLink",
    "PDMBOMBinding": "App::PropertyString",
    "PDMBOMPosition": "App::PropertyString",
    "PDMBOMStatus": "App::PropertyString",
}


def entries(data):
    report = data["report"]
    if report.get("view", "direct") != "direct":
        raise ValueError("Linked balloons currently require a Direct BOM table")
    if not report.get("revision_id"):
        raise ValueError("The table has no assembly revision identity; update Drawing BOM first")
    lines = report["lines"]
    keys = [drawing_bom.row_key(line) for line in lines]
    positions = [line["position"] for line in lines]
    if (
        len(set(keys)) != len(keys)
        or len(set(positions)) != len(positions)
        or any(type(p) is not int or p < 1 for p in positions)
    ):
        raise ValueError("The frozen table has ambiguous BOM entries or invalid positions")
    return drawing_bom.ordered_lines(report, drawing_bom.layout(data["layout"]))


def identity(data, line):
    """Duplicate occurrence sets must stay unchanged; recreated database IDs are irrelevant."""
    revision = line["component_revision_id"]
    return {
        "format": 1,
        "revision_id": data["report"]["revision_id"],
        "component_revision_id": revision,
        "row_key": drawing_bom.row_key(line),
        "position": line["position"],
        "occurrences": sorted(
            drawing_bom.row_key(row)
            for row in data["report"]["lines"]
            if row["component_revision_id"] == revision
        ),
    }


def resolve(binding, data):
    if not isinstance(binding, dict) or binding.get("format") not in (1, 2, 3):
        raise ValueError("Unsupported balloon binding; explicitly relink the balloon")
    saved = {k: v for k, v in binding.items() if k != "attachment"}
    saved["format"] = 1
    candidates = [
        line
        for line in entries(data)
        if drawing_bom.row_key(line) == binding.get("row_key")
        and line["component_revision_id"] == binding.get("component_revision_id")
        and identity(data, line) == saved
    ]
    if len(candidates) != 1:
        raise ValueError("BOM entry removed, renumbered, replaced or ambiguous; relink the balloon")
    return candidates[0]


def linked(document, table):
    return [obj for obj in document.Objects if getattr(obj, "PDMBOMTable", None) is table]


def text_expression(balloon):
    return dict(balloon.ExpressionEngine).get("Text")


def review_state(balloon):
    return (
        balloon.Text,
        tuple(balloon.ExpressionEngine),
        getattr(balloon, "SourceView", None),
        *(getattr(balloon, name, None) for name in PROPERTIES),
    )


def check_properties(balloon):
    for name, kind in PROPERTIES.items():
        if name in balloon.PropertiesList and balloon.getTypeIdOfProperty(name) != kind:
            raise ValueError("Incompatible balloon property: " + name)


def validate_target(document, page, balloon, table):
    if (
        balloon.Document is not document
        or table.Document is not document
        or page.Document is not document
        or not balloon.isDerivedFrom("TechDraw::DrawViewBalloon")
        or balloon not in page.Views
        or table not in page.Views
        or not source_on_page(page, balloon.SourceView)
    ):
        raise ValueError("Choose a native balloon and BOM table on the same page and document")
    check_properties(balloon)


def source_on_page(page, source):
    """Projection items belong through their group's Views, not directly to the page."""
    if source is None:
        return False
    if source in page.Views:
        return True
    return (
        getattr(source, "TypeId", "") == "TechDraw::DrawProjGroupItem"
        and source.Document is page.Document
        and any(
            getattr(view, "TypeId", "") == "TechDraw::DrawProjGroup"
            and view.Document is page.Document
            and any(
                child.Document is source.Document and child.Name == source.Name
                for child in view.Views
            )
            for view in page.Views
        )
    )


def bind(document, page, balloon, table, row_key, attachment=None):
    validate_target(document, page, balloon, table)
    data = drawing_bom.read_table(table)
    candidates = [row for row in entries(data) if drawing_bom.row_key(row) == row_key]
    if len(candidates) != 1:
        raise ValueError("The chosen frozen BOM entry changed; reopen Link BOM Balloon")
    binding = identity(data, candidates[0])
    if attachment is not None:
        from .geometry_fingerprint import PROFILE

        profile = attachment["geometry"].get("fingerprint")
        if profile not in (None, PROFILE):
            raise ValueError("Unsupported balloon geometry fingerprint")
        binding.update(format=3 if profile == PROFILE else 2, attachment=attachment)
    document.openTransaction("ForgePDM Link BOM Balloon")
    try:
        for name, kind in PROPERTIES.items():
            if name not in balloon.PropertiesList:
                balloon.addProperty(kind, name, "ForgePDM")
        balloon.PDMBOMTable = table
        balloon.PDMBOMBinding = json.dumps(binding, sort_keys=True)
        balloon.PDMBOMPosition = str(binding["position"])
        balloon.PDMBOMStatus = "Linked"
        balloon.setExpression("Text", EXPRESSION)
        for name in PROPERTIES:
            balloon.setEditorMode(name, 1)
        # Older addons must refuse table edits that would leave balloons stale.
        data["format"] = (
            7
            if binding["format"] == 3 or data["format"] == 7
            else 6
            if attachment is not None or data["format"] == 6
            else 5
        )
        table.PDMTableData = json.dumps(data, sort_keys=True)
        document.recompute()
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        raise


def refresh(document, table, data):
    """Called inside the table's transaction. Unresolved links require explicit adoption."""
    for balloon in linked(document, table):
        check_properties(balloon)
        try:
            if balloon.PDMBOMStatus != "Linked" or text_expression(balloon) != EXPRESSION:
                raise ValueError("Balloon link needs explicit relinking")
            binding = json.loads(balloon.PDMBOMBinding)
            validate_attachment(balloon, binding)
            line = resolve(binding, data)
            balloon.PDMBOMPosition = str(line["position"])
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            balloon.setExpression("Text", EXPRESSION)
            balloon.PDMBOMPosition = "?"
            balloon.PDMBOMStatus = "Unresolved: " + str(error)


def update_issues(table, report, definition):
    if table is None or not hasattr(table, "Document"):
        return []
    result = []
    for balloon in linked(table.Document, table):
        try:
            if balloon.PDMBOMStatus != "Linked" or text_expression(balloon) != EXPRESSION:
                raise ValueError("Balloon link needs explicit relinking")
            resolve(json.loads(balloon.PDMBOMBinding), {"report": report, "layout": definition})
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            result.append(balloon.Label + ": " + str(error))
    return result


def diagnostics(page):
    """Return object identities and reasons without changing frozen links or styles."""
    result = []
    for balloon in page.Views:
        if not hasattr(balloon, "PDMBOMBinding"):
            continue
        try:
            table = balloon.PDMBOMTable
            validate_target(page.Document, page, balloon, table)
            data = drawing_bom.read_table(table)
            binding = json.loads(balloon.PDMBOMBinding)
            validate_attachment(balloon, binding)
            line = resolve(binding, data)
            if (
                data["format"] not in (5, 6, 7)
                or (binding.get("format") == 3 and data["format"] != 7)
                or balloon.PDMBOMStatus != "Linked"
                or text_expression(balloon) != EXPRESSION
                or balloon.PDMBOMPosition != str(line["position"])
                or balloon.Text != str(line["position"])
            ):
                raise ValueError("Balloon text or link changed; explicitly relink it")
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            result.append({"balloon": balloon, "reason": str(error)})
    return result


def issues(page):
    """Validate frozen links before ForgePDM PDF export; never change the snapshot."""
    return [entry["balloon"].Label + ": " + entry["reason"] for entry in diagnostics(page)]


def validate_attachment(balloon, binding):
    if binding.get("format") in (2, 3):
        from . import balloon_geometry
        from .geometry_fingerprint import PROFILE

        attachment = binding["attachment"]
        saved = attachment["geometry"]
        if binding["format"] == 3 and saved.get("fingerprint") != PROFILE:
            raise ValueError(
                "Unsupported balloon geometry fingerprint; explicitly relink the balloon"
            )
        current = (
            balloon_geometry.evidence(balloon, legacy=True)
            if binding["format"] == 2
            else balloon_geometry.evidence(balloon)
        )
        if saved != current:
            reason = "Arrow or source geometry changed"
            for key, message in (
                ("view", "Source view changed"),
                ("origin", "Arrow position changed"),
                ("scale", "View scale changed"),
                ("direction", "View direction changed"),
                ("x_direction", "View orientation changed"),
                ("rotation", "View rotation changed"),
                ("perspective", "View perspective changed"),
                ("components", "Component geometry changed"),
            ):
                if saved.get(key) != current.get(key):
                    reason = message
                    break
            raise ValueError(reason + "; retry Link BOM Balloon")
        hits = balloon_geometry.pick(balloon)
        if not any(
            obj.Name == attachment["component"] and rid == binding["component_revision_id"]
            for obj, rid in hits
        ):
            raise ValueError("The arrow no longer touches its saved component")


def plan_legacy_upgrade(page, balloon):
    """Plan an explicitly authorized rebaseline to the same verified target.

    This is never used during restore or PDF validation. An old one-way hash
    cannot prove geometric equivalence; the caller must authorize a rebaseline
    under the normal working-copy, permission and checkout guards.
    """
    from . import balloon_geometry as geometry

    table = balloon.PDMBOMTable
    validate_target(page.Document, page, balloon, table)
    data = drawing_bom.read_table(table)
    binding = json.loads(balloon.PDMBOMBinding)
    resolve(binding, data)
    if (
        binding.get("format") != 2
        or balloon.PDMBOMStatus != "Linked"
        or text_expression(balloon) != EXPRESSION
        or balloon.Text != str(binding["position"])
        or balloon.PDMBOMPosition != str(binding["position"])
    ):
        raise ValueError("Review this balloon explicitly with Link BOM Balloon")
    saved = binding["attachment"]["geometry"]
    current = geometry.evidence(balloon)
    if {k: v for k, v in saved.items() if k != "components"} != {
        k: v for k, v in current.items() if k not in ("components", "fingerprint")
    }:
        raise ValueError("Arrow or view changed; review Link BOM Balloon")
    if [row[:2] for row in saved["components"]] != [row[:2] for row in current["components"]]:
        raise ValueError("Component occurrences or revisions changed; review Link BOM Balloon")
    component = binding["attachment"]["component"]
    if not any(
        obj.Name == component and rid == binding["component_revision_id"]
        for obj, rid in geometry.pick(balloon)
    ):
        raise ValueError("The arrow no longer touches its saved component")
    return dict(binding, format=3, attachment=dict(component=component, geometry=current))


def unresolved(balloon, reason):
    document = balloon.Document
    document.openTransaction("ForgePDM Unresolved Balloon")
    try:
        check_properties(balloon)
        for name, kind in PROPERTIES.items():
            if name not in balloon.PropertiesList:
                balloon.addProperty(kind, name, "ForgePDM")
        if not balloon.PDMBOMBinding:
            balloon.PDMBOMBinding = '{"format": 2}'
        balloon.PDMBOMPosition = "?"
        balloon.PDMBOMStatus = "Unresolved: " + reason
        balloon.setExpression("Text", EXPRESSION)
        document.recompute()
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        raise

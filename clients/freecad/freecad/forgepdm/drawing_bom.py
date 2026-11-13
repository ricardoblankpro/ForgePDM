"""Frozen drawing reports, safe column layouts and self-contained SVG tables."""

import copy
import json
import math
from decimal import Decimal, localcontext
from xml.sax.saxutils import escape

FIELDS = {
    "position": "Pos.",
    "item_number": "Item number",
    "item_name": "Name / designation",
    "revision_label": "Revision",
    "quantity": "Qty.",
    "description": "Description / Material",
    "material": "Material",
    "lifecycle_state": "Lifecycle",
    "item_kind": "Type",
    "unit_mass": "Unit mass",
    "total_mass": "Total mass",
    "custom": "Custom text",
}
DEFAULT = {
    "columns": [
        {"field": field, "heading": FIELDS[field], "width": width, "align": "left", "unit": "kg"}
        for field, width in [
            ("position", 12),
            ("item_number", 28),
            ("revision_label", 16),
            ("quantity", 14),
            ("description", 105),
        ]
    ],
    "font": 3.0,
    "precision": 3,
}


def layout(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid table layout")
    value = copy.deepcopy(value)
    columns = value.get("columns")
    if not isinstance(columns, list) or not 1 <= len(columns) <= 12:
        raise ValueError("Choose 1 to 12 table columns")
    for index, column in enumerate(columns):
        if not isinstance(column, dict):
            raise ValueError("Invalid column definition")
        if column.get("field") not in FIELDS or column.get("align") not in (
            "left",
            "center",
            "right",
        ):
            raise ValueError("Unsupported column field or alignment")
        if not isinstance(column.get("heading"), str) or len(column["heading"]) > 100:
            raise ValueError("Column headings must contain at most 100 characters")
        width = float(column["width"])
        if not math.isfinite(width) or not 5 <= width <= 250:
            raise ValueError("Column widths must be between 5 and 250 mm")
        column["width"] = width
        if column.get("unit", "kg") not in ("kg", "g"):
            raise ValueError("Mass units must be kg or g")
        column.setdefault("unit", "kg")
        column.setdefault("key", "column-" + str(index))
        if not isinstance(column["key"], str) or len(column["key"]) > 100:
            raise ValueError("Invalid saved column identity")
    if len({column["key"] for column in columns}) != len(columns):
        raise ValueError("Column identities must be unique")
    font = float(value["font"])
    if not math.isfinite(font) or not 1.5 <= font <= 10 or not 0 <= int(value["precision"]) <= 6:
        raise ValueError("Font must be 1.5–10 mm and precision 0–6")
    value["font"], value["precision"] = font, int(value["precision"])
    return value


def row_key(line):
    return line["component_revision_id"] + ":" + str(line["position"])


def cell(line, column, notes, precision):
    if column["field"] == "custom":
        return str(notes.get(row_key(line), {}).get(column["key"], ""))
    value = line.get(column["field"])
    if (
        column["field"] == "description"
        and not value
        and line.get("item_number", "").startswith("S")
    ):
        value = line.get("item_name", "")
    if column["field"] in ("unit_mass", "total_mass"):
        if value is None:
            return "—"
        with localcontext() as context:
            context.prec = 4096
            amount = Decimal(value) * (1000 if column["unit"] == "g" else 1)
            threshold = Decimal(1).scaleb(-precision)
            text = (
                "<" + format(threshold, "f")
                if 0 < amount < threshold
                else format(amount, f".{precision}f").rstrip("0").rstrip(".")
                if precision
                else format(amount, ".0f")
            )
        source = line.get("mass_source", {})
        return ("~" if source.get("status") == "cad_estimate" else "") + text
    return "" if value is None else str(value)


def measure_text(font):
    from .ui import QtGui

    face = QtGui.QFont("DejaVu Sans")
    face.setPixelSize(1000)
    metrics = QtGui.QFontMetricsF(face)
    return lambda text: metrics.horizontalAdvance(text) * font / 1000


def render(report, definition, notes, measure=None):
    definition = layout(definition)
    if not isinstance(notes, dict) or any(
        not isinstance(values, dict)
        or any(not isinstance(text, str) or len(text) > 1000 for text in values.values())
        for values in notes.values()
    ):
        raise ValueError("Custom text must contain at most 1000 characters per cell")
    font = definition["font"]
    columns = definition["columns"]
    measure = measure or (lambda text: len(text) * font * 0.65)

    def wrap(text, width):
        result = []
        for paragraph in str(text).split("\n"):
            line = ""
            for word in paragraph.split():
                if line and measure(line + " " + word) > width - 2:
                    result.append(line)
                    line = ""
                if measure(word) > width - 2:
                    for char in word:
                        if line and measure(line + char) > width - 2:
                            result.append(line)
                            line = ""
                        line += char
                else:
                    line += (" " if line else "") + word
            result.append(line)
        return result

    rows = [
        [
            column["heading"]
            + (
                " (" + column["unit"] + ")"
                if column["field"] in ("unit_mass", "total_mass")
                else ""
            )
            for column in columns
        ]
    ]
    rows += [
        [cell(line, column, notes, definition["precision"]) for column in columns]
        for line in report["lines"]
    ]
    wrapped = [[wrap(text, column["width"]) for text, column in zip(row, columns)] for row in rows]
    heights = [max(len(value) for value in row) * font * 1.25 + 2 for row in wrapped]
    width = sum(column["width"] for column in columns)
    width = sum(column["width"] for column in columns)
    title = "ENGINEERING BOM — {} Rev {}".format(report["item_number"], report["revision_label"])
    title_lines = wrap(title, width)
    footer_lines = wrap("Stored direct EBOM · — unavailable · ~ CAD estimate", width)
    title_height = len(title_lines) * font * 1.25 + 2
    height = sum(heights) + title_height + len(footer_lines) * font + 2
    if width > 1000 or height > 2000:
        raise ValueError("Table is too large; reduce columns/font or use fewer direct lines")
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">',
        '<g font-family="DejaVu Sans" fill="black" stroke="none">',
    ]
    for i, text in enumerate(title_lines):
        svg.append(
            f'<text x="1" y="{font + 1 + i * font * 1.25}" font-size="{font}">{escape(text)}</text>'
        )
    y = title_height
    for values, row_height in zip(wrapped, heights):
        x = 0
        for lines, column in zip(values, columns):
            w = column["width"]
            svg.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{row_height}" fill="none" stroke="black" stroke-width="0.25"/>'
            )
            anchor = {"left": "start", "center": "middle", "right": "end"}[column["align"]]
            tx = x + 1 if anchor == "start" else x + w - 1 if anchor == "end" else x + w / 2
            for i, text in enumerate(lines):
                svg.append(
                    f'<text x="{tx}" y="{y + 1 + font + i * font * 1.25}" font-size="{font}" text-anchor="{anchor}">{escape(text)}</text>'
                )
            x += w
        y += row_height
    for i, text in enumerate(footer_lines):
        svg.append(
            f'<text x="1" y="{y + font + 1 + i * font}" font-size="{font * 0.8}">{escape(text)}</text>'
        )
    svg.append("</g></svg>")
    result = "".join(svg)
    from .techdraw import validate_svg

    def invalid(message):
        raise ValueError("Table text/layout cannot be rendered: " + message)

    validate_svg(result.encode("utf-8"), invalid)
    return result, width, height


def read_table(obj):
    if not hasattr(obj, "PDMTableData"):
        return None
    data = json.loads(obj.PDMTableData)
    if data.get("format") != 1:
        raise ValueError("Unsupported saved drawing BOM format")
    layout(data["layout"])
    if not isinstance(data.get("report"), dict) or not isinstance(data.get("notes"), dict):
        raise ValueError("Invalid saved table data; original contents preserved")
    for values in data["notes"].values():
        if not isinstance(values, dict) or any(
            not isinstance(text, str) or len(text) > 1000 for text in values.values()
        ):
            raise ValueError("Invalid custom text in saved table")
    return data


def placement(page, target, report, definition, notes, x, y):
    svg, width, height = render(report, definition, notes, measure_text(float(definition["font"])))
    if target is not None and target not in page.Views:
        raise ValueError("The selected table no longer belongs to this page")
    scale = float(target.Scale) if target else 1.0
    angle = math.radians(float(target.Rotation)) if target else 0.0
    w = scale * (abs(math.cos(angle)) * width + abs(math.sin(angle)) * height)
    h = scale * (abs(math.sin(angle)) * width + abs(math.cos(angle)) * height)
    pw, ph = float(page.Template.Width), float(page.Template.Height)
    if (
        not all(math.isfinite(v) for v in (x, y, scale, angle))
        or scale <= 0
        or x - w / 2 < 0
        or x + w / 2 > pw
        or y - h / 2 < 0
        or y + h / 2 > ph
    ):
        raise ValueError(
            f"Table ({w:.1f} × {h:.1f} mm) does not fit the page at this position; adjust widths, font or X/Y"
        )
    return svg


def apply(document, page, target, report, definition, notes, x, y):
    svg = placement(page, target, report, definition, notes, x, y)
    data = {"format": 1, "report": report, "layout": layout(definition), "notes": notes}
    document.openTransaction("ForgePDM Drawing BOM")
    try:
        if target is None:
            target = document.addObject("TechDraw::DrawViewSymbol", "ForgePDMBOM")
            target.Label = "Engineering BOM"
            target.addProperty("App::PropertyString", "PDMTableData", "ForgePDM")
            page.addView(target)
        target.Symbol = svg
        target.PDMTableData = json.dumps(data, sort_keys=True)
        target.setEditorMode("PDMTableData", 1)
        target.X, target.Y = x, y
        document.recompute()
        document.commitTransaction()
    except BaseException:
        document.abortTransaction()
        raise
    return target

"""Only proven embedded TechDraw templates may bypass external-file rejection."""

from zipfile import ZipFile

import pytest

from freecad.forgepdm import fcstd, techdraw


SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm"><text>Title</text></svg>'
)


def drawing(
    tmp_path,
    svg=SVG,
    *,
    object_type="TechDraw::DrawSVGTemplate",
    member="sheet.svg",
    included="sheet.svg",
    page_result=True,
    extra="",
):
    result = (
        (
            '<Property name="PageResult" type="App::PropertyFileIncluded">'
            '<FileIncluded file="{}"/></Property>'.format(included)
        )
        if page_result
        else ""
    )
    xml = (
        '<Document><Objects><Object name="Template" type="{}"/></Objects><ObjectData>'
        '<Object name="Template"><Properties><Property name="Template" type="App::PropertyFile">'
        '<String value="/missing/on/another/machine.svg"/></Property>{}{}'
        "</Properties></Object></ObjectData></Document>"
    ).format(object_type, result, extra)
    path = tmp_path / "drawing.FCStd"
    with ZipFile(path, "w") as archive:
        archive.writestr("Document.xml", xml)
        if member:
            archive.writestr(member, svg)
        archive.writestr("Shape.brp", b"untouched shape data")
    return path


def test_embedded_template_does_not_require_original_path_and_is_preserved_on_rewrite(tmp_path):
    source = drawing(tmp_path)
    fcstd.validate(source, [])
    destination = tmp_path / "rewritten.FCStd"
    fcstd.rewrite(source, destination, [], {})
    fcstd.validate(destination, [])
    with ZipFile(destination) as archive:
        assert archive.read("sheet.svg") == SVG
        assert archive.read("Shape.brp") == b"untouched shape data"
        assert b"/missing/on/another/machine.svg" in archive.read("Document.xml")


@pytest.mark.parametrize(
    "fault",
    [
        "missing_result",
        "missing_member",
        "empty",
        "traversal",
        "absolute",
        "wrong_root",
        "malformed",
        "dtd",
        "utf16",
    ],
)
def test_invalid_embedded_templates_are_rejected(tmp_path, fault):
    kwargs = {}
    if fault == "missing_result":
        kwargs["page_result"] = False
    elif fault == "missing_member":
        kwargs["member"] = None
    elif fault == "traversal":
        kwargs["included"] = "../sheet.svg"
    elif fault == "absolute":
        kwargs["included"] = "/sheet.svg"
    else:
        kwargs["svg"] = {
            "empty": b"",
            "wrong_root": b"<html/>",
            "malformed": b"<svg>",
            "dtd": b'<!DOCTYPE svg [<!ENTITY x "bad">]><svg>&x;</svg>',
            "utf16": "<svg/>".encode("utf-16"),
        }[fault]
    with pytest.raises(fcstd.CADIntegrityError, match="TechDraw template"):
        fcstd.inspect(drawing(tmp_path, **kwargs))


@pytest.mark.parametrize(
    "body",
    [
        '<image href="file:///tmp/company-logo.png"/>',
        '<image xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://example.test/logo.png"/>',
        '<use href="other.svg#symbol"/>',
        '<style>@import "external.css";</style>',
        '<rect style="fill:url(https://example.test/color)"/>',
        '<rect style="fill:u\\72l(external.svg)"/>',
        "<script>bad()</script>",
        '<rect onclick="bad()"/>',
        "<foreignObject/>",
        '<image href="data:image/svg+xml;base64,PHN2Zy8+"/>',
        '<image href="data:image/png;base64,invalid!"/>',
    ],
)
def test_templates_with_external_or_active_content_remain_unsupported(tmp_path, body):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg">' + body + "</svg>").encode()
    with pytest.raises(fcstd.CADIntegrityError, match="TechDraw template"):
        fcstd.inspect(drawing(tmp_path, svg=svg))


def test_internal_svg_references_and_embedded_raster_data_are_allowed(tmp_path):
    svg = b"""<svg xmlns="http://www.w3.org/2000/svg"><defs><g id="mark"/></defs>
    <use href="#mark"/><rect style="fill:url('#mark')"/>
    <image href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ZkAAAAASUVORK5CYII="/>
    </svg>"""
    fcstd.validate(drawing(tmp_path, svg=svg), [])


def test_wrapped_base64_image_data_is_not_mistaken_for_external_resource(tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,QQ==\n  "/></svg>'
    fcstd.validate(drawing(tmp_path, svg=svg), [])


def test_other_objects_and_extra_external_properties_are_not_exempted(tmp_path):
    with pytest.raises(fcstd.CADIntegrityError, match="External file assets"):
        fcstd.inspect(drawing(tmp_path, object_type="Part::Feature"))
    extra = '<Property name="OtherAsset" type="App::PropertyFile"><String value="/external.png"/></Property>'
    with pytest.raises(fcstd.CADIntegrityError, match="OtherAsset"):
        fcstd.inspect(drawing(tmp_path, extra=extra))


def test_oversize_template_is_rejected_before_read(tmp_path, monkeypatch):
    monkeypatch.setattr(techdraw, "MAX_TEMPLATE_BYTES", 8)
    with pytest.raises(fcstd.CADIntegrityError, match="too large"):
        fcstd.inspect(drawing(tmp_path))

"""Installed-client localization and frozen TechDraw acceptance on serve.py fixtures.

run(App, Gui, CASE_DIR) uses disposable credentials only and preserves existing docs.
"""


def run(App, Gui, directory):
    import hashlib
    import json
    from pathlib import Path

    from freecad.forgepdm import __version__, api, cad, drawing_bom, session

    case = Path(directory)
    config = json.loads((case / "connection.json").read_text())
    assert "forgepdm-localization" in str(case) and config["url"].startswith("http://127.0.0.1:")
    original_session = session.Session.client, session.Session.user
    active = App.ActiveDocument.Name if App.ActiveDocument else None

    def documents():
        return {
            d.Name: (
                d.FileName,
                cad.document_modified(d),
                hashlib.sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
            )
            for d in App.listDocuments().values()
        }

    before = documents()
    checks = []
    document = None
    client = api.ForgePDMClient(config["url"])
    try:
        client.login("web-admin", config["password"])
        item = client._json_request(
            "POST",
            "/api/v1/items",
            {
                "kind": "assembly",
                "name": "Conjunto nativo",
                "description": "",
                "source_language": "pt-BR",
                "project_id": config["projects"]["design"],
            },
        )
        path = "/api/v1/items/" + item["id"] + "/localized-texts"
        source = next(r for r in client._json_request("GET", path) if r["field"] == "designation")
        original = client._json_request(
            "GET", "/api/v1/revisions/" + item["current_revision_id"] + "/description"
        )
        source = client._json_request(
            "POST",
            "/api/v1/localized-texts/" + source["id"],
            {
                "operation": "draft",
                "expected_token": source["token"],
                "language": "en",
                "text": "Native assembly",
            },
        )
        client._json_request(
            "POST",
            "/api/v1/localized-texts/" + source["id"],
            {
                "operation": "approve",
                "expected_token": source["token"],
                "translation_id": source["translations"][-1]["id"],
            },
        )
        client.description_language = "en"
        results = client.search_items("Native assembly")
        assert results["items"][0]["localized_name"]["text"] == "Native assembly"
        checks.append(
            "Installed HTTP client creates Portuguese source and approves searchable English translation"
        )
        assert (
            client._json_request(
                "GET", "/api/v1/revisions/" + item["current_revision_id"] + "/description"
            )
            == original
        )
        checks.append("Native original-description token remains unchanged")
        client.description_language = "pt-BR"
        bundle = client.bom_report(config["root"]["revision"])
        report = drawing_bom.report_for_view(bundle, "direct")
        assert report["language"] == "pt-BR"
        assert all("localization" in row for row in report["lines"])
        checks.append(
            "Installed BOM client requests selected language and receives exact-pin provenance"
        )
        document = App.newDocument("ForgePDMLocalizationQA")
        page = document.addObject("TechDraw::DrawPage", "Page")
        template = document.addObject("TechDraw::DrawSVGTemplate", "Template")
        template_path = case / "localization-template.svg"
        template_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"><rect x="5" y="5" width="287" height="200" fill="none" stroke="black"/></svg>'
        )
        template.Template = str(template_path)
        page.Template = template
        document.recompute()
        table = drawing_bom.apply(document, page, None, report, drawing_bom.DEFAULT, {}, 148, 110)
        frozen = table.PDMTableData
        saved = drawing_bom.read_table(table)
        assert saved["format"] == 3 and saved["report"]["language"] == "pt-BR"
        checks.append("Real TechDraw table embeds format-3 language and review provenance")
        native = case / "localization-frozen.FCStd"
        document.recompute()
        document.saveAs(str(native))
        name = document.Name
        App.closeDocument(name)
        document = App.openDocument(str(native))
        table = document.getObject("ForgePDMBOM")
        client.description_language = "en"
        document.recompute()
        assert table.PDMTableData == frozen
        checks.append("Saved FCStd table survives reopen and language change without text refresh")
    finally:
        if document:
            App.closeDocument(document.Name)
        if active and active in App.listDocuments():
            App.setActiveDocument(active)
        client.logout()
    assert documents() == before
    assert (
        session.Session.client is original_session[0]
        and session.Session.user is original_session[1]
    )
    checks.append(
        "Existing documents, file hashes, dirty states, active document and authenticated session preserved"
    )
    result = {
        "addon": __version__,
        "freecad": ".".join(App.Version()[:3]),
        "scope": "Installed native HTTP client and actual TechDraw with disposable backend/CAD fixture",
        "checks": checks,
        "preexisting_documents": len(before),
    }
    (case / "localization-native-report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result

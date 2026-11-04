"""Live explicit PDF publication, loss recovery and browser-fixture preparation."""


def run(App, Gui, case, worker, drive, check, client, part, assembly, selected):
    import json

    from freecad.forgepdm import api, cad, commands, drawing_publication, ui, workspace

    original_select, original_review = ui.select_drawing_pages, ui.review_drawing_publication
    original_upload = client.upload_drawing_publication
    ui.select_drawing_pages = lambda pages: pages
    ui.review_drawing_publication = lambda *args: True

    def snapshot(document):
        return (
            document.Name,
            document.FileName,
            document.Label,
            cad.document_modified(document),
            [(obj.Name, obj.Label) for obj in document.Objects],
            workspace.digest(document.FileName)[0],
        )

    def select_all(_):
        raise AssertionError("Recovery unexpectedly re-exported PDF pages")

    try:
        App.setActiveDocument(part.Name)
        selected["workspace"] = "part-download"
        drive(commands.CheckoutCommand())
        drive(commands.UploadCommand())
        before = snapshot(part)
        metadata = part.getObject("ForgePDM_Metadata")
        part_revision, part_item, part_number = (
            metadata.RevisionId,
            metadata.ItemId,
            metadata.ItemNumber,
        )
        lease = worker(client.get_checkout, part_revision)
        selection_before = [
            (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
            for s in Gui.Selection.getSelectionEx()
        ]
        names_before = set(App.listDocuments())
        calls = []

        def lost_response(*args):
            result = original_upload(*args)
            calls.append(result)
            raise api.ForgePDMError(
                "Injected lost PDF publication response", code="connection_failed"
            )

        client.upload_drawing_publication = lost_response
        try:
            drive(commands.PublishDrawingsCommand())
        except api.ForgePDMError as error:
            check(
                "PDF response loss is surfaced with recoverable intent",
                error.code == "connection_failed",
            )
        else:
            raise AssertionError("Transport fault was not surfaced")
        check("PDF export leaves original CAD state and bytes unchanged", snapshot(part) == before)
        check("PDF export closes only its owned copies", set(App.listDocuments()) == names_before)
        check(
            "PDF export restores active document and selection",
            App.ActiveDocument is part
            and [
                (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
                for s in Gui.Selection.getSelectionEx()
            ]
            == selection_before,
        )
        value = workspace.binding(part.FileName, client.base_url)
        journal = json.loads((value["directory"] / drawing_publication.JOURNAL).read_text())
        check("PDF operation journal survives response loss", journal["state"] == "prepared")
        ui.select_drawing_pages = select_all
        drive(commands.PublishDrawingsCommand())
        ui.select_drawing_pages = lambda pages: pages
        client.upload_drawing_publication = original_upload
        publications = worker(
            client._json_request, "GET", "/api/v1/revisions/" + part_revision + "/drawings"
        )
        publication = publications[0]
        check("PDF recovery creates no duplicates", len(publications) == 1 and len(calls) == 1)
        check("two TechDraw pages publish as two separate PDFs", len(publication["pages"]) == 2)
        check(
            "PDFs point to exact original native snapshot",
            publication["source_file_id"] == value["entry"]["file_id"],
        )
        check(
            "PDF publication does not release or renew checkout",
            worker(client.get_checkout, part_revision) == lease,
        )
        for page in publication["pages"]:
            destination = case / page["filename"]
            worker(
                client.download_file,
                page["file_id"],
                str(destination),
                page["content_hash"],
                page["byte_size"],
            )
            check(
                "published " + page["page_name"] + " PDF downloads with verified bytes",
                destination.read_bytes().startswith(b"%PDF-"),
            )

        App.setActiveDocument(assembly.Name)
        selected["workspace"] = "working"
        drive(commands.CheckoutCommand())
        drive(commands.UploadCommand())
        assembly_before = snapshot(assembly)
        drive(commands.PublishDrawingsCommand())
        check(
            "assembly PDF export preserves original assembly", snapshot(assembly) == assembly_before
        )
        assembly_metadata = assembly.getObject("ForgePDM_Metadata")
        assembly_pubs = worker(
            client._json_request,
            "GET",
            "/api/v1/revisions/" + assembly_metadata.RevisionId + "/drawings",
        )
        check(
            "assembly drawing PDF is published",
            len(assembly_pubs) == 1 and len(assembly_pubs[0]["pages"]) == 1,
        )

        App.setActiveDocument(part.Name)
        part.TemplatePart.EditableTexts = {"Title": "New CAD title after PDF publication"}
        part.Box.Length = 120
        part.recompute()
        drive(commands.CheckInCommand())
        stale = worker(
            client._json_request, "GET", "/api/v1/revisions/" + part_revision + "/drawings"
        )
        check(
            "later native snapshot marks existing PDFs stale",
            stale[0]["newer_snapshot_available"] is True,
        )
        check(
            "historical PDFs retain their exact native source",
            stale[0]["source_file_id"] == publication["source_file_id"],
        )
        worker(client.transition, part_revision, "released")
        next_revision = worker(
            client.create_next_revision, part_item, "Browser historical PDF test"
        )
        check(
            "published PDFs remain readable after release",
            len(
                worker(
                    client._json_request, "GET", "/api/v1/revisions/" + part_revision + "/drawings"
                )
            )
            == 1,
        )
        config = json.loads((case / "connection.json").read_text())
        config.update(
            url=client.base_url,
            part=dict(
                id=part_item,
                number=part_number,
                revision=part_revision,
                next_revision=next_revision["id"],
            ),
            assembly=dict(
                id=assembly_metadata.ItemId,
                number=assembly_metadata.ItemNumber,
                revision=assembly_metadata.RevisionId,
            ),
            publication=publication,
        )
        (case / "connection.json").write_text(json.dumps(config))
        (case / "connection.json").chmod(0o600)
    finally:
        ui.select_drawing_pages, ui.review_drawing_publication = original_select, original_review
        client.upload_drawing_publication = original_upload

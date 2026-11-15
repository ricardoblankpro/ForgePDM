"""Extend the disposable drawing command fixture with shared HTTP/native views."""


def exercise(
    App,
    Gui,
    document,
    page,
    target,
    client,
    worker,
    drive,
    mode,
    rid,
    item,
    parts,
    case,
    check,
    original_dialog,
):
    import time
    import TechDrawGui
    from freecad.forgepdm import cad, commands, drawing_bom, ui, workspace
    from freecad.forgepdm.bom_ui import BOMDialog

    assemblies = worker(client.search_items, "", number_series="A")["items"]
    sub = max(
        (row for row in assemblies if row["id"] != item["id"]),
        key=lambda row: row["number"],
    )
    sub_id = sub["current_revision_id"]
    worker(client.acquire_checkout, sub_id)
    sub_lines = [
        {"component_revision_id": parts[0]["current_revision_id"], "quantity": "4", "position": 1}
    ]
    worker(client._json_request, "PUT", f"/api/v1/revisions/{sub_id}/bom", {"lines": sub_lines})
    root_lines = [
        {"component_revision_id": sub_id, "quantity": "3", "position": 1},
        {"component_revision_id": parts[0]["current_revision_id"], "quantity": "2", "position": 2},
    ]
    worker(client._json_request, "PUT", f"/api/v1/revisions/{rid}/bom", {"lines": root_lines})
    report = worker(client.bom_report, rid)
    check(
        "live shared report expands 3 times 4 plus 2 into 14 pinned parts",
        report["views"]["flattened"][0]["quantity"] == "14",
    )
    App.setActiveDocument(document.Name)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(target)
    mode.update(view="indented", note="INDENTED FINISH")
    drive(commands.DrawingBOMCommand().action())
    stored = drawing_bom.read_table(target)
    check(
        "protected Drawing BOM command creates indented format 2",
        stored["format"] == 2
        and stored["layout"]["view"] == "indented"
        and [v["quantity"] for v in stored["report"]["lines"]] == ["3", "12", "2"],
    )
    TechDrawGui.exportPageAsPdf(page, str(case / "indented.pdf"))
    mode.update(view="flattened", note="FLATTENED FINISH")
    drive(commands.DrawingBOMCommand().action())
    flat = drawing_bom.read_table(target)
    check(
        "protected command uses the same server flattened rows",
        flat["report"]["lines"] == report["views"]["flattened"]
        and "FLATTENED" in target.Symbol
        and any("FLATTENED FINISH" in v.values() for v in flat["notes"].values()),
    )
    check(
        "view switching preserves orphaned and isolated annotations",
        any("INDENTED FINISH" in v.values() for v in flat["notes"].values())
        and any("PAINT BLUE" in v.values() for v in flat["notes"].values()),
    )
    mode.update(note=None, nested_change=True, sub_revision=sub_id)
    previous = target.PDMTableData
    try:
        drive(commands.DrawingBOMCommand().action())
    except workspace.WorkspaceError as error:
        check(
            "nested BOM change during drawing review invalidates the report",
            "Published BOM data changed" in str(error) and target.PDMTableData == previous,
        )
    else:
        raise AssertionError("Nested stale drawing report accepted")
    mode.update(nested_change=False)
    worker(client._json_request, "PUT", f"/api/v1/revisions/{sub_id}/bom", {"lines": sub_lines})
    observations, errors = [], []

    def inspect_viewer(dialog):
        if not isinstance(dialog, BOMDialog):
            return original_dialog(dialog)
        deadline = time.monotonic() + 30
        timer = ui.QtCore.QTimer()

        def inspect():
            if dialog.job is not None or dialog.notice_job is not None or dialog.retired_notices:
                if time.monotonic() > deadline:
                    errors.append("Native BOM viewer timed out")
                    if dialog.job:
                        dialog.job.cancel()
                return
            try:
                assert dialog.report, dialog.status.text()
                dialog.view.setCurrentIndex(1)
                child = dialog.tree.topLevelItem(0).child(0)
                assert child.text(4) == "4" and child.text(5) == "12"
                dialog.view.setCurrentIndex(0)
                assert dialog.tree.topLevelItemCount() == 2
                dialog.view.setCurrentIndex(2)
                assert dialog.tree.topLevelItemCount() == 1
                assert dialog.tree.topLevelItem(0).text(5) == "14"
                observations.append(True)
            except BaseException as error:
                errors.append(str(error))
            finally:
                timer.stop()
                dialog.reject()

        timer.timeout.connect(inspect)
        timer.start(20)
        try:
            return original_dialog(dialog)
        finally:
            timer.stop()

    prior = commands.execute_dialog
    commands.execute_dialog = inspect_viewer
    try:
        drive(commands.ShowBOMCommand().action())
    finally:
        commands.execute_dialog = prior
    check(
        "actual native BOM viewer switches all three views with root and parent quantities",
        observations and not errors,
    )
    check(
        "viewer does not synchronize engineering structure",
        worker(client.get_bom, rid)[0]["quantity"] == "3",
    )
    commands._save_document(document)
    uploaded = worker(
        client.upload_native, document.FileName, rid, item["id"], cad.capture(document)
    )
    destination = case / "flattened-retrieval"
    destination.mkdir(exist_ok=True)
    configuration = worker(
        client.retrieve_configuration,
        str(destination),
        rid,
        uploaded["id"],
        uploaded["files"][0]["id"],
    )
    opened = cad.open_configuration(configuration, commands._set_metadata)
    worker(client.finish_configuration, configuration)
    restored = opened["root"].getObject(target.Name)
    worker(
        client._json_request,
        "PUT",
        f"/api/v1/revisions/{sub_id}/bom",
        {"lines": [{**sub_lines[0], "quantity": "8"}]},
    )
    saved = drawing_bom.read_table(restored)
    check(
        "managed retrieval freezes format 2 quantities and notes after nested changes",
        saved["report"]["lines"][0]["quantity"] == "14"
        and "FLATTENED" in restored.Symbol
        and any("FLATTENED FINISH" in v.values() for v in saved["notes"].values()),
    )
    check(
        "live report changes independently to 26 parts",
        worker(client.bom_report, rid)["views"]["flattened"][0]["quantity"] == "26",
    )
    pdf = case / "flattened.pdf"
    TechDrawGui.exportPageAsPdf(opened["root"].getObject(page.Name), str(pdf))
    check("retrieved flattened table exports PDF", pdf.is_file() and pdf.stat().st_size > 1000)

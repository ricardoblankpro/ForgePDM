"""Real Fasteners/native-tree/tooltip checks on disposable serve.py data only."""


def run(App, Gui, directory):
    from concurrent.futures import ThreadPoolExecutor
    from hashlib import sha256
    from html import escape
    import json
    from pathlib import Path
    from time import monotonic, sleep
    from uuid import uuid4

    import FastenersCmd
    from freecad.forgepdm import __version__, api, cad, fasteners, pdm_status, tree_status
    from freecad.forgepdm.open_ui import OpenDialog
    from freecad.forgepdm.session import Session
    from freecad.forgepdm.ui import QtCore, QtGui, QtWidgets

    case = Path(directory)
    assert case.name.startswith("forgepdm-tree-description-qa")
    config = json.loads((case / "connection.json").read_text())
    fixture = json.loads((case / "tree-fixture.json").read_text())
    assert config["url"].startswith("http://127.0.0.1:")
    assert not Session.busy and QtWidgets.QApplication.activeModalWidget() is None
    controller = tree_status._controller
    assert controller is not None
    original_session = Session.client, Session.user
    original_active = App.ActiveDocument.Name if App.ActiveDocument else None
    original_selection = [
        (s.Object, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()
    ]

    def documents():
        return {
            d.Name: (
                d.FileName,
                cad.document_modified(d),
                d.isTouched(),
                sha256(Path(d.FileName).read_bytes()).hexdigest() if d.FileName else None,
                [
                    (
                        o.Name,
                        o.Label,
                        getattr(o, "Label2", None),
                        getattr(o, fasteners.ASSOCIATION, None),
                    )
                    for o in d.Objects
                ],
            )
            for d in App.listDocuments().values()
        }

    before = documents()
    tree_states = [
        (t, t.header().saveState(), t.horizontalScrollBar().value(), t.verticalScrollBar().value())
        for t in controller.column.trees
    ]
    executor = ThreadPoolExecutor(max_workers=1)

    def worker(fn, *args):
        future = executor.submit(fn, *args)
        deadline = monotonic() + 30
        while not future.done():
            QtWidgets.QApplication.processEvents()
            assert monotonic() < deadline, "Fixture request timed out"
            sleep(0.005)
        return future.result()

    document = None
    browser = None
    checks = []
    client = api.ForgePDMClient(config["url"])
    try:
        controller.timer.stop()
        Session.busy = True
        worker(client.login, "web-admin", config["password"])
        browser = OpenDialog(None, client, str(case), lambda: str(case), on_open=lambda _: None)
        browser.timer.stop()
        document = App.newDocument("TreeDescriptionQA" + uuid4().hex[:8])
        document.Label = "Isolated Fasteners tree description QA"
        metadata = document.addObject("App::FeaturePython", "ForgePDM_Metadata")
        item = fixture["assembly"]
        values = dict(
            ItemId=item["id"],
            RevisionId=item["current_revision_id"],
            ItemNumber=item["number"],
            RevisionLabel="A",
            ServerUrl=client.base_url,
        )
        original = worker(client.get_description, item["current_revision_id"])
        values["PDMDescriptionData"] = json.dumps(
            dict(
                version=2,
                revision_id=item["current_revision_id"],
                description=original["description"],
                expected_token=original["token"],
            )
        )
        for name, value in values.items():
            metadata.addProperty("App::PropertyString", name, "ForgePDM")
            setattr(metadata, name, value)
        assembly = document.addObject("App::Part", "Assembly")
        native = []
        for entry in fixture["standards"]:
            obj = document.addObject("Part::FeaturePython", "Fastener" + entry["standard"])
            FastenersCmd.FSScrewObject(obj, entry["standard"], None)
            obj.Diameter = "M12"
            document.recompute()
            if hasattr(obj, "Length"):
                obj.Length = "80"
            assembly.addObject(obj)
            document.recompute()
            fasteners.associate(obj, entry["revision_id"])
            native.append((obj, entry))
        repeat = document.addObject("App::Link", "RepeatedScrew")
        repeat.setLink(native[0][0])
        assembly.addObject(repeat)
        document.recompute()
        Gui.updateGui()
        target_records, _ = tree_status.collect(client)
        targets = [t for t in target_records.values() if not t["foreign"]]
        assert len(targets) == 1 and len(targets[0]["fasteners"]) == 3
        checks.append(
            "Real Fasteners proxies retain exact associated revisions inside an assembly container"
        )

        def rows(name):
            result = []
            for tree in controller.column.trees:
                model = tree.model()
                roots = [model.index(i, 0) for i in range(model.rowCount())]
                for root in roots:
                    if root.data() != document.Label:
                        continue
                    stack = [root]
                    while stack:
                        index = stack.pop()
                        if index.sibling(index.row(), 2).data() == name:
                            description = index.sibling(index.row(), tree_status.DESCRIPTION_COLUMN)
                            result.append(
                                (
                                    tree,
                                    QtCore.QPersistentModelIndex(description),
                                    description.data() or "",
                                    description.data(QtCore.Qt.ToolTipRole) or "",
                                )
                            )
                        stack.extend(model.index(i, 0, index) for i in range(model.rowCount(index)))
            assert result, name
            return result

        for language in ("pt-BR", "en", None):
            browser.description_language.setCurrentIndex(
                browser.description_language.findData(language)
            )
            browser.debounce.stop()
            assert client.description_language == language
            snapshot = worker(pdm_status.fetch, client, targets, {})
            controller.column.render(client, snapshot)
            report = worker(client.bom_report, item["current_revision_id"])
            bom = {
                line["component_revision_id"]: line["description"]
                for line in report["views"]["direct"]
            }
            for obj, entry in native:
                expected = entry[language or "en"]
                assert bom[entry["revision_id"]] == expected
                for _, _, text, tooltip in rows(obj.Name):
                    assert text == expected, (obj.Name, text, expected)
                    assert tooltip == "<qt>" + escape(expected) + "</qt>"
            for _, _, text, _ in rows(repeat.Name):
                assert text == fixture["standards"][0][language or "en"]
            checks.append(
                "Native screw, washer, nut and repeated link match the BOM in "
                + (language or "original language")
            )
            if language == "pt-BR":
                tree, index, _, tooltip = rows(native[0][0].Name)[0]
                parent = QtCore.QModelIndex(index).parent()
                parents = []
                while parent.isValid():
                    parents.append(parent)
                    parent = parent.parent()
                for parent in reversed(parents):
                    tree.expand(parent)
                tree.setColumnWidth(tree_status.DESCRIPTION_COLUMN, 90)
                tree.scrollTo(QtCore.QModelIndex(index))
                Gui.updateGui()
                position = QtCore.QPoint(
                    tree.header().sectionViewportPosition(tree_status.DESCRIPTION_COLUMN) + 20,
                    tree.visualRect(QtCore.QModelIndex(index)).center().y(),
                )
                event = QtGui.QHelpEvent(
                    QtCore.QEvent.ToolTip, position, tree.viewport().mapToGlobal(position)
                )
                QtWidgets.QApplication.sendEvent(tree.viewport(), event)
                assert QtWidgets.QToolTip.text() == tooltip
                checks.append(
                    "Hover help over a narrow native Description cell shows its full text"
                )
                QtWidgets.QToolTip.hideText()
                client.description_language = "en"
                controller.column.render(client, snapshot)
                assert all(text == native[0][1]["en"] for _, _, text, _ in rows(native[0][0].Name))
                checks.append(
                    "An old language snapshot never displays the previous translation after switching"
                )
        changed = native[-1][0]
        changed.Diameter = "M10"
        document.recompute()
        controller.column.render(client, snapshot)
        for _, _, text, _ in rows(changed.Name):
            assert "M10" in text and "ISO7040" in text and text != original["description"]
        checks.append(
            "Changed unassociated geometry shows its own parameters instead of assembly or stale catalog text"
        )
        checks.append(
            "The existing browser language selector drives the same native tree and BOM language"
        )
    finally:
        QtWidgets.QToolTip.hideText()
        if browser is not None:
            browser.finish(0)
            browser.deleteLater()
        if document is not None and document.Name in App.listDocuments():
            App.closeDocument(document.Name)
        if original_active and original_active in App.listDocuments():
            App.setActiveDocument(original_active)
        Gui.Selection.clearSelection()
        for obj, subs in original_selection:
            if subs:
                for sub in subs:
                    Gui.Selection.addSelection(obj, sub)
            else:
                Gui.Selection.addSelection(obj)
        Session.busy = False
        controller.column.render(original_session[0], controller.snapshot, controller.stale)
        for tree, state, horizontal, vertical in tree_states:
            tree.header().restoreState(state)
            tree.horizontalScrollBar().setValue(horizontal)
            tree.verticalScrollBar().setValue(vertical)
        controller.timer.start()
        executor.shutdown(wait=False, cancel_futures=True)
        assert original_session == (Session.client, Session.user)
        assert documents() == before, "Existing document state changed"
    checks.append(
        "Original document bytes, paths, labels, associations, dirty flags, active document and session are preserved"
    )
    report = {
        "addon": __version__,
        "freecad": App.Version()[:3],
        "qt": QtCore.qVersion(),
        "checks": checks,
        "scope": "Disposable server and native documents only",
    }
    (case / "native-tree-descriptions-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return report

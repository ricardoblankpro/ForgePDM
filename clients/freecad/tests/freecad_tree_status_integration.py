"""Real Qt status-column acceptance checks, called by the multi-user harness."""


def run(
    App, Gui, case, worker, check, alice, bob, alice_user, bob_user, parent, item_id, revision_id
):
    import json
    import importlib.util
    from pathlib import Path
    from threading import Event
    from time import monotonic

    from freecad.forgepdm import api, cad, commands, session, tree_status, workspace
    from freecad.forgepdm.ui import QtCore, QtWidgets

    # Preserve the live Session class while testing new hooks from repository code.
    session_spec = importlib.util.spec_from_file_location(
        "freecad.forgepdm._status_session_fixture",
        Path(__file__).parents[1] / "freecad/forgepdm/session.py",
    )
    session_source = importlib.util.module_from_spec(session_spec)
    session_spec.loader.exec_module(session_source)
    previous_methods = {name: session.Session.__dict__[name] for name in ("set_client", "clear")}
    for name in previous_methods:
        setattr(session.Session, name, session_source.Session.__dict__[name])

    worker(bob.transition, revision_id, "released")
    revision_b = worker(bob.create_next_revision, item_id, "Tree status fixture B")
    new_doc = App.newDocument("PDMStatusOtherUser")
    new_doc.Label = "PDM status — Bob's working revision"
    new_doc.addObject("Part::Box", "Box")
    commands._set_metadata(
        new_doc,
        ItemId=item_id,
        RevisionId=revision_b["id"],
        ItemNumber="STATUS",
        RevisionLabel="B",
        ServerUrl=alice.base_url,
    )
    new_doc.recompute()
    new_doc.saveAs(str(case / "status-b.FCStd"))
    if new_doc.HasPendingTransaction:
        new_doc.commitTransaction()
    Gui.getDocument(new_doc.Name).save()
    # Disposable fixture item numbers can overlap the user's separate server.
    parent.Label = "PDM status — isolated parent assembly"
    parent.recompute()
    Gui.getDocument(parent.Name).save()
    App.setActiveDocument(parent.Name)
    Gui.updateGui()
    documents_before = {
        d.Name: (
            d.Label,
            cad.document_modified(d),
            [(o.Name, o.Label, tuple(o.PropertiesList)) for o in d.Objects],
        )
        for d in App.listDocuments().values()
    }
    files_before = {
        d.FileName: workspace.digest(d.FileName)[0]
        for d in App.listDocuments().values()
        if d.FileName
    }
    selection_before = [
        (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
        for s in Gui.Selection.getSelectionEx()
    ]
    active_before = App.ActiveDocument.Name
    previous_controller = tree_status._controller
    if previous_controller is not None:
        previous_controller.timer.stop()
    controller = tree_status.Controller()
    tree_status._controller = controller
    release = Event()
    normal_fetch = alice.fetch_tree_status

    def spin(predicate, timeout=15):
        deadline = monotonic() + timeout
        loop, timer = QtCore.QEventLoop(), QtCore.QTimer()

        def poll():
            controller.tick()
            if predicate() or monotonic() > deadline:
                loop.quit()

        timer.timeout.connect(poll)
        timer.start(20)
        if not predicate():
            loop.exec()
        timer.stop()
        assert predicate(), "Timed out waiting for status controller"

    def settled():
        return (
            controller.future is None and not controller.pending and controller.snapshot is not None
        )

    def root_and_item(document, name=""):
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            if tree.metaObject().className() != "Gui::TreeWidget":
                continue
            for i in range(tree.topLevelItemCount()):
                root = tree.topLevelItem(i)
                if root.text(0) != document.Label:
                    continue
                if not name:
                    return tree, root
                pending = [root]
                while pending:
                    item = pending.pop()
                    if item.text(2) == name:
                        return tree, item
                    pending.extend(item.child(j) for j in range(item.childCount()))
        raise AssertionError("Missing native tree row: " + name)

    try:
        # Invoke the registered command implementation, not just the renderer.
        commands.RefreshPDMStatusCommand().Activated()
        spin(settled)
        check("status batch completed without stale data", controller.stale is None)
        count, ambiguous = controller.column.render(alice, controller.snapshot)
        check("native PDM status column installed", count > 0)
        tree, root = root_and_item(parent)
        check("parent shows your checkout: " + root.text(3), "You" in root.text(3))
        tree, first = root_and_item(parent, "First")
        _, second = root_and_item(parent, "Second")
        check(
            "released and newer revision badges coexist",
            "Released" in first.text(3) and "Rev B available" in first.text(3),
        )
        check("fresh occurrence has no snapshot alert", "Snapshot update" not in first.text(3))
        check(
            "old occurrence has same-revision snapshot alert", "Snapshot update" in second.text(3)
        )
        _, other = root_and_item(new_doc)
        check("other checkout owner is shown by name", bob_user["display_name"] in other.text(3))
        badges = other.data(3, QtCore.Qt.UserRole)
        check("other user's checkout has orange badge", any(b["kind"] == "other" for b in badges))
        check(
            "native icon and label remain present",
            not first.icon(0).isNull() and first.text(0) == parent.getObject("First").Label,
        )
        check(
            "tooltip has expiry and refresh time",
            "until" in other.toolTip(3) and "Last server check" in other.toolTip(3),
        )
        tree.setColumnCount(5)
        tree.headerItem().setText(4, "Fixture extension")
        controller.column.clear()
        check(
            "private statuses clear even if another extension adds a column",
            first.text(3) == "" and first.data(3, QtCore.Qt.UserRole) is None,
        )
        check(
            "status removal preserves another extension's column",
            tree.columnCount() == 5 and tree.headerItem().text(4) == "Fixture extension",
        )
        tree.setColumnCount(3)
        controller.column.render(alice, controller.snapshot)
        # Duplicate source copies must be refused, never assigned by label alone.
        if ambiguous:
            check("ambiguous duplicate document roots are handled safely", ambiguous > 0)
        parent_root = root_and_item(parent)[1]
        parent_root.setExpanded(True)
        for j in range(parent_root.childCount()):
            parent_root.child(j).setExpanded(True)
        Gui.updateGui()
        tree.grab().save(str(case / "tree-status.png"))

        def offline(*args):
            raise api.ForgePDMError("Injected offline server", code="connection_failed")

        alice.fetch_tree_status = offline
        controller.request()
        spin(
            lambda: (
                controller.future is None
                and not controller.pending
                and controller.stale is not None
            )
        )
        controller.column.render(alice, controller.snapshot, controller.stale)
        check(
            "offline refresh renders cached information as stale",
            second.text(3) == "Stale status" and "last known" in second.toolTip(3),
        )
        alice.fetch_tree_status = normal_fetch
        controller.request()
        spin(settled)
        check("manual refresh recovers from offline failure", controller.stale is None)

        started = Event()

        def delayed(*args):
            started.set()
            assert release.wait(10), "Delayed fixture was not released"
            return normal_fetch(*args)

        alice.fetch_tree_status = delayed
        controller.request()
        spin(started.is_set)
        session.Session.clear()
        check(
            "logout immediately clears cached private statuses",
            controller.snapshot is None and controller.key is None,
        )
        check("logout removes owned tree column", tree.columnCount() == 3)
        session.Session.set_client(bob, bob_user)
        release.set()
        spin(settled)
        own_b = controller.snapshot["remote"][revision_b["id"]]["checkout"]
        check(
            "late previous-user result is discarded after account switch", own_b["is_mine"] is True
        )
        alice.fetch_tree_status = normal_fetch
        session.Session.set_client(alice, alice_user)
        spin(settled)
        session.Session.busy = True
        try:
            controller.request()
            controller.tick()
            check(
                "background refresh defers during CAD commands",
                controller.future is None and controller.pending,
            )
        finally:
            session.Session.busy = False
        spin(settled)
        controller.next_refresh = 0
        controller.tick()
        check("scheduled refresh starts a background request", controller.future is not None)
        spin(settled)

        documents_after = {
            d.Name: (
                d.Label,
                cad.document_modified(d),
                [(o.Name, o.Label, tuple(o.PropertiesList)) for o in d.Objects],
            )
            for d in App.listDocuments().values()
        }
        check(
            "status refresh never changes CAD labels properties or dirty flags",
            documents_after == documents_before,
        )
        check(
            "status refresh never saves CAD files",
            all(workspace.digest(p)[0] == h for p, h in files_before.items()),
        )
        check(
            "status refresh preserves selection and active document",
            App.ActiveDocument.Name == active_before
            and [
                (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
                for s in Gui.Selection.getSelectionEx()
            ]
            == selection_before,
        )
        (case / "status-summary.json").write_text(
            json.dumps(dict(rows=count, ambiguous_roots=ambiguous), indent=2)
        )
    finally:
        release.set()
        alice.fetch_tree_status = normal_fetch
        controller.close()
        tree_status._controller = previous_controller
        if previous_controller is not None:
            previous_controller.reset()
            previous_controller.timer.start()
        for name, method in previous_methods.items():
            setattr(session.Session, name, method)

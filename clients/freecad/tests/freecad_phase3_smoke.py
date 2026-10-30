"""Real GUI integration harness; run through MCP with an isolated server case.

Not collected by pytest. Credentials are read only from the private case file.
Existing documents/session/preferences are restored; fixture files stay in /tmp.
"""


def run(case_directory):
    from concurrent.futures import ThreadPoolExecutor
    import importlib
    import json
    from pathlib import Path
    import shutil
    import sys
    from threading import get_ident
    import traceback

    import FreeCAD as App
    import FreeCADGui as Gui
    from freecad.forgepdm import session, api, fcstd, workspace, cad, commands, ui

    original_client, original_user = session.Session.client, session.Session.user
    original_names = set(App.listDocuments())
    active = App.ActiveDocument.Name if App.ActiveDocument else None
    for module in (api, fcstd, workspace, cad, commands):
        importlib.reload(module)
    if original_client is not None:
        refreshed = api.ForgePDMClient(original_client.base_url, original_client.timeout)
        refreshed.token = original_client.token
        refreshed.expires_at = original_client.expires_at
        original_client = refreshed
    # FreeCAD retains old callback instances on live reload. This is confined
    # to the test harness; a normal addon installation requires a restart.
    import gc
    classes = {name: value for name, value in vars(commands).items()
               if isinstance(value, type) and name.endswith("Command")}
    for instance in gc.get_objects():
        previous = type(instance)
        if previous.__module__ == commands.__name__ and previous.__name__ in classes:
            instance.__class__ = classes[previous.__name__]
    case = Path(case_directory)
    config = json.loads((case / "connection.json").read_text())
    report = {"freecad": App.Version(), "python": sys.version, "qt": ui.QtCore.qVersion(),
              "checks": [], "scope": "Real FreeCAD GUI, isolated HTTP server, automated dialog choices"}
    main_thread = get_ident()
    threads, ticks = [], [0]
    executor = ThreadPoolExecutor(max_workers=1)
    originals = {name: getattr(commands, name) for name in
                 ("ask_choice", "ask_text", "_choose_workspace", "information", "warning")}
    selected = {"kind": "part", "project": "PRJ-SMOKE"}

    def check(name, condition):
        assert condition, name
        report["checks"].append(name)

    def worker(function, *args, **kwargs):
        def execute():
            threads.append(get_ident())
            return function(*args, **kwargs)
        future = executor.submit(execute)
        loop = ui.QtCore.QEventLoop()
        timer = ui.QtCore.QTimer()
        def poll():
            ticks[0] += 1
            if future.done():
                loop.quit()
        timer.timeout.connect(poll)
        timer.start(5)
        loop.exec()
        timer.stop()
        return future.result(timeout=1)

    def drive(command):
        generator = command.action()
        value = None
        while True:
            try:
                request = generator.send(value)
            except StopIteration:
                return
            value = worker(request.function, *request.args, **request.kwargs)

    def choice(title, prompt, choices, default=None):
        if title == "New ForgePDM Item":
            return selected["kind"]
        return next((value for value in choices if selected["project"] in value), choices[0])

    def upload(document, kind="part", project="PRJ-SMOKE"):
        selected.update(kind=kind, project=project)
        App.setActiveDocument(document.Name)
        drive(commands.UploadCommand())
        value = workspace.binding(document.FileName, client.base_url)
        return dict(value["entry"])

    def source(name, folder):
        path = case / folder / "part.FCStd"
        path.parent.mkdir(parents=True)
        document = App.newDocument(name)
        document.saveAs(str(path))
        return document, path

    def component(name, folder, length, project):
        document, path = source(name, folder)
        box = document.addObject("Part::Box", "Box")
        box.Length, box.Width, box.Height = length, 2, 3
        document.recompute()
        document.save()
        before = workspace.digest(path)
        entry = upload(document, project=project)
        check(name + " original preserved", workspace.digest(path) == before)
        return document, entry

    def assembly(name, links):
        document, _path = source(name, name)
        group = document.addObject("App::Part", "Assembly")
        for index, target in enumerate(links):
            link = document.addObject("App::Link", "Occurrence" + str(index))
            link.setLink(target)
            group.addObject(link)
            link.Placement.Base = App.Vector(index * 20, 0, 0)
        document.recompute()
        document.save()
        return document, upload(document, "assembly")

    def retrieve(root, entry):
        return worker(client.retrieve_configuration, str(root), entry["revision_id"],
                      entry["dataset_id"], entry["file_id"])

    def open_config(configuration):
        result = cad.open_configuration(configuration, commands._set_metadata)
        worker(client.finish_configuration, configuration)
        return result

    client = api.ForgePDMClient(config["base_url"])
    try:
        user = worker(client.login, config["username"], config["password"])
        session.Session.set_client(client, user)
        commands.ask_choice = choice
        commands.ask_text = lambda *args, **kwargs: "Phase 3 integration test"
        commands._choose_workspace = lambda *args: str(case / "source-workspace")
        commands.information = lambda *args: None
        commands.warning = lambda *args: None
        names = ["Login", "Logout", "Upload", "Checkout", "CheckIn", "Release",
                 "NewRevision", "Download", "ShowBOM"]
        check("nine command IDs registered", all("ForgePDM_" + n in Gui.listCommands() for n in names))
        first, first_a = component("P3First", "original-one", 10, "PRJ-SMOKE")
        second, second_a = component("P3Second", "original-two", 30, "PRJ-HIDDEN")
        sub, sub_a = assembly("P3Sub", [first.Box, first.Box])
        root, root_a = assembly("P3Root", [sub.Assembly, second.Box])
        check("nested assemblies uploaded with exact manifests", len(worker(client.get_manifest, root_a["dataset_id"])["references"]) == 2)
        # Deliberately set engineering BOM through its existing API, never by CAD extraction.
        for parent, children in [(sub_a, [first_a]), (root_a, [sub_a, second_a])]:
            lines = [{"component_revision_id": child["revision_id"], "quantity": "1", "position": str(index + 1)}
                     for index, child in enumerate(children)]
            worker(client._json_request, "PUT", "/api/v1/revisions/" + parent["revision_id"] + "/bom", {"lines": lines})
        for entry in (first_a, second_a, sub_a, root_a):
            worker(client.checkin, entry["revision_id"], "Verified A")
            worker(client.transition, entry["revision_id"], "released")
        old_path = Path(first.FileName)
        old_hash = workspace.digest(old_path)
        App.setActiveDocument(first.Name)
        drive(commands.NewRevisionCommand())
        first.Box.Length = 15
        first.recompute()
        upload(first)
        check("new revision uses a separate file", Path(first.FileName) != old_path and workspace.digest(old_path) == old_hash)
        target_root = case / "retrieval-workspace"
        configuration = retrieve(target_root, root_a)
        opened = open_config(configuration)
        documents = opened["documents"]
        old_first = documents[first_a["file_id"]]
        old_sub = documents[sub_a["file_id"]]
        old_root = opened["root"]
        check("historical component geometry retained", old_first.Box.Length.Value == 10 and first.Box.Length.Value == 15)
        check("same-basename components remain distinct", old_first is not documents[second_a["file_id"]] and documents[second_a["file_id"]].Box.Length.Value == 30)
        check("repeated components share exact pinned document", old_sub.Occurrence0.LinkedObject.Document is old_first and old_sub.Occurrence1.LinkedObject.Document is old_first)
        check("occurrence placement retained", old_sub.Occurrence1.Placement.Base.x == 20)
        check("nested link points to pinned assembly object", old_root.Occurrence0.LinkedObject is old_sub.Assembly)
        ledger = json.loads((Path(configuration["directory"]) / workspace.MANIFEST).read_text())
        check("complete ledger after GUI reference verification", ledger["state"] == "complete")
        root_relative = Path(old_root.FileName).relative_to(target_root)
        cad.close_owned(opened["owned"])
        relocated = case / "relocated-workspace"
        shutil.move(str(target_root), relocated)
        before_names = set(App.listDocuments())
        moved = App.openDocument(str(relocated / root_relative))
        check("relocated root resolves nested assembly", moved.Occurrence0.LinkedObject.Document.Occurrence0.LinkedObject.Length.Value == 10)
        moved_documents = [doc for name, doc in App.listDocuments().items() if name not in before_names]
        check("relocated references stay inside relocated workspace", all(Path(doc.FileName).is_relative_to(relocated) for doc in moved_documents))
        cad.close_owned(moved_documents)
        # Existing editable working copy is dirty: no implicit overwrite/adoption.
        second.Box.Length = 31
        second.recompute()
        try:
            cad.capture(root)
        except workspace.WorkspaceError:
            check("unsaved linked component rejected", True)
        else:
            raise AssertionError("dirty linked component accepted")
        second.Box.Length = 30
        second.recompute()
        viewer = api.ForgePDMClient(config["base_url"])
        worker(viewer.login, config["viewer_username"], config["viewer_password"])
        denied = case / "denied-workspace"
        try:
            worker(viewer.retrieve_configuration, str(denied), root_a["revision_id"], root_a["dataset_id"], root_a["file_id"])
        except api.ForgePDMError as error:
            check("private dependency denies retrieval", error.status == 403)
        else:
            raise AssertionError("private component retrieval accepted")
        check("denied retrieval publishes no configuration", not list(denied.glob("configurations/*")))
        # Real network failure after one verified cache fill; retry may reuse it.
        retry_root = case / "retry-workspace"
        original_download = client.download_file
        downloads = [0]
        def interrupted(*args, **kwargs):
            downloads[0] += 1
            if downloads[0] == 2:
                raise api.ForgePDMError("Injected interrupted transfer")
            return original_download(*args, **kwargs)
        client.download_file = interrupted
        try:
            retrieve(retry_root, root_a)
        except api.ForgePDMError:
            check("interrupted graph has no published configuration", not list(retry_root.glob("configurations/*")))
        finally:
            client.download_file = original_download
        retried = retrieve(retry_root, root_a)
        recovered = open_config(retried)
        check("retry reconstructs complete graph", len(recovered["documents"]) == 4)
        cad.close_owned(recovered["owned"])
        # Exercise the public Download action and its item/revision selectors.
        commands.ask_text = lambda *args, **kwargs: root.ForgePDM_Metadata.ItemNumber
        commands._choose_workspace = lambda *args: str(case / "command-download")
        before_command = set(App.listDocuments())
        drive(commands.DownloadCommand())
        command_documents = [doc for name, doc in App.listDocuments().items()
                             if name not in before_command]
        check("Download command opens verified four-document configuration", len(command_documents) == 4)
        command_ledgers = list((case / "command-download/configurations").glob("*/" + workspace.MANIFEST))
        check("Download command completes workspace ledger", len(command_ledgers) == 1 and json.loads(command_ledgers[0].read_text())["state"] == "complete")
        cad.close_owned(command_documents)
        check("HTTP and transfer work stayed off GUI thread", threads and all(thread != main_thread for thread in threads))
        check("GUI timers remained responsive during requests", ticks[0] > 20)
        report["heartbeat_ticks"] = ticks[0]
        report["status"] = "passed"
    except BaseException:
        report["status"] = "failed"
        report["traceback"] = traceback.format_exc()
    finally:
        for name, method in originals.items():
            setattr(commands, name, method)
        session.Session.client, session.Session.user = original_client, original_user
        for name in list(App.listDocuments()):
            if name not in original_names:
                App.closeDocument(name)
        if active and active in App.listDocuments():
            App.setActiveDocument(active)
        executor.shutdown(wait=True)
        (case / "phase3-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    return report


if "PHASE3_CASE" in globals():
    run(globals()["PHASE3_CASE"])

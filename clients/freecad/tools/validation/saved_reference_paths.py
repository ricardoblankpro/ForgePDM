"""Disposable native cached-path regression; invoke run(App, Gui, case_dir) via MCP."""


def run(App, Gui, case_dir):
    import hashlib
    from pathlib import Path

    from freecad.forgepdm import cad, commands, fcstd
    from freecad.forgepdm.session import Session

    assert not Session.busy
    original_documents = set(App.listDocuments())
    active = App.ActiveDocument
    selection = Gui.Selection.getSelectionEx()
    client = Session.client
    checks = []
    root = Path(case_dir)
    root.mkdir(parents=True, exist_ok=True)

    def check(label, condition):
        assert condition, label
        checks.append(label)

    def rejected(path, references):
        try:
            fcstd.validate(path, references, source_path=path)
        except fcstd.CADIntegrityError:
            return True
        return False

    def state(document):
        return {
            obj.Name: (obj.Label, str(obj.Placement), obj.LinkedObject.Name)
            for obj in document.Objects
            if hasattr(obj, "LinkedObject")
        }

    try:
        for kind in ("App::Link", "Assembly::AssemblyLink"):
            folder = root / kind.split("::")[0]
            original, working = folder / "original", folder / "working"
            original.mkdir(parents=True)
            working.mkdir()
            child = App.newDocument("SavedPathChild")
            shape = child.addObject("Part::Box", "Box")
            metadata = child.addObject("App::FeaturePython", "ForgePDM_Metadata")
            for prop in ("ItemId", "RevisionId"):
                metadata.addProperty("App::PropertyString", prop, "ForgePDM")
                setattr(metadata, prop, prop)
            child.recompute()
            child.saveAs(str(original / "part.FCStd"))
            child_hash = hashlib.sha256(Path(child.FileName).read_bytes()).hexdigest()
            owner = App.newDocument("SavedPathOwner")
            owner.saveAs(str(original / "assembly.FCStd"))
            link = owner.addObject(kind, "Component")
            if kind == "App::Link":
                link.setLink(shape)
            else:
                link.LinkedObject = shape
            link.Placement = App.Placement(App.Vector(12, 24, 36), App.Rotation())
            internal = owner.addObject("App::Link", "Internal")
            internal.setLink(link)
            owner.recompute()
            owner.save()
            baseline = state(owner)
            references = cad.capture(owner)
            owner.saveAs(str(working / "model.FCStd"))
            check(
                kind + " reproduces stale paths after native Save As",
                rejected(owner.FileName, references),
            )
            commands._save_document(owner)
            fcstd.validate(owner.FileName, references, source_path=owner.FileName)
            check(
                kind + " ordinary save repairs paths and keeps live references",
                cad.capture(owner) == references,
            )
            check(
                kind + " preserves placements, labels and internal links", state(owner) == baseline
            )
            commands._save_document(owner)
            fcstd.validate(owner.FileName, references, source_path=owner.FileName)
            check(kind + " repeated save keeps repaired paths", state(owner) == baseline)
            changed = [dict(ref, target_object_name="DifferentObject") for ref in references]
            check(
                kind + " still rejects genuine reference changes", rejected(owner.FileName, changed)
            )
            check(
                kind + " leaves component bytes unchanged",
                hashlib.sha256(Path(child.FileName).read_bytes()).hexdigest() == child_hash,
            )
            readonly_source = Path(owner.FileName)
            source_hash = hashlib.sha256(readonly_source.read_bytes()).hexdigest()
            readonly_source.chmod(0o444)
            destination = folder / "writable-copy.FCStd"
            dialog = commands.QtWidgets.QFileDialog
            original_choose = dialog.getSaveFileName
            try:
                dialog.getSaveFileName = lambda *args: (str(destination), "")
                commands._save_document(owner)
            finally:
                dialog.getSaveFileName = original_choose
                readonly_source.chmod(0o644)
            fcstd.validate(owner.FileName, references, source_path=owner.FileName)
            check(
                kind + " writable Save As repairs paths and preserves its source",
                Path(owner.FileName) == destination
                and hashlib.sha256(readonly_source.read_bytes()).hexdigest() == source_hash
                and state(owner) == baseline,
            )
            path = owner.FileName
            App.closeDocument(owner.Name)
            reopened = App.openDocument(path)
            check(
                kind + " reopens with exact targets and placements",
                state(reopened) == baseline and cad.capture(reopened) == references,
            )
            App.closeDocument(reopened.Name)
            App.closeDocument(child.Name)
    finally:
        for name in set(App.listDocuments()) - original_documents:
            App.closeDocument(name)
        if active is not None:
            App.setActiveDocument(active.Name)
        Gui.Selection.clearSelection()
        for entry in selection:
            for sub in entry.SubElementNames or ("",):
                Gui.Selection.addSelection(entry.Object, sub)
        assert set(App.listDocuments()) == original_documents
        assert Session.client is client and not Session.busy
    return {"checks": checks, "freecad": App.Version()}

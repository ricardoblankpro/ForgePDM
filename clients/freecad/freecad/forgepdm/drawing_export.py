"""Modal GUI-thread PDF export of owned, verified configuration copies only."""

from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui

from . import cad
from .ui import QtCore, QtWidgets, parent_window
from .workspace import WorkspaceError


def export(configuration, pages, directory, set_metadata):
    import TechDrawGui

    active = App.ActiveDocument.Name if App.ActiveDocument else None
    selection = [
        (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
        for s in Gui.Selection.getSelectionEx()
    ]
    progress = QtWidgets.QProgressDialog(
        "Preparing verified drawing snapshot…", "", 0, len(pages), parent_window()
    )
    progress.setCancelButton(None)
    progress.setWindowModality(QtCore.Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.show()
    opened = None
    previous_documents = set(App.listDocuments())
    try:
        QtWidgets.QApplication.processEvents()
        opened = cad.open_configuration(configuration, set_metadata)
        document = opened["root"]
        for index, record in enumerate(pages, 1):
            obj = document.getObject(record["page_name"])
            if (
                obj is None
                or not obj.isDerivedFrom("TechDraw::DrawPage")
                or obj.Label != record["page_label"]
            ):
                raise WorkspaceError(
                    "The reviewed page differs from the uploaded CAD snapshot; upload current changes first"
                )
            progress.setLabelText("Exporting PDF page {} of {}…".format(index, len(pages)))
            progress.setValue(index - 1)
            cad.settle_techdraw(document)
            path = Path(directory) / "page_{:04d}.pdf".format(index)
            if path.exists():
                raise WorkspaceError("The PDF export destination already exists")
            TechDrawGui.exportPageAsPdf(obj, str(path))
            if not path.is_file() or not path.stat().st_size:
                raise WorkspaceError("FreeCAD did not produce a drawing PDF")
            progress.setValue(index)
        return pages
    finally:
        # Application-modal input guard covers construction through cleanup. Only
        # our copies can have known export-induced changes; never close user docs.
        if opened is not None:
            for document in reversed(opened["owned"]):
                try:
                    if App.getDocument(document.Name) is document:
                        App.closeDocument(document.Name)
                except NameError:
                    pass
        else:
            for name in set(App.listDocuments()) - previous_documents:
                document = App.getDocument(name)
                if document.FileName and Path(document.FileName).resolve().is_relative_to(
                    Path(configuration["directory"]).resolve()
                ):
                    App.closeDocument(name)
        if active and active in App.listDocuments():
            App.setActiveDocument(active)
        current = [
            (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
            for s in Gui.Selection.getSelectionEx()
        ]
        if current != selection:
            Gui.Selection.clearSelection()
            for doc, name, subnames in selection:
                if doc not in App.listDocuments() or App.getDocument(doc).getObject(name) is None:
                    continue
                for subname in subnames or ("",):
                    Gui.Selection.addSelection(doc, name, subname)
        progress.close()
        progress.deleteLater()

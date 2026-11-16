"""GUI-thread isometric capture of a just-saved document; never save for preview."""

import tempfile
from pathlib import Path

from . import cad
from .workspace import digest

SIZE = 384


def capture(document):
    import FreeCAD as App
    import FreeCADGui as Gui

    if not document.FileName or cad.document_modified(document):
        raise ValueError("Save the document before generating its preview")
    source = Path(document.FileName)
    if source.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("Automatic previews currently support CAD files up to 256 MiB")
    identity = digest(source)
    # A parent's saved link can still display newer unsaved component geometry.
    # Reject that preview rather than representing the pinned snapshot incorrectly.
    seen, pending, linked, linked_paths = set(), [document], [], {source.resolve()}
    while pending:
        current = pending.pop()
        if current.Name in seen:
            continue
        seen.add(current.Name)
        if cad.document_modified(current):
            raise ValueError("A displayed component has unsaved changes")
        for reference in cad.capture(current):
            target_path = Path(reference["target_path"]).resolve()
            if target_path in linked_paths:
                continue
            linked_paths.add(target_path)
            if len(linked_paths) > 1000 or target_path.stat().st_size > 256 * 1024 * 1024:
                raise ValueError("The displayed component set exceeds preview limits")
            target = next(
                (
                    doc
                    for doc in App.listDocuments().values()
                    if doc.FileName and Path(doc.FileName).resolve() == target_path
                ),
                None,
            )
            if target is None:
                raise ValueError("A linked component is not available for preview")
            linked.append((target, target_path, digest(target_path)))
            pending.append(target)
    gui_document = Gui.getDocument(document.Name)
    view = gui_document.activeView()
    if not hasattr(view, "getCamera"):
        views = gui_document.mdiViewsOfType("Gui::View3DInventor")
        if not views:
            raise ValueError("No existing 3D view is available for this snapshot")
        view = views[0]
    camera_type, camera = view.getCameraType(), view.getCameraNode().copy()
    animation = view.isAnimationEnabled()
    selection = [
        (s.DocumentName, s.ObjectName, tuple(s.SubElementNames))
        for s in Gui.Selection.getSelectionEx()
    ]
    try:
        Gui.Selection.clearSelection()
        view.setAnimationEnabled(False)
        view.setCameraType("Orthographic")
        view.viewIsometric()
        view.fitAll()
        with tempfile.TemporaryDirectory(prefix="forgepdm-preview-") as directory:
            image = Path(directory) / "isometric.png"
            view.saveImage(str(image), SIZE, SIZE, "White")
            png = image.read_bytes()
    finally:
        try:
            view.setCameraType(camera_type)
            # Copy native fields directly: parsing getCamera() text renormalizes
            # axis-angle rotations and introduces repeated float rounding drift.
            view.getCameraNode().copyFieldValues(camera)
        finally:
            view.setAnimationEnabled(animation)
            Gui.Selection.clearSelection()
            for doc, obj, subelements in selection:
                for subelement in subelements or ("",):
                    Gui.Selection.addSelection(doc, obj, subelement)
    if cad.document_modified(document) or digest(source) != identity:
        raise ValueError("The document changed while its preview was being prepared")
    if any(cad.document_modified(doc) or digest(path) != before for doc, path, before in linked):
        raise ValueError("A linked component changed while its preview was being prepared")
    return {"source_content_hash": identity[0], "png": png, "render_profile": "isometric-v1"}


def optional(document):
    try:
        return capture(document)
    except Exception:
        # Preview failure must never prevent saving/uploading the engineering data.
        return None

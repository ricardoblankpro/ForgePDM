"""FreeCAD discovers this module through the shared freecad namespace."""

import FreeCADGui as Gui

from .workbench import ForgePDMWorkbench


if "ForgePDMWorkbench" not in Gui.listWorkbenches():
    Gui.addWorkbench(ForgePDMWorkbench())

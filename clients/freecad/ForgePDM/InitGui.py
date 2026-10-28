"""Register the ForgePDM Workbench with FreeCAD Gui."""

import FreeCADGui as Gui
from FreeCADGui import Workbench


class ForgePDMWorkbench(Workbench):
    MenuText = "ForgePDM"
    ToolTip = "Manage FreeCAD documents with a ForgePDM server"
    Icon = ""

    def Initialize(self):
        from ForgePDM.commands import (
            CheckInCommand,
            CheckoutCommand,
            DownloadCommand,
            LoginCommand,
            LogoutCommand,
            NewRevisionCommand,
            ReleaseCommand,
            ShowBOMCommand,
            UploadCommand,
        )

        commands = [
            ("ForgePDM_Login", LoginCommand()),
            ("ForgePDM_Logout", LogoutCommand()),
            ("ForgePDM_Upload", UploadCommand()),
            ("ForgePDM_Checkout", CheckoutCommand()),
            ("ForgePDM_CheckIn", CheckInCommand()),
            ("ForgePDM_Release", ReleaseCommand()),
            ("ForgePDM_NewRevision", NewRevisionCommand()),
            ("ForgePDM_Download", DownloadCommand()),
            ("ForgePDM_ShowBOM", ShowBOMCommand()),
        ]
        for name, command in commands:
            Gui.addCommand(name, command)
        self.appendToolbar("ForgePDM", [name for name, _command in commands])
        self.appendMenu("ForgePDM", [name for name, _command in commands])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ForgePDMWorkbench())

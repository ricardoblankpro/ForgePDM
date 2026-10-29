"""Lazy Workbench initialization; startup performs no API requests."""

import FreeCADGui as Gui

from .resources import icon_path


class ForgePDMWorkbench(Gui.Workbench):
    MenuText = "ForgePDM"
    ToolTip = "Manage FreeCAD documents with a ForgePDM server"
    Icon = icon_path()

    def Initialize(self):
        if getattr(self, "_initialized", False):
            return

        from . import commands
        from .i18n import install_translations, translate

        install_translations(Gui)
        entries = (
            ("ForgePDM_Login", commands.LoginCommand),
            ("ForgePDM_Logout", commands.LogoutCommand),
            ("ForgePDM_Upload", commands.UploadCommand),
            ("ForgePDM_Checkout", commands.CheckoutCommand),
            ("ForgePDM_CheckIn", commands.CheckInCommand),
            ("ForgePDM_Release", commands.ReleaseCommand),
            ("ForgePDM_NewRevision", commands.NewRevisionCommand),
            ("ForgePDM_Download", commands.DownloadCommand),
            ("ForgePDM_ShowBOM", commands.ShowBOMCommand),
        )
        for name, command in entries:
            Gui.addCommand(name, command())
        names = [name for name, _command in entries]
        self.appendToolbar(translate("ForgePDM", "ForgePDM"), names)
        self.appendMenu(translate("ForgePDM", "ForgePDM"), names)
        self._initialized = True

    def GetClassName(self):
        return "Gui::PythonWorkbench"

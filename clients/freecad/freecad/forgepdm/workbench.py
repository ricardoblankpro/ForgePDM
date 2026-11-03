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
            ("ForgePDM_UpdateFromServer", commands.UpdateFromServerCommand),
            ("ForgePDM_UpdateSelectedComponents", commands.UpdateSelectedComponentsCommand),
            ("ForgePDM_ShowBOM", commands.ShowBOMCommand),
            ("ForgePDM_RefreshTreeLabels", commands.RefreshTreeLabelsCommand),
            ("ForgePDM_ReplaceRevision", commands.ReplaceRevisionCommand),
            ("ForgePDM_ReplaceComponent", commands.ReplaceComponentCommand),
        )
        for name, command in entries:
            Gui.addCommand(name, command())
        names = [name for name, _command in entries]
        self.appendToolbar(translate("ForgePDM", "ForgePDM"), names)
        self.appendMenu(translate("ForgePDM", "ForgePDM"), names)
        from . import tree_observer

        tree_observer.install()
        self._initialized = True

    def GetClassName(self):
        return "Gui::PythonWorkbench"

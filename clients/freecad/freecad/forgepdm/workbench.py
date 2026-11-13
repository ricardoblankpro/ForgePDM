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
            ("ForgePDM_ConfigureWorkspace", commands.ConfigureWorkspaceCommand),
            ("ForgePDM_RegisterStandardPart", commands.RegisterStandardPartCommand),
            (
                "ForgePDM_ChangeStandardPartAssociation",
                commands.ChangeStandardPartAssociationCommand,
            ),
            ("ForgePDM_Upload", commands.UploadCommand),
            ("ForgePDM_Checkout", commands.CheckoutCommand),
            ("ForgePDM_CheckIn", commands.CheckInCommand),
            ("ForgePDM_Release", commands.ReleaseCommand),
            ("ForgePDM_NewRevision", commands.NewRevisionCommand),
            ("ForgePDM_Download", commands.DownloadCommand),
            ("ForgePDM_UpdateFromServer", commands.UpdateFromServerCommand),
            ("ForgePDM_UpdateSelectedComponents", commands.UpdateSelectedComponentsCommand),
            ("ForgePDM_PublishDrawings", commands.PublishDrawingsCommand),
            ("ForgePDM_RefreshPDMStatus", commands.RefreshPDMStatusCommand),
            ("ForgePDM_ShowBOM", commands.ShowBOMCommand),
            ("ForgePDM_DrawingBOM", commands.DrawingBOMCommand),
            ("ForgePDM_AssignMaterials", commands.AssignMaterialsCommand),
            ("ForgePDM_RegisterRawMaterial", commands.RegisterRawMaterialCommand),
            ("ForgePDM_LinkPhysicalMaterial", commands.LinkPhysicalMaterialCommand),
            ("ForgePDM_RefreshTreeLabels", commands.RefreshTreeLabelsCommand),
            ("ForgePDM_ReplaceRevision", commands.ReplaceRevisionCommand),
            ("ForgePDM_ReplaceComponent", commands.ReplaceComponentCommand),
            ("ForgePDM_ManageComponent", commands.ManageComponentCommand),
        )
        for name, command in entries:
            Gui.addCommand(name, command())
        toolbar = [
            "Login",
            "Download",
            "Checkout",
            "Upload",
            "CheckIn",
            "UpdateFromServer",
            "ManageComponent",
            "ShowBOM",
            "AssignMaterials",
        ]
        self.appendToolbar(
            translate("ForgePDM", "ForgePDM"), ["ForgePDM_" + name for name in toolbar]
        )
        groups = {
            "Session": ["Login", "Logout", "ConfigureWorkspace"],
            "Documents": ["Download", "Checkout", "Upload", "CheckIn", "UpdateFromServer"],
            "Components": ["ManageComponent", "ChangeStandardPartAssociation"],
            "Lifecycle": ["Release", "NewRevision"],
            "BOM and publishing": ["ShowBOM", "DrawingBOM", "PublishDrawings"],
            "Catalog and materials": [
                "AssignMaterials",
                "RegisterStandardPart",
                "RegisterRawMaterial",
                "LinkPhysicalMaterial",
            ],
            "Maintenance": ["RefreshPDMStatus", "RefreshTreeLabels"],
        }
        for title, names in groups.items():
            self.appendMenu(
                [translate("ForgePDM", "ForgePDM"), translate("ForgePDM", title)],
                ["ForgePDM_" + name for name in names],
            )
        from . import tree_observer

        tree_observer.install()
        self._initialized = True

    def ContextMenu(self, recipient):
        from . import commands

        if recipient == "Tree" and commands.ChangeStandardPartAssociationCommand().IsActive():
            self.appendContextMenu("ForgePDM", ["ForgePDM_ChangeStandardPartAssociation"])

    def Activated(self):
        from . import tree_status

        tree_status.enable()

    def GetClassName(self):
        return "Gui::PythonWorkbench"

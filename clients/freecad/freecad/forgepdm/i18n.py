"""Translation hooks using the Qt runtime supplied by FreeCAD."""

from .resources import RESOURCE_ROOT


def translate(context, text):
    from .ui import QtCore

    return QtCore.QCoreApplication.translate(context, text)


def install_translations(gui):
    gui.addLanguagePath(str(RESOURCE_ROOT / "translations"))
    gui.updateLocale()

"""Mocked installed-loading tests; these do not execute FreeCAD."""

import subprocess
import sys
from zipfile import ZipFile

import pytest


SCRIPT = r"""
import importlib
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace

sys.path.insert(0, sys.argv[1])
binding = sys.argv[2]
class ForbiddenSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise AssertionError("startup network request")
socket.socket = ForbiddenSocket
gui = ModuleType("FreeCADGui")
registered = {}
command_calls = []
workbenches = {}
language_paths = []
class Workbench:
    def appendToolbar(self, title, names): self.toolbar = list(names)
    def appendMenu(self, title, names): self.menu = list(names)
def add_command(name, command):
    command_calls.append(name)
    registered[name] = command
gui.Workbench = Workbench
gui.addWorkbench = lambda obj: workbenches.update({type(obj).__name__: obj})
gui.listWorkbenches = lambda: workbenches
gui.addCommand = add_command
gui.addLanguagePath = language_paths.append
gui.updateLocale = lambda: None
sys.modules["FreeCADGui"] = gui
app = ModuleType("FreeCAD")
app.ActiveDocument = None
sys.modules["FreeCAD"] = app

import freecad.forgepdm.init_gui as entry
assert 'freecad.forgepdm.commands' not in sys.modules
assert not {'PySide', 'PySide2', 'PySide6'} & set(sys.modules)
assert 'forgepdm' not in sys.modules
importlib.reload(entry)
assert list(workbenches) == ['ForgePDMWorkbench']
wb = workbenches['ForgePDMWorkbench']
assert Path(wb.Icon).is_file()

qt = ModuleType(binding)
qt.QtCore = SimpleNamespace(QCoreApplication=SimpleNamespace(translate=lambda context, text: text))
qt.QtGui = SimpleNamespace()
qt.QtWidgets = SimpleNamespace()
sys.modules[binding] = qt
wb.Initialize()
wb.Initialize()
expected = [
    'ForgePDM_Login', 'ForgePDM_Logout', 'ForgePDM_Upload', 'ForgePDM_Checkout',
    'ForgePDM_CheckIn', 'ForgePDM_Release', 'ForgePDM_NewRevision',
    'ForgePDM_Download', 'ForgePDM_ShowBOM',
]
assert command_calls == wb.menu == wb.toolbar == expected
assert wb.GetClassName() == 'Gui::PythonWorkbench'
assert len(language_paths) == 1 and Path(language_paths[0]).is_dir()
expected_icons = ['login', 'logout', 'upload', 'checkout', 'checkin', 'release',
                  'new-revision', 'download', 'bom']
for command, icon in zip(registered.values(), expected_icons):
    resources = command.GetResources()
    assert resources['MenuText'] and resources['ToolTip']
    assert Path(resources['Pixmap']).is_file()
    assert Path(resources['Pixmap']).name == icon + '.svg'
assert registered['ForgePDM_Login'].IsActive()
assert not registered['ForgePDM_CheckIn'].IsActive()

from freecad.forgepdm import commands
class Metadata:
    def __init__(self): self.ViewObject = SimpleNamespace(Visibility=True)
    def addProperty(self, kind, name, group): setattr(self, name, '')
class Document:
    obj = None
    def getObject(self, name):
        assert name == 'ForgePDM_Metadata'
        return self.obj
    def addObject(self, kind, name):
        assert kind == 'App::FeaturePython' and name == 'ForgePDM_Metadata'
        self.obj = Metadata()
        return self.obj
document = Document()
obj = commands._set_metadata(document, ItemId='item', RevisionId='revision',
                             ItemNumber='P000001', RevisionLabel='A')
assert not obj.ViewObject.Visibility
assert commands._require_metadata(document) is obj
assert (obj.ItemId, obj.RevisionId, obj.ItemNumber, obj.RevisionLabel) == (
    'item', 'revision', 'P000001', 'A')
assert not {'forgepdm', 'sqlite3', 'fastapi'} & set(sys.modules)
"""


@pytest.mark.parametrize("binding", ["PySide", "PySide2", "PySide6"])
def test_loading_registration_and_metadata_from_archive(addon_tools, tmp_path, binding):
    archive = addon_tools.build(tmp_path / "addon.zip")
    installed = tmp_path / "Mod" / "ForgePDM"
    with ZipFile(archive) as zipped:
        zipped.extractall(installed)
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", SCRIPT, str(installed), binding],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr

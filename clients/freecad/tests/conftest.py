"""Addon tooling fixtures, independent of the backend and real FreeCAD."""

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def addon_tools():
    spec = importlib.util.spec_from_file_location("addon_tools", ROOT / "tools/addon.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def addon_root():
    return ROOT

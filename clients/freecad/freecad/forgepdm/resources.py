"""Resolve installed resources without relying on the working directory."""

from pathlib import Path


RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"


def icon_path():
    return str(RESOURCE_ROOT / "icons" / "forgepdm.svg")

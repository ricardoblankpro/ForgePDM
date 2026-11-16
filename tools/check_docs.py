"""Check repository Markdown, handoff metadata and portable validation paths."""

import argparse
import ast
import html
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^\)]+)\)")
SKIP = {
    ".git",
    ".venv",
    "var",
    "dist",
    "node_modules",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
}


def markdown_files(root):
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in SKIP]
        for name in sorted(files):
            if name.endswith(".md"):
                yield Path(directory) / name


def anchors(text):
    values, counts = set(), {}
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.MULTILINE):
        heading = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", heading)
        value = re.sub(r"[^\w\- ]", "", html.unescape(heading).lower()).replace(" ", "-")
        number = counts.get(value, 0)
        counts[value] = number + 1
        values.add(value + ("-" + str(number) if number else ""))
    values.update(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    return values


def link_errors(root):
    errors = []
    for path in markdown_files(root):
        text = path.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            target = match.group(1).strip()
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            target = target.removeprefix("<").removesuffix(">")
            destination, _, anchor = target.partition("#")
            destination = unquote(destination)
            resolved = (path.parent / destination).resolve() if destination else path.resolve()
            line = text.count("\n", 0, match.start()) + 1
            message = f"{path.relative_to(root)}:{line}: {target}"
            if not resolved.exists():
                errors.append("Missing link target: " + message)
            elif (
                anchor
                and resolved.suffix == ".md"
                and unquote(anchor) not in anchors(resolved.read_text())
            ):
                errors.append("Missing heading anchor: " + message)
    return errors


def version_errors(root):
    addon = root / "clients/freecad"
    project = tomllib.loads((addon / "pyproject.toml").read_text())["project"]
    manifest = ElementTree.parse(addon / "package.xml").getroot()
    version = manifest.findtext("{https://wiki.freecad.org/Package_Metadata}version")
    module = ast.parse((addon / "freecad/forgepdm/__init__.py").read_text())
    python_version = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    errors = []
    if not version == project["version"] == python_version:
        errors.append("Addon manifest, Python and package versions disagree")
    backend = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    tree = ast.parse((root / "src/forgepdm/infrastructure/database.py").read_text())
    migrations = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "MIGRATIONS" for t in node.targets)
    )
    schema = max(ast.literal_eval(node.elts[0]) for node in migrations.elts)
    status = (root / "DEVELOPMENT_STATUS.md").read_text()
    for label, value in [
        ("Addon", version),
        ("Backend package", backend),
        ("Database schema", schema),
    ]:
        if f"- {label}: **{value}**" not in status:
            errors.append(f"Current handoff does not declare {label} {value}")
    return errors


def portable_errors(root):
    errors = []
    for path in (root / "clients/freecad/tools/validation").glob("*.py"):
        if re.search(r"/home/[^/\"']+/", path.read_text()):
            errors.append("Personal home path in native harness: " + str(path.relative_to(root)))
    return errors


def check(root=ROOT):
    root = Path(root).resolve()
    return link_errors(root) + version_errors(root) + portable_errors(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = check(args.root)
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print("Documentation links/anchors, delivery metadata and portable harness paths pass")


if __name__ == "__main__":
    main()

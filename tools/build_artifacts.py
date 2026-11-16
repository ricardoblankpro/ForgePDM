"""Build reviewable backend/addon artifacts and SHA-256 checksums; never publish."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    addon = ROOT / "clients/freecad"
    addon_version = tomllib.loads((addon / "pyproject.toml").read_text())["project"]["version"]
    backend_version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    archive = addon / "dist" / f"ForgePDM-{addon_version}.zip"
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(addon),
            "--extra",
            "dev",
            "--locked",
            "python",
            str(addon / "tools/addon.py"),
            "build",
            "--output",
            str(archive),
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    destination = output / archive.name
    if destination != archive.resolve():
        shutil.copyfile(archive, destination)
    subprocess.run(["uv", "build", "--out-dir", str(output)], cwd=ROOT, check=True)
    files = [
        destination,
        output / f"forgepdm-{backend_version}-py3-none-any.whl",
        output / f"forgepdm-{backend_version}.tar.gz",
    ]
    lines = []
    for path in sorted(files):
        with path.open("rb") as stream:
            lines.append(hashlib.file_digest(stream, "sha256").hexdigest() + "  " + path.name)
    (output / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release")
    args = parser.parse_args()
    try:
        print(build(args.output))
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)


if __name__ == "__main__":
    main()

"""Review or install Linux user timers for ForgePDM backups and restore drills."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "# Managed by ForgePDM backup installer."


def quote(value, *, command=False):
    value = str(value)
    if any(character in value for character in "\n\r\x00"):
        raise ValueError("systemd paths must not contain line breaks or NUL")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if command:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def units(executable, database, files, backups, scratch):
    environment = "\n".join(
        "Environment=" + quote(key + "=" + str(value))
        for key, value in (("FORGEPDM_DATABASE", database), ("FORGEPDM_FILE_ROOT", files))
    )
    commands = {
        "forgepdm-backup": [executable, "backup-create", "--destination", backups],
        "forgepdm-restore-drill": [
            executable,
            "backup-drill",
            backups,
            "--latest",
            "--scratch-root",
            scratch,
        ],
    }
    result = {}
    for name, arguments in commands.items():
        description = (
            "ForgePDM verified backup"
            if name == "forgepdm-backup"
            else "ForgePDM isolated restore drill"
        )
        result[name + ".service"] = (
            f"{MARKER}\n[Unit]\nDescription={description}\n\n[Service]\nType=oneshot\n"
            f"{environment}\nUMask=0077\nNoNewPrivileges=yes\nNice=10\n"
            "IOSchedulingClass=best-effort\nIOSchedulingPriority=7\nTimeoutStartSec=15min\n"
            "ExecStart=" + " ".join(quote(arg, command=True) for arg in arguments) + "\n"
        )
        calendar = "hourly" if name == "forgepdm-backup" else "*-*-* 03:15:00"
        result[name + ".timer"] = (
            f"{MARKER}\n[Unit]\nDescription={description} schedule\n\n[Timer]\n"
            f"OnCalendar={calendar}\nPersistent=true\nRandomizedDelaySec=5min\n\n"
            "[Install]\nWantedBy=timers.target\n"
        )
    return result


def install(definitions, directory):
    directory.mkdir(parents=True, exist_ok=True)
    # Inspect every existing unit before changing any of them.
    for name in definitions:
        target = directory / name
        if target.is_symlink() or (target.exists() and MARKER not in target.read_text()):
            raise ValueError(f"refusing to replace an unmanaged systemd unit: {name}")
    for name, text in definitions.items():
        target = directory / name
        if target.exists():
            shutil.copyfile(target, directory / (name + ".previous"))
        descriptor, temporary = tempfile.mkstemp(prefix=".forgepdm-unit-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--files", type=Path, required=True)
    parser.add_argument("--backups", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--executable", type=Path, default=Path(sys.executable).parent / "forgepdm")
    parser.add_argument(
        "--install", action="store_true", help="install and enable the reviewed user timers"
    )
    args = parser.parse_args()
    values = [args.executable, args.database, args.files, args.backups, args.scratch]
    if any(p.is_symlink() for path in values for p in (path, *path.parents)):
        parser.error("symlinks are not supported")
    executable, database, files, backups, scratch = [Path(os.path.abspath(path)) for path in values]
    if not executable.is_file() or not os.access(executable, os.X_OK) or not database.is_file():
        parser.error("the installed forgepdm executable and existing database are required")
    for output in (backups, scratch):
        for source in (database, files):
            if output == source or output in source.parents or source in output.parents:
                parser.error("backup/drill directories must not overlap live data")
    if backups == scratch or backups in scratch.parents or scratch in backups.parents:
        parser.error("backup and drill directories must be separate")
    definitions = units(executable, database, files, backups, scratch)
    if not args.install:
        for name, text in definitions.items():
            print(f"# {name}\n{text}")
        return
    directory = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user"
    install(definitions, directory)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        [
            "systemctl",
            "--user",
            "enable",
            "--now",
            "forgepdm-backup.timer",
            "forgepdm-restore-drill.timer",
        ],
        check=True,
    )
    print("Hourly backup and daily isolated restore timers enabled; no live data was replaced.")


if __name__ == "__main__":
    main()

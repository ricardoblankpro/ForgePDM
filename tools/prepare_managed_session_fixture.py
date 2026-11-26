"""Create a disposable backend fixture for native managed-session acceptance."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if not directory.is_relative_to(Path("/tmp")) or (directory / "forgepdm.sqlite3").exists():
        parser.error("Use a fresh directory under /tmp; existing databases are never replaced")
    directory.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    import conftest

    backend = conftest.backend.__wrapped__(directory)
    items = {
        name: conftest.create_item(backend, kind="assembly", name=name)
        for name in ("source", "parent")
    }
    fixture = {
        name: dict(
            item_id=item.id,
            revision_id=item.current_revision_id,
            item_number=item.number,
            revision_label="A",
        )
        for name, item in items.items()
    }
    (directory / "fixture.json").write_text(json.dumps(fixture, indent=2))
    print("Disposable fixture prepared:", directory)


if __name__ == "__main__":
    main()

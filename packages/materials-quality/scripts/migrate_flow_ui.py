"""Copy an old Langflow JSON to native controls without overwriting either file."""

import argparse
import json
from pathlib import Path

from materials_quality.science.flow_migration import MigrationError, migrate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Existing saved Langflow JSON file")
    parser.add_argument("output", type=Path, nargs="?", help="New file; default <stem>.ui-v2.json")
    parser.add_argument(
        "--prefer-forms",
        action="store_true",
        help="Use native controls only where effective legacy parameters and connections are preserved",
    )
    args = parser.parse_args(argv)
    source = args.input.expanduser().resolve()
    destination = (args.output or source.with_name(source.stem + ".ui-v2.json")).expanduser().resolve()
    if destination.exists():
        parser.error(f"Output already exists; refusing to overwrite: {destination}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        updated, report = migrate(payload, prefer_forms=args.prefer_forms)
        serialized = json.dumps(updated, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        # Exclusive creation closes the existence-check/write race, including
        # another process creating the destination after validation.
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    except (OSError, ValueError, MigrationError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(destination), **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

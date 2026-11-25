"""Deterministic science-operation CLI for external agent engines (DSH, scripts).

Usage:
    python -m materials_quality.science_tools list
    python -m materials_quality.science_tools show materials.xrd
    python -m materials_quality.science_tools run materials.xrd \
        --config '{"baseline":{"method":"asls"}}' --table data.csv

The CLI is a thin, JSON-in/JSON-out wrapper over the same functions the
registered canvas components call. It exists so an external agent (for example
the DeepSeek Harness engine) can invoke StudyUI's deterministic science
operations instead of re-implementing them in generated code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAX_ROWS = 2000
MAX_ITEMS = 500


def _jsonable(value, depth=0):
    if depth > 6:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "data") and hasattr(value, "table") and hasattr(value, "warnings"):
        return {
            "data": _jsonable(getattr(value, "data", {}), depth + 1),
            "table": _jsonable(getattr(value, "table", None), depth + 1),
            "features": _jsonable(getattr(value, "features", None), depth + 1),
            "artifacts": _jsonable(getattr(value, "artifacts", []), depth + 1),
            "warnings": _jsonable(getattr(value, "warnings", []), depth + 1),
        }
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS]}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            flat = value.reshape(-1)[:MAX_ITEMS]
            return _jsonable(flat.tolist(), depth + 1)
        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            head = value.head(MAX_ROWS)
            return {
                "columns": [str(c) for c in head.columns],
                "rows": _jsonable(head.to_dict(orient="records"), depth + 1),
                "row_count": int(len(value)),
                "truncated": bool(len(value) > MAX_ROWS),
            }
        if isinstance(value, pd.Series):
            return _jsonable(value.head(MAX_ROWS).tolist(), depth + 1)
    except Exception:
        pass
    return str(value)


def _load_table(path: str):
    import pandas as pd

    p = Path(path).expanduser()
    if not p.is_file():
        raise SystemExit(f"table file not found: {p}")
    suffix = p.suffix.lower()
    if suffix in {".tsv", ".txt"} and suffix != ".csv":
        return pd.read_csv(p, sep="\t")
    return pd.read_csv(p)


def _parse_json_arg(text: str, flag: str):
    if text is None:
        return None
    candidate = Path(text)
    if candidate.is_file():
        return json.loads(candidate.read_text(encoding="utf-8"))
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag} is neither a JSON string nor an existing file: {exc}") from exc


def cmd_list(_args):
    from .science import catalog
    from .science.categories import category_label

    items = [
        {
            "key": item["key"],
            "title": item.get("title", ""),
            "category": item.get("category", ""),
            "category_label": item.get("category_label") or category_label(item.get("category", "")),
            "requirement": item.get("requirement", ""),
        }
        for item in catalog.entries()
    ]
    json.dump({"operations": items}, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


def cmd_show(args):
    from .science import catalog

    item = {k: v for k, v in catalog.get(args.operation).items() if k != "callable"}
    json.dump(item, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


def cmd_run(args):
    from .science import catalog

    item = catalog.get(args.operation)
    config = _parse_json_arg(args.config, "--config") or {}
    data = _parse_json_arg(args.data, "--data")
    if isinstance(config, dict) and args.table:
        config.setdefault("path", str(Path(args.table).expanduser().resolve()))
    table = _load_table(args.table) if args.table else None
    try:
        result = item["callable"](table, config=config, data=data)
    except TypeError:
        result = item["callable"](table, config=config)
    payload = {
        "operation": args.operation,
        "title": item.get("title", ""),
        "result": _jsonable(result),
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(prog="science_tools", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list registered science operations")
    p_show = sub.add_parser("show", help="show one operation's catalog entry")
    p_show.add_argument("operation")
    p_run = sub.add_parser("run", help="run one operation")
    p_run.add_argument("operation")
    p_run.add_argument("--config", help="JSON string or path to a JSON file")
    p_run.add_argument("--data", help="JSON string or path to a JSON file")
    p_run.add_argument("--table", help="CSV/TSV file loaded as the operation's table input")
    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "show":
        return cmd_show(args)
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())

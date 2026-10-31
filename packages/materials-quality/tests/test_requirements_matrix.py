import importlib
import json
from pathlib import Path

from scripts.build_requirements_matrix import build

ROOT = Path(__file__).resolve().parents[1]


def test_all_fifty_source_entries_and_submethods_have_implementations_and_evidence():
    rows = build()
    assert rows == json.loads((ROOT / "docs/requirements-matrix.json").read_text(encoding="utf-8"))
    assert [sum(r["category"] == i for r in rows) for i in range(1, 9)] == [6, 6, 6, 6, 6, 8, 6, 6]
    assert len({r["operation"] for r in rows}) == 50
    for row in rows:
        module, name = row["implementation"].split(":")
        assert callable(getattr(importlib.import_module(module), name))
        assert row["submethods"]
        assert (ROOT / row["method_manual"]).is_file()
        assert all((ROOT / f).is_file() for f in row["test_files"])

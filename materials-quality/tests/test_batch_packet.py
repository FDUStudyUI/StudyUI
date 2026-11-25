import json
from copy import deepcopy
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from materials_quality.batch.packet import (
    combined_table,
    is_batch,
    make_batch,
    make_item,
    pack_table,
    unpack_table,
    validate_batch,
)


def test_json_transport_preserves_precision_types_index_and_units():
    frame = pd.DataFrame(
        {
            "id": pd.Series(["001", "002", "003"], dtype="string"),
            "integer": pd.Series([2**60 + 3, pd.NA, -7], dtype="Int64"),
            "value": [np.nextafter(1.0, 2.0), np.inf, np.nan],
            "grade": pd.Categorical(["hi", "lo", None], categories=["lo", "hi"], ordered=True),
            "time": pd.to_datetime(["2026-01-01", None, "2026-02-01"], utc=True),
            "object": [Decimal("1.234567890123456789"), pd.NA, (1, "x")],
        }
    )
    frame.index = pd.MultiIndex.from_tuples([("a", 7), ("a", 9), ("b", 1)], names=["specimen", "point"])
    frame.attrs = {"units": {"value": "MPa"}, "note": "original"}
    transported = json.loads(json.dumps(pack_table(frame), allow_nan=False))
    restored = unpack_table(transported)
    assert_frame_equal(restored, frame)
    assert restored.attrs == frame.attrs


@pytest.mark.parametrize(
    "index",
    [
        pd.RangeIndex(3, 9, 2, name="position"),
        pd.DatetimeIndex(["2026-01-01", "2026-01-02", "2026-01-03"], name="date"),
        pd.CategoricalIndex(["a", "b", "a"], categories=["b", "a"], ordered=True, name="kind"),
    ],
)
def test_index_variants_roundtrip(index):
    frame = pd.DataFrame({"x": [1, 2, 3]}, index=index)
    assert_frame_equal(unpack_table(pack_table(frame)), frame)


def test_batch_counts_failures_and_preserves_identity_without_mutation():
    a = make_item("a", "A", {"source_name": "a.csv"}, pd.DataFrame({"x": [1]}))
    b = make_item("b", "B", {"source_name": "b.csv"})
    b.update(status="failed", error={"stage": "source", "message": "missing source"})
    batch = make_batch([a, b], batch_id="fixed", on_error="continue")
    assert batch["batch_id"] == "fixed"
    assert batch["counts"] == {"total": 2, "completed": 1, "failed": 1, "skipped": 0}
    assert batch["execution_status"] == "partial_failed"
    assert is_batch(batch)
    validate_batch(json.loads(json.dumps(batch, allow_nan=False)))
    batch["items"][0]["label"] = "changed"
    assert a["label"] == "A"
    assert make_batch([b])["execution_status"] == "failed"


def test_validation_rejects_duplicate_ids_bad_counts_and_malformed_tables():
    item = make_item("x", "X", {}, pd.DataFrame({"x": [1]}))
    with pytest.raises(ValueError, match="unique|duplicate"):
        make_batch([item, item])
    packet = make_batch([item])
    packet["counts"]["completed"] = 9
    with pytest.raises(ValueError, match="counts"):
        validate_batch(packet)
    table = pack_table(pd.DataFrame({"x": [1]}))
    table["data"][0][0] = ["__reduce__", "os.system"]
    with pytest.raises(ValueError):
        unpack_table(table)


def test_combined_table_includes_only_completed_items_and_checks_reserved_columns():
    item = make_item("001", "sample", {}, pd.DataFrame({"x": [1, 2]}))
    failed = make_item("002", "bad", {}, pd.DataFrame({"x": [999]}))
    failed.update(status="failed", error={"stage": "source", "message": "bad"})
    packet = make_batch([item, failed])
    combined = combined_table(packet)
    assert combined.to_dict("list") == {
        "x": [1, 2],
        "batch_item_id": ["001", "001"],
        "batch_label": ["sample", "sample"],
    }
    assert combined_table(make_batch([make_item("x", "x", {})])) is None
    trusted = deepcopy(item)
    trusted["table"] = pack_table(combined)
    assert len(combined_table(make_batch([trusted]))) == 2
    collision = make_item("other", "sample", {}, combined)
    with pytest.raises(ValueError, match="reserved|collision"):
        combined_table(make_batch([collision]))


def test_malformed_index_and_dtype_cannot_escape_decoder_validation():
    payload = pack_table(pd.DataFrame({"x": [1]}))
    payload["index"] = {"kind": "multi", "names": [["str", "bad"]], "levels": [None], "codes": [[0]]}
    with pytest.raises(ValueError):
        unpack_table(payload)


def test_file_style_extra_packet_fields_survive_validation():
    packet = make_batch([make_item("x", "X", {})])
    packet["rename_columns"] = {"old": "new"}
    packet["artifacts"] = ["summary.html"]
    assert validate_batch(packet)["rename_columns"] == {"old": "new"}

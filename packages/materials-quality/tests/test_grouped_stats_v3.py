import pandas as pd
import pytest

from materials_quality.science.grouped_stats import grouped_summary


def test_legacy_order_and_mixed_units():
    f = pd.DataFrame({"g": ["a", "a", "b"], "x": [1.0, 3, 5], "y": [10.0, 20, 40]})
    r = grouped_summary(f, {"group": "g", "columns": ["x", "y"], "units": {"x": "nm", "y": "s"}})
    assert list(r.table.columns)[:4] == ["g", "variable", "count", "mean"]
    assert r.table.iloc[0]["mean"] == 2
    assert r.table.unit.tolist() == ["nm", "s", "nm", "s"]
    assert set(r.table.attrs.get("units", {})) <= set(r.table.columns)
    assert set(r.data["units"]) <= set(r.table.columns)
    assert r.data["input_units"] == {"x": "nm", "y": "s"}


def test_conflicting_and_invalid_explicit_units():
    f = pd.DataFrame({"g": ["a", "a"], "x": [1.0, 2.0]})
    f.attrs["units"] = {"x": "nm"}
    with pytest.raises(ValueError, match="conflicting"):
        grouped_summary(f, {"group": "g", "column": "x", "units": {"x": "s"}})
    with pytest.raises(ValueError, match="existing"):
        grouped_summary(f, {"group": "g", "column": "x", "units": {"missing": "s"}})


def test_multikey_wide_normalization_and_units():
    f = pd.DataFrame({"g": ["a", "a", "b"], "h": [1, 1, 2], "x": [1.0, 3, 5]})
    r = grouped_summary(
        f, {"group_by": ["g", "h"], "columns": ["x"], "normalize_by_group": True, "output_format": "wide"}
    )
    assert list(r.table.x_mean) == pytest.approx([1, 1])
    assert r.data["normalization"] == "divide by within-group variable mean"

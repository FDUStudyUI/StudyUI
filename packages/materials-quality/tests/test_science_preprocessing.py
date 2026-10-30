import importlib

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


def api():
    return importlib.import_module("materials_quality.science.preprocessing")


def test_filter_select_rename_and_drop_empty_are_auditable():
    table = pd.DataFrame({"id": ["A", "B", None], "x": [1, 3, None], "unused": [0, 0, None]}, index=[8, 8, 9])
    original = table.copy(deep=True)
    result = api().filter_rows(
        table,
        config={
            "conditions": [{"column": "x", "op": "ge", "value": 2}],
            "columns": ["id", "x"],
            "rename": {"x": "stress"},
            "drop_empty": True,
        },
    )
    assert result.table.to_dict("records") == [{"id": "B", "stress": 3.0}]
    assert result.data["removed_positions"] == [0, 2]
    assert_frame_equal(table, original)


@pytest.mark.parametrize(
    "method,want", [("mean", 2), ("median", 2), ("mode", 1), ("ffill", 1), ("linear", 2)]
)
def test_missing_methods_fill_only_declared_cells(method, want):
    table = pd.DataFrame({"time": [0, 1, 2], "x": [1, -200, 3]})
    original = table.copy(deep=True)
    result = api().handle_missing(
        table,
        config={
            "columns": ["x"],
            "method": method,
            "missing_tokens": ["-200"],
            "order_by": "time",
            "continuous": True,
        },
    )
    assert result.table.x.iloc[1] == want
    assert result.data["changes"][0]["before"] == -200
    assert result.data["changes"][0]["row_position"] == 1
    assert_frame_equal(table, original)


def test_interpolation_requires_explicit_continuous_unique_coordinates():
    table = pd.DataFrame({"x": [1, None, 3], "t": [0, 0, 2]})
    with pytest.raises(ValueError, match="continuous"):
        api().handle_missing(table, config={"columns": ["x"], "method": "linear", "order_by": "t"})
    with pytest.raises(ValueError, match="unique"):
        api().handle_missing(
            table, config={"columns": ["x"], "method": "linear", "order_by": "t", "continuous": True}
        )


def test_missing_keep_drop_and_group_specific_mean():
    table = pd.DataFrame({"g": ["a", "a", "b", "b"], "x": [1, None, 100, None]})
    keep = api().handle_missing(table, config={"method": "keep", "columns": ["x"]})
    assert_frame_equal(keep.table, table)
    assert len(api().handle_missing(table, config={"method": "drop", "columns": ["x"]}).table) == 2
    filled = api().handle_missing(table, config={"method": "mean", "columns": ["x"], "group_by": ["g"]})
    assert filled.table.x.tolist() == [1, 1, 100, 100]


def test_unit_conversion_handles_temperature_offsets_and_mixed_inline_units():
    table = pd.DataFrame({"temperature": [0, 100], "stress": ["1 MPa", "1000 kPa"]})
    original = table.copy(deep=True)
    result = api().convert_units(
        table,
        config={
            "source_units": {"temperature": "degC"},
            "target_units": {"temperature": "K", "stress": "Pa"},
        },
    )
    assert result.table.temperature.tolist() == pytest.approx([273.15, 373.15])
    assert result.table.stress.tolist() == pytest.approx([1e6, 1e6])
    assert len(result.data["changes"]) == 4
    assert_frame_equal(table, original)


def test_incompatible_unit_conversion_fails_without_altering_input():
    table = pd.DataFrame({"x": ["1 MPa"]})
    with pytest.raises(ValueError, match="incompatible"):
        api().convert_units(table, config={"source_units": {}, "target_units": {"x": "K"}})


def test_wide_long_and_explicit_type_conversions():
    table = pd.DataFrame({"id": ["A"], "x": ["1"], "y": ["2"], "date": ["2026-10-30"]})
    typed = api().reshape_table(
        table,
        config={
            "method": "types",
            "types": {"x": "number", "date": "datetime"},
            "date_formats": {"date": "%Y-%m-%d"},
        },
    )
    assert typed.table.x.iloc[0] == 1
    assert pd.api.types.is_datetime64_any_dtype(typed.table.date)
    long = api().reshape_table(
        table, config={"method": "wide_to_long", "id_vars": ["id", "date"], "value_vars": ["x", "y"]}
    )
    assert long.table.variable.tolist() == ["x", "y"]
    wide = api().reshape_table(
        long.table,
        config={"method": "long_to_wide", "index": ["id", "date"], "columns": "variable", "values": "value"},
    )
    assert wide.table.x.iloc[0] == "1"
    assert wide.table.y.iloc[0] == "2"


def test_merge_exact_append_and_ordered_tolerance_match():
    a = pd.DataFrame({"id": ["A", "B"], "x": [1, 2]})
    b = pd.DataFrame({"id": ["B", "A"], "y": [20, 10]})
    joined = api().merge_tables(
        tables=[a, b], config={"method": "join", "on": ["id"], "validate": "one_to_one"}
    )
    assert joined.table.y.tolist() == [10, 20]
    assert len(api().merge_tables(tables=[a, a], config={"method": "append"}).table) == 4
    matched = api().merge_tables(
        tables=[pd.DataFrame({"t": [0.0, 1.0]}), pd.DataFrame({"t": [0.05, 1.4], "v": [1, 2]})],
        config={"method": "asof", "on": "t", "tolerance": 0.1, "direction": "nearest"},
    )
    assert matched.table.v.iloc[0] == 1 and pd.isna(matched.table.v.iloc[1])


@pytest.mark.parametrize(
    "method,want",
    [("minmax", [0, 0.5, 1]), ("zscore", [-np.sqrt(1.5), 0, np.sqrt(1.5)]), ("robust", [-1, 0, 1])],
)
def test_normalization_parameters_and_values(method, want):
    result = api().normalize_table(
        pd.DataFrame({"x": [1, 2, 3]}), config={"columns": ["x"], "method": method}
    )
    assert result.table.x.tolist() == pytest.approx(want)
    assert result.data["fit_parameters"]["x"]

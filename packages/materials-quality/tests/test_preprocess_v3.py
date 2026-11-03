import pandas as pd
import pytest

from materials_quality.science.preprocessing import filter_rows, merge_tables, normalize_table


def test_safe_formulas_preserve_units_and_evaluate_before_filter():
    f = pd.DataFrame({"x": [1.0, 2.0, 3.0], "t": [2.0, 2.0, 2.0]})
    f.attrs["units"] = {"x": "m", "t": "s"}
    r = filter_rows(
        f,
        config={
            "derived_columns": [
                {"column": "twice", "expression": "2*x", "unit": ""},
                {"column": "speed", "expression": "x/t", "unit": "m/s"},
            ],
            "conditions": [{"column": "twice", "op": "gt", "value": 2}],
        },
    )
    assert r.table.twice.tolist() == [4, 6]
    assert r.table.speed.tolist() == [1, 1.5]
    assert r.table.attrs["units"]["twice"] == "m"
    assert list(f) == ["x", "t"]
    assert r.data["input_columns"] == ["x", "t"]


@pytest.mark.parametrize(
    "expression", ["__import__('os').system('whoami')", "x.__class__", "x[0]", "[x for x in x]", "sum(x)"]
)
def test_formula_injection_rejected(expression):
    with pytest.raises(ValueError, match="formula"):
        filter_rows(
            pd.DataFrame({"x": [1.0, 2.0]}),
            config={"derived_columns": [{"column": "z", "expression": expression, "unit": "1"}]},
        )


def test_dimensional_formula_requires_explicit_compatible_unit():
    f = pd.DataFrame({"x": [1.0, 2.0], "t": [1.0, 2.0]})
    f.attrs["units"] = {"x": "m", "t": "s"}
    with pytest.raises(ValueError, match="unit"):
        filter_rows(f, config={"derived_columns": [{"column": "v", "expression": "x/t"}]})
    with pytest.raises(ValueError, match="unit"):
        filter_rows(f, config={"derived_columns": [{"column": "v", "expression": "x/t", "unit": "kg"}]})


@pytest.mark.parametrize(
    "method,expected",
    [
        ("minmax", [0.0, 1.0, 0.0, 1.0]),
        ("zscore", [-1.0, 1.0, -1.0, 1.0]),
        ("robust", [-1.0, 1.0, -1.0, 1.0]),
    ],
)
def test_group_normalization_isolated(method, expected):
    f = pd.DataFrame({"curve_id": ["a", "a", "b", "b"], "value": [1.0, 3.0, 100.0, 200.0]})
    r = normalize_table(f, config={"columns": ["value"], "group_by": ["curve_id"], "method": method})
    assert r.table.value.tolist() == pytest.approx(expected)
    assert len(r.data["fit_parameters_by_group"]) == 2
    assert r.data["fit_parameters_by_group"][1]["parameters"]["value"]["center"] >= 100
    assert f.value.tolist() == [1, 3, 100, 200]


def test_merge_source_provenance_rows():
    a = pd.DataFrame({"id": [1, 2], "x": [3, 4]})
    b = pd.DataFrame({"id": [2], "y": [5]})
    a.attrs["source_name"] = "left.csv"
    b.attrs["source_name"] = "right.csv"
    r = merge_tables(tables=[a, b], config={"on": ["id"], "how": "left"})
    assert r.data["input_table_rows"] == [2, 1]
    assert r.data["output_rows"] == 2
    assert r.data["sources"][0]["source_name"] == "left.csv"


def test_formula_and_group_normalization_native_controls():
    from materials_quality.science.ui_schema import science_inputs

    controls = {i.name: i for i in science_inputs("preprocess.filter", {})}
    derived = controls["cfg_derived_columns"]
    assert derived.__class__.__name__ == "TableInput"
    assert {column["name"] for column in derived.table_schema} == {"column", "expression", "unit"}
    controls = {i.name: i for i in science_inputs("preprocess.normalize", {"method": "minmax"})}
    assert controls["cfg_group_by"].__class__.__name__ == "MultiselectInput"
    assert controls["cfg_group_by"].is_list


def test_logarithm_converts_scaled_dimensionless_units_before_evaluation():
    import numpy as np
    import pandas as pd

    from materials_quality.science.preprocessing import filter_rows

    frame = pd.DataFrame({"x": [50.0, 100.0]})
    frame.attrs["units"] = {"x": "%"}
    result = filter_rows(
        frame,
        config={
            "derived_columns": [{"column": "ln_fraction", "expression": "log(x)", "unit": "dimensionless"}]
        },
    )
    assert result.table["ln_fraction"].tolist() == __import__("pytest").approx(np.log([0.5, 1.0]))

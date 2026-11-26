import importlib
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal


def api():
    return importlib.import_module("materials_quality.science.contracts")


def test_result_defaults_do_not_share_state():
    a, b = api().NodeResult(), api().NodeResult()
    a.warnings.append("review")
    assert not b.warnings
    assert a.table is None and a.data == {} and a.artifacts == []


def test_validated_tables_are_independent_copies():
    original = pd.DataFrame({"x": [1, 2]}, index=[5, 5])
    before = original.copy(deep=True)
    out = api().require_table(original, ["x"], min_rows=2)
    out.iloc[0, 0] = 3
    assert_frame_equal(original, before)
    with pytest.raises(ValueError):
        api().require_table(original, ["unknown"])
    with pytest.raises(ValueError):
        api().numeric_matrix(pd.DataFrame({"x": [1, "bad"]}), ["x"])


def test_artifacts_have_real_output_directories_and_inputs_must_exist(tmp_path):
    output = api().artifact_path({"output_dir": str(tmp_path / "out")}, "figure.png")
    assert isinstance(output, Path) and output.parent.is_dir()
    source = tmp_path / "data.csv"
    source.write_text("x\n1\n", encoding="utf-8")
    assert api().read_path({"path": str(source)}) == source.resolve()
    assert api().read_path({}, {"file_path": str(source)}) == source.resolve()
    with pytest.raises(ValueError):
        api().read_path({"path": str(tmp_path / "absent")})

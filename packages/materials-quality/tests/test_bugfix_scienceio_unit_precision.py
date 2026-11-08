"""Unit conversion must not silently round exact integers through binary floats."""

import pandas as pd
import pytest

from materials_quality.science.io_nodes import table_import
from materials_quality.science.preprocessing import convert_units


def test_unit_conversion_refuses_to_round_large_exact_integer(tmp_path):
    path = tmp_path / "stress.csv"
    path.write_text("stress\n9007199254740993\n", encoding="utf-8")
    table = table_import(config={"path": str(path)}).table

    with pytest.raises(ValueError, match="precision"):
        convert_units(table, config={"source_units": {"stress": "Pa"}, "target_units": {"stress": "Pa"}})


def test_representable_integers_and_fractions_still_convert():
    table = pd.DataFrame({"temperature": [0.0, 100.0, 1.5]})

    result = convert_units(
        table, config={"source_units": {"temperature": "degC"}, "target_units": {"temperature": "K"}}
    )

    assert result.table["temperature"].tolist() == pytest.approx([273.15, 373.15, 274.65])
    assert len(result.data["changes"]) == 3


def test_unit_conversion_reports_inline_quantity_precision_loss_too():
    table = pd.DataFrame({"stress": ["9007199254740993 Pa"]})

    with pytest.raises(ValueError, match="precision"):
        convert_units(table, config={"source_units": {}, "target_units": {"stress": "MPa"}})

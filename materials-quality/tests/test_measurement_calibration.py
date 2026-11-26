import numpy as np
import pandas as pd
import pytest

from materials_quality.context import table_fingerprint
from materials_quality.science.preprocessing import normalize_table
from materials_quality.science.table_contract import attach_contract, make_contract, read_contract


def config(method, **options):
    return {
        "method": method,
        "calibration_signal": "signal",
        "calibration_output": "corrected",
        "calibration_input_unit": "mV",
        "calibration_source": "synthetic reference certificate",
        **options,
    }


def test_blank_preserves_source_and_records_repeatability():
    source = pd.DataFrame({"sample": ["001", "001", "002"], "signal": [3, 5, 6]})
    source.attrs["units"] = {"signal": "mV"}
    before = table_fingerprint(source)
    result = normalize_table(
        source,
        config=config("blank_subtract", calibration_blank=1, group_by=["sample"]),
    )
    assert table_fingerprint(source) == before
    assert result.table["corrected"].tolist() == [2, 4, 5]
    assert result.table.attrs["units"]["corrected"] == "mV"
    first, second = result.data["repeatability_by_group"]
    assert first["n"] == 2 and first["sd"] == pytest.approx(np.sqrt(2))
    assert second["n"] == 1 and second["sd"] is None
    assert result.data["calibration"]["input_sha256"] == before


def test_reference_ratio_uses_same_row_reference_and_rejects_zero_and_conflict():
    source = pd.DataFrame({"signal": [3, 5], "reference": [5, 9]})
    c = config("reference_ratio", calibration_blank=1, calibration_reference_column="reference")
    result = normalize_table(source, config=c)
    assert result.table["corrected"].tolist() == [0.5, 0.5]
    assert result.table.attrs["units"]["corrected"] == "dimensionless"
    source.attrs["units"] = {"reference": "A"}
    with pytest.raises(ValueError, match="conflicting units"):
        normalize_table(source, config=c)
    source.attrs.clear()
    source.loc[1, "reference"] = 1
    with pytest.raises(ValueError, match="zero"):
        normalize_table(source, config=c)


def test_linear_standards_preserve_contract_and_refuse_extrapolation():
    source = pd.DataFrame({"signal": [0.5, 1.5], "sample_id": ["001", "002"]})
    source.attrs["units"] = {"signal": "mV"}
    source = attach_contract(
        source,
        make_contract(
            source,
            granularity="sample",
            roles={"sample_id": "sample_id", "response": "signal"},
        ),
    )
    c = config(
        "linear_calibration", calibration_standards=[[0, 1], [1, 3], [2, 5]], calibration_output_unit="MPa"
    )
    result = normalize_table(source, config=c)
    assert result.table["corrected"].tolist() == pytest.approx([2, 4])
    assert result.data["calibration"]["fit"]["slope"] == pytest.approx(2)
    assert read_contract(result.table)["granularity"] == "sample"
    assert read_contract(result.table)["units_state"]["units"]["corrected"] == "MPa"
    outside = source.copy()
    outside.loc[0, "signal"] = 3
    with pytest.raises(ValueError, match="outside"):
        normalize_table(outside, config=c)
    allowed = normalize_table(outside, config={**c, "calibration_allow_extrapolation": True})
    assert allowed.data["calibration"]["fit"]["extrapolated_rows"] == 1
    assert allowed.warnings


@pytest.mark.parametrize(
    "options",
    [
        {"calibration_output": "signal"},
        {"calibration_source": ""},
        {"calibration_blank": float("inf")},
    ],
)
def test_rejects_untraceable_or_destructive_calibration(options):
    with pytest.raises(ValueError):
        normalize_table(pd.DataFrame({"signal": [1, 2]}), config=config("blank_subtract", **options))

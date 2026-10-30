import json
from pathlib import Path

import pandas as pd
import pytest
from lfx.schema import DataFrame
from openpyxl import load_workbook

from components.materials_preprocessing.preprocess_units import SciencePreprocessUnits
from components.materials_visualization.export_table import ScienceExportTable
from materials_quality.science.preprocessing import convert_units, filter_rows, normalize_table
from materials_quality.science.visualization import export_table


def sample(table_type=pd.DataFrame):
    table = table_type({"stress": [1, 2], "temp": [20, 25], "length": [0.5, 1.0]})
    table.attrs["units"] = {"stress": "MPa", "temp": "degC", "length": "mm"}
    return table


def test_conversion_filter_normalization_keep_units_in_sync():
    original = sample()
    converted = convert_units(
        original, config={"source_units": {"stress": "MPa"}, "target_units": {"stress": "kPa"}}
    )
    assert converted.table.stress.tolist() == [1000, 2000]
    assert (
        converted.table.attrs["units"]
        == converted.data["units"]
        == {
            "stress": "kPa",
            "temp": "degC",
            "length": "mm",
        }
    )
    assert original.attrs["units"]["stress"] == "MPa"
    kept = filter_rows(
        converted.table, config={"columns": ["stress", "temp"], "rename": {"stress": "strength"}}
    )
    assert kept.table.attrs["units"] == kept.data["units"] == {"strength": "kPa", "temp": "degC"}
    scaled = normalize_table(kept.table, config={"columns": ["strength"], "method": "zscore"})
    assert (
        scaled.table.attrs["units"] == scaled.data["units"] == {"strength": "dimensionless", "temp": "degC"}
    )
    assert kept.table.attrs["units"]["strength"] == "kPa"


def test_conversion_uses_input_unit_and_rejects_contradictions():
    frame = sample()
    with pytest.raises(ValueError, match="conflict"):
        convert_units(frame, config={"source_units": {"stress": "Pa"}, "target_units": {"stress": "kPa"}})
    result = convert_units(frame, config={"target_units": {"stress": "kPa"}})
    assert result.table.stress.tolist() == [1000, 2000]


@pytest.mark.parametrize("fmt", ["csv", "excel"])
def test_united_metadata_on_disk(fmt, tmp_path):
    frame = sample()
    frame.attrs["units"] = {"stress": "MPa"}
    result = export_table(
        frame,
        data={"units": {"temp": "degC"}},
        config={"format": fmt, "units": {"length": "mm"}, "output_dir": str(tmp_path)},
    )
    units = {"stress": "MPa", "temp": "degC", "length": "mm"}
    assert result.table.attrs["units"] == units
    assert json.loads(Path(result.data["metadata_path"]).read_text(encoding="utf-8"))["units"] == units
    if fmt == "excel":
        wb = load_workbook(result.data["file_path"], read_only=True)
        try:
            assert {field: unit for field, unit, _ in list(wb["Metadata"].values)[1:]} == units
            assert list(wb["Results"].values)[1][0] == 1
        finally:
            wb.close()
    else:
        assert pd.read_csv(result.data["file_path"]).stress.tolist() == [1, 2]


@pytest.mark.parametrize("sources", [("attrs", "config"), ("data", "config"), ("data", "attrs")])
def test_conflicting_units_rejected_before_export(sources, tmp_path):
    frame = pd.DataFrame({"x": [1]})
    declarations = dict(zip(sources, [{"x": "MPa"}, {"x": "kPa"}], strict=True))
    frame.attrs["units"] = declarations.get("attrs", {})
    with pytest.raises(ValueError, match="conflict"):
        export_table(
            frame,
            config={"units": declarations.get("config", {}), "output_dir": str(tmp_path)},
            data={"units": declarations.get("data", {})},
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("connect_report", [False, True])
def test_native_units_to_export_roundtrip(connect_report, tmp_path):
    frame = sample(DataFrame)
    converter = SciencePreprocessUnits().set(
        input_table=frame,
        config_json=json.dumps(
            {
                "source_units": {"stress": "MPa"},
                "target_units": {"stress": "kPa"},
            }
        ),
    )
    table = converter.build_table()
    node = ScienceExportTable().set(input_table=table, config_json=json.dumps({"output_dir": str(tmp_path)}))
    if connect_report:
        node.set(input_data=converter.build_report())
    exported = node.build_report().data["data"]
    units = json.loads(Path(exported["metadata_path"]).read_text(encoding="utf-8"))["units"]
    assert units == {"stress": "kPa", "temp": "degC", "length": "mm"}
    assert pd.read_csv(exported["file_path"]).stress.tolist() == [1000, 2000]


def test_excel_does_not_silently_round_large_integer(tmp_path):
    frame = pd.DataFrame({"value": pd.array([9007199254740993], dtype="Int64")})
    with pytest.raises(ValueError, match="15 digits|15-digit"):
        export_table(frame, config={"format": "excel", "output_dir": str(tmp_path)})
    assert not list(tmp_path.iterdir())
    result = export_table(frame, config={"format": "csv", "output_dir": str(tmp_path)})
    assert pd.read_csv(result.data["file_path"]).value.tolist() == [9007199254740993]


def test_excel_readback_detects_one_integer_unit_difference(tmp_path, monkeypatch):
    import openpyxl

    def corrupt(path, **kwargs):
        book = load_workbook(path)
        book["Results"]["A2"] = 100000000000001
        return book

    monkeypatch.setattr(openpyxl, "load_workbook", corrupt)
    with pytest.raises(ValueError, match="integer"):
        export_table(
            pd.DataFrame({"value": [100000000000000]}),
            config={"format": "excel", "output_dir": str(tmp_path)},
        )

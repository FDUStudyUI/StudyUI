"""Declarative ingestion/extraction/preprocessing forms match actual algorithms."""

import importlib
import json

import pytest

from materials_quality.science.catalog import entries


def schemas():
    modules = [
        importlib.import_module(f"materials_quality.science.ui_specs_{name}")
        for name in ("io", "preprocessing")
    ]
    return (
        {key: spec for module in modules for key, spec in module.SPECS.items()},
        {key: contract for module in modules for key, contract in module.CONTRACTS.items()},
    )


def fields(key):
    return {item["path"]: item for item in schemas()[0][key]}


def test_all_eighteen_operations_have_unique_serializable_native_fields_and_contracts():
    specs, contracts = schemas()
    expected = {
        item["key"] for item in entries() if item["key"].startswith(("io.", "extract.", "preprocess."))
    }
    assert len(expected) == 18
    assert set(specs) == set(contracts) == expected
    json.dumps([specs, contracts], allow_nan=False)
    for key, spec in specs.items():
        assert spec and len({item["path"] for item in spec}) == len(spec), key
        for item in spec:
            assert item["label"] and item["info"], (key, item)
            assert item["kind"] != "json" or item["advanced"], (key, item)
        for name in ("table_output", "artifacts_output"):
            assert type(contracts[key][name]) is bool
        assert isinstance(contracts[key]["upload_types"], list)
        assert contracts[key]["icon"]


def test_csv_and_excel_header_sheet_and_schema_are_native():
    form = fields("io.table_import")
    assert {
        "path",
        "header",
        "sheet",
        "encoding",
        "delimiter",
        "decimal_separator",
        "range",
        "names",
        "id_columns",
        "dtype",
    } <= form.keys()
    assert form["sheet"]["converter"] == "number_or_text"
    assert form["header"]["converter"] == "nullable_int"
    assert form["dtype"]["kind"] == "dict"
    assert form["id_columns"]["kind"] == "list"
    assert form["decimal_separator"]["choices"] == [".", ","]
    assert form["encoding"]["choices"].count("cp1252") == 1
    assert all(control["kind"] != "json" for control in form.values())
    text = fields("io.text_import")
    assert set(text["method"]["choices"]) == {"lines", "delimited", "fixed_width"}
    assert text["widths"]["converter"] == "int_list"
    assert text["widths"]["when"] == {"method": ["fixed_width"]}
    assert text["header"]["when"] == {"method": ["delimited"]}


def test_database_method_and_readonly_query_have_native_controls():
    form = fields("io.database_import")
    assert set(form["method"]["choices"]) == {"sqlite", "sqlalchemy", "rest"}
    assert form["path"]["when"] == {"method": ["sqlite"]}
    assert form["query"]["when"] == {"method": ["sqlite", "sqlalchemy"]}
    assert "SELECT" in form["query"]["info"]
    assert form["parameters"]["kind"] == "dict"
    assert set(form["pagination.mode"]["choices"]) == {"page", "offset", "next", "none"}
    assert form["pagination.page_size"]["when"]["method"] == ["rest"]
    assert form["headers"]["advanced"]


def test_calibration_and_ocr_use_numeric_or_editable_tables():
    chart = fields("extract.chart_digitize")
    for axis in ("x", "y"):
        control = chart[f"calibration.{axis}"]
        assert control["required"] and control["kind"] == "table"
        assert control["converter"] == "pairs"
        assert control["pair_columns"] == ["pixel", "value"]
        assert {column["type"] for column in control["table_schema"]} == {"float"}
        assert chart[f"calibration.{axis}_scale"]["choices"] == ["linear", "log"]
    assert chart["color"]["converter"] == "int_list"
    assert chart["region"]["converter"] == "int_list"
    ocr = fields("extract.image_ocr")
    assert ocr["regions"]["kind"] == "table"
    assert ocr["regions"]["converter"] == "rectangles"
    assert ocr["text_score"]["default"] == ocr["box_thresh"]["default"] == 0.5
    assert fields("extract.pdf_tables")["region"]["converter"] == "float_list"
    assert fields("extract.image_tables")["header"]["kind"] == "bool"


def test_filter_units_and_reshape_support_normal_work_without_json():
    filter_form = fields("preprocess.filter")
    assert filter_form["conditions"]["kind"] == "table"
    assert filter_form["conditions"]["converter"] == "filter_conditions"
    assert [c["name"] for c in filter_form["conditions"]["table_schema"]] == ["column", "op", "value"]
    assert "not_in" in filter_form["conditions"]["info"]
    assert filter_form["rename"]["kind"] == "dict"
    units = fields("preprocess.units")
    assert units["source_units"]["kind"] == units["target_units"]["kind"] == "dict"
    reshape = fields("preprocess.reshape")
    assert set(reshape["method"]["choices"]) == {"types", "wide_to_long", "long_to_wide"}
    assert reshape["types"]["kind"] == reshape["date_formats"]["kind"] == "dict"
    assert reshape["categories"]["converter"] == "list_mapping"
    assert reshape["values"]["when"] == {"method": ["long_to_wide"]}


def test_missing_merge_and_normalize_only_offer_supported_methods():
    missing = fields("preprocess.missing")
    assert set(missing["method"]["choices"]) == {"keep", "drop", "mean", "median", "mode", "ffill", "linear"}
    assert missing["continuous"]["when"] == {"method": ["linear"]}
    assert missing["continuous"]["default"] is False
    assert missing["order_by"]["when"] == {"method": ["ffill", "linear"]}
    merge = fields("preprocess.merge")
    assert set(merge["method"]["choices"]) == {"join", "append", "asof", "specimen"}
    assert merge["on"]["converter"] == "column_or_list"
    assert merge["tolerance"]["converter"] == "number_or_text"
    assert merge["tolerance"]["when"] == {"method": ["asof"]}
    assert merge["validate"]["default"] == "one_to_one"
    normalize = fields("preprocess.normalize")
    assert set(normalize["method"]["choices"]) == {
        "minmax",
        "zscore",
        "robust",
        "blank_subtract",
        "reference_ratio",
        "linear_calibration",
    }
    assert normalize["calibration_standards"]["kind"] == "table"
    assert normalize["calibration_standards"]["converter"] == "pairs"
    assert normalize["calibration_allow_extrapolation"]["default"] is False


def test_ports_distinguish_real_empty_frames_from_absent_tables_and_exact_uploads():
    _, contracts = schemas()
    absent = {"io.pdf_import", "io.image_import"}
    artifacts = {
        "io.pdf_import",
        "io.instrument_import",
        "extract.pdf_text",
        "extract.pdf_tables",
        "extract.convert_file",
    }
    for key, contract in contracts.items():
        assert contract["table_output"] == (key not in absent), key
        assert contract["artifacts_output"] == (key in artifacts), key
        assert bool(contract["upload_types"]) == (not key.startswith("preprocess.")), key
    assert contracts["io.pdf_import"]["upload_types"] == ["pdf"]
    assert contracts["io.database_import"]["upload_types"] == ["db", "sqlite", "sqlite3"]
    assert "gif" in contracts["io.image_import"]["upload_types"]
    assert "gif" not in contracts["extract.convert_file"]["upload_types"]
    conversion = contracts["extract.convert_file"]
    assert conversion["method_path"] == "target"
    assert conversion["table_methods"] == ["csv", "txt"]
    merge = next(item for item in entries() if item["key"] == "preprocess.merge")
    assert merge["tables_input"] is True and merge["table_input"] is True


def test_specimen_merge_runs_using_native_master_port_and_form_fields():
    from lfx.schema import DataFrame

    from materials_quality.science.catalog import component_class

    node = component_class("preprocess.merge")().set(
        input_table=DataFrame({"lot": ["X", "Y"], "id": ["01", "01"]}),
        input_tables=[DataFrame({"lot": ["Y"], "id": ["01"], "peak": [550]})],
        cfg_method="specimen",
        cfg_on=["lot", "id"],
        cfg_allow_undeclared_features=True,
        cfg_unmatched="report",
    )
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["input_table"]["show"] is True
    assert template["cfg_unmatched"]["show"] is True
    assert template["cfg_validate"]["show"] is False
    assert node.build_table()["peak"].dropna().tolist() == [550]
    report = node.build_report().data
    assert report["data"]["association"]["features"][0]["missing_master_rows"] == 1
    assert report["table_preview"]["total_rows"] == 2


@pytest.mark.parametrize(
    "key",
    [
        "extract.pdf_text",
        "extract.pdf_tables",
        "extract.image_ocr",
        "extract.image_tables",
        "extract.chart_digitize",
    ],
)
def test_extraction_ordinary_parameters_never_require_whole_json(key):
    assert all(item["kind"] != "json" for item in schemas()[0][key])

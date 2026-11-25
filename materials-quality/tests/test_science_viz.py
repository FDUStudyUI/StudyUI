"""Figures carry numerical plot data; exports are read back without losing identifiers."""

import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image


def api():
    return importlib.import_module("materials_quality.science.visualization")


def verify(r):
    image = Image.open(r.artifacts[0]).convert("RGB")
    assert image.width >= 500 and image.height >= 300
    assert np.asarray(image).std() > 10
    json.dumps(r.data, allow_nan=False)


@pytest.mark.parametrize("method", ["scatter", "bar", "box", "violin"])
def test_performance_plots_expose_actual_groups_and_observations(tmp_path, method):
    t = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 4, "x": range(8), "y": [1, 2, 3, 4, 4, 5, 6, 7]})
    r = api().performance(
        t,
        config={
            "method": method,
            "x": "x",
            "y": "y",
            "group": "g",
            "units": {"y": "MPa"},
            "output_dir": str(tmp_path),
        },
    )
    verify(r)
    assert r.data["plot_data"]["groups"][0]["n"] == 4
    assert r.data["labels"]["y"] == "y (MPa)"


@pytest.mark.parametrize("method", ["line", "overlay", "difference"])
def test_spectra_difference_and_peak_labels_are_numeric(tmp_path, method):
    t = pd.DataFrame({"x": [1, 2, 3, 4], "a": [1, 4, 1, 0], "b": [0, 1, 1, 0]})
    r = api().spectra(
        t,
        config={
            "x": "x",
            "columns": ["a", "b"],
            "method": method,
            "peaks": [{"x": 2, "label": "peak"}],
            "output_dir": str(tmp_path),
        },
    )
    verify(r)
    if method == "difference":
        assert r.data["plot_data"]["curves"][0]["y"] == [1, 3, 0, 0]
    assert r.data["plot_data"]["peaks"][0]["x"] == 2


@pytest.mark.parametrize("method", ["overlay", "mean_error"])
def test_mechanics_mean_and_sample_std_errorband(tmp_path, method):
    t = pd.DataFrame(
        {
            "strain": [0, 1, 2] * 2,
            "stress": [0, 2, 4, 0, 4, 8],
            "sample": ["a"] * 3 + ["b"] * 3,
            "group": ["g"] * 6,
        }
    )
    r = api().mechanics(
        t,
        config={
            "method": method,
            "x": "strain",
            "y": "stress",
            "sample": "sample",
            "group": "group",
            "output_dir": str(tmp_path),
        },
    )
    verify(r)
    if method == "mean_error":
        assert r.data["plot_data"]["curves"][0]["y"] == [0, 3, 6]
        assert r.data["plot_data"]["curves"][0]["error"][1] == pytest.approx(2**0.5)


@pytest.mark.parametrize("method", ["histogram", "correlation", "residual", "prediction"])
def test_statistical_figures_validate_values(tmp_path, method):
    t = pd.DataFrame({"y": [1, 2, 3, 4], "p": [1, 3, 2, 5]})
    r = api().statistics_plot(
        t,
        config={
            "method": method,
            "column": "y",
            "columns": ["y", "p"],
            "y_true": "y",
            "y_pred": "p",
            "output_dir": str(tmp_path),
        },
    )
    verify(r)
    if method == "residual":
        assert r.data["plot_data"]["residual"] == [0, -1, 1, -1]


@pytest.mark.parametrize("format", ["csv", "excel"])
def test_export_roundtrips_leading_zero_ids_units_and_formula_text(tmp_path, format):
    t = pd.DataFrame({"id": ["001", "002"], "stress": [1.5, 2.5], "note": ["=1+1", "<script>x</script>"]})
    r = api().export_table(
        t,
        config={
            "format": format,
            "id_columns": ["id"],
            "units": {"stress": "MPa"},
            "output_dir": str(tmp_path),
        },
    )
    assert r.data["verified"] is True
    meta = json.loads(Path(r.data["metadata_path"]).read_text(encoding="utf-8"))
    assert meta["units"] == {"stress": "MPa"} and meta["id_columns"] == ["id"]
    if format == "csv":
        back = pd.read_csv(r.data["file_path"], dtype={"id": str})
    else:
        back = pd.read_excel(r.data["file_path"], dtype={"id": str})
    assert back.id.tolist() == ["001", "002"]
    assert back.stress.tolist() == [1.5, 2.5]
    assert back.note.iloc[0] == "=1+1"


def test_report_embeds_verified_figure_and_escapes_untrusted_html(tmp_path):
    fig = api().performance(
        pd.DataFrame({"x": [1, 2], "y": [2, 4]}), config={"x": "x", "y": "y", "output_dir": str(tmp_path)}
    )
    r = api().export_report(
        pd.DataFrame({"result": [2]}),
        config={"output_dir": str(tmp_path)},
        data={
            "title": "<script>evil()</script>",
            "sources": ["raw.csv"],
            "parameters": {"alpha": 0.05},
            "results": {"mean": 2},
            "figures": [fig.artifacts[0]],
            "warnings": ["review assumption"],
        },
    )
    body = Path(r.data["file_path"]).read_text(encoding="utf-8")
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "data:image/png;base64," in body
    assert all(x in body for x in ["raw.csv", "alpha", "mean", "review assumption"])
    assert r.data["embedded_figures_verified"] == 1


def test_plot_and_export_reject_malformed_science_inputs(tmp_path):
    with pytest.raises(ValueError):
        api().spectra(pd.DataFrame({"x": [2, 1, 1], "y": [1, 2, 3]}), config={"x": "x", "columns": ["y"]})
    with pytest.raises(ValueError):
        api().performance(pd.DataFrame({"x": [1], "y": [np.inf]}), config={"x": "x", "y": "y"})
    raw = tmp_path / "raw.csv"
    raw.write_text("x\n1\n", encoding="utf-8")
    r = api().export_table(
        pd.DataFrame({"x": [2]}), config={"output_dir": str(tmp_path), "filename": "raw.csv"}
    )
    assert raw.read_text(encoding="utf-8") == "x\n1\n"
    assert Path(r.data["file_path"]) != raw


def test_markdown_report_embeds_image_and_escapes_raw_html(tmp_path):
    fig = api().performance(
        pd.DataFrame({"x": [1, 2], "y": [2, 3]}), config={"x": "x", "y": "y", "output_dir": str(tmp_path)}
    )
    report = api().export_report(
        pd.DataFrame({"unsafe": ["<script>x</script>"]}),
        config={"format": "markdown", "output_dir": str(tmp_path)},
        data={"title": "[bad](javascript:x)", "figures": [fig.artifacts[0]]},
    )
    body = Path(report.data["file_path"]).read_text(encoding="utf-8")
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "data:image/png;base64," in body


def test_mechanics_explicit_grid_interpolation_and_sem(tmp_path):
    t = pd.DataFrame({"x": [0, 1, 2, 0, 0.5, 2], "y": [0, 2, 4, 0, 2, 8], "id": ["a"] * 3 + ["b"] * 3})
    c = {"x": "x", "y": "y", "sample": "id", "method": "mean_error", "output_dir": str(tmp_path)}
    with pytest.raises(ValueError, match="grid"):
        api().mechanics(t, config=c)
    r = api().mechanics(t, config={**c, "grid": [0, 1, 2], "error": "sem"})
    assert r.data["plot_data"]["curves"][0]["y"] == [0, 3, 6]
    assert r.data["plot_data"]["curves"][0]["error"] == pytest.approx([0, 1, 2])
    with pytest.raises(ValueError, match="range|extrapolation"):
        api().mechanics(t, config={**c, "grid": [-1, 0, 1]})


def test_png_svg_pdf_exports_and_exact_histogram_counts(tmp_path):
    r = api().statistics_plot(
        pd.DataFrame({"x": [0, 0, 1, 2, 3, 3]}),
        config={
            "method": "histogram",
            "column": "x",
            "bins": [0, 1, 2, 3],
            "formats": ["png", "svg", "pdf"],
            "output_dir": str(tmp_path),
        },
    )
    assert r.data["plot_data"]["count"] == [2, 1, 3]
    assert Path(r.artifacts[1]).read_text(encoding="utf-8").find("<svg") >= 0
    import fitz

    with fitz.open(r.artifacts[2]) as pdf:
        assert len(pdf) == 1 and pdf[0].get_pixmap().width > 300


def test_exports_empty_tables_and_missing_values(tmp_path):
    t = pd.DataFrame({"id": ["001", "NA"], "v": [1.0, np.nan], "text": ["", None]})
    for format in ["csv", "excel"]:
        r = api().export_table(
            t, config={"format": format, "output_dir": str(tmp_path), "id_columns": ["id"]}
        )
        assert r.data["verified"]
        empty = api().export_table(
            t.iloc[:0], config={"format": format, "output_dir": str(tmp_path), "id_columns": ["id"]}
        )
        assert empty.data["verified"]


def test_excel_headers_and_metadata_formula_text_are_real_strings_on_disk(tmp_path):
    from openpyxl import load_workbook

    t = pd.DataFrame({"=1+1": ["=3+3"], "id": ["001"]})
    result = api().export_table(
        t, config={"format": "excel", "output_dir": str(tmp_path), "units": {"=1+1": "=2+2"}}
    )
    book = load_workbook(result.data["file_path"], data_only=False)
    for sheet, position, expected in [
        ("Results", "A1", "=1+1"),
        ("Results", "A2", "=3+3"),
        ("Metadata", "A2", "=1+1"),
        ("Metadata", "B2", "=2+2"),
    ]:
        assert book[sheet][position].value == expected
        assert book[sheet][position].data_type == "s"
    assert all(cell.data_type != "f" for sheet in book for row in sheet for cell in row)
    book.close()


@pytest.mark.parametrize("dtype", [object, "string"])
def test_csv_preserves_undeclared_text_columns_and_records_reopen_schema(tmp_path, dtype):
    t = pd.DataFrame({"note": pd.Series(["001", "002"], dtype=dtype), "v": [1, 2]})
    result = api().export_table(t, config={"output_dir": str(tmp_path)})
    metadata = json.loads(Path(result.data["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["csv_readback"]["dtype"] == {"note": "str"}
    reopened = pd.read_csv(result.data["file_path"], **metadata["csv_readback"])
    assert reopened.note.tolist() == ["001", "002"]
    assert reopened.v.tolist() == [1, 2]


def test_mechanics_explicit_grid_applies_even_when_measured_grids_match(tmp_path):
    t = pd.DataFrame({"x": [0, 1, 2] * 2, "y": [0, 2, 4, 0, 4, 8], "sample": ["a"] * 3 + ["b"] * 3})
    config = {
        "method": "mean_error",
        "x": "x",
        "y": "y",
        "sample": "sample",
        "grid": [0, 0.5, 1],
        "output_dir": str(tmp_path),
    }
    result = api().mechanics(t, config=config)
    curve = result.data["plot_data"]["curves"][0]
    assert curve["x"] == [0, 0.5, 1] and curve["y"] == [0, 1.5, 3]
    with pytest.raises(ValueError, match="extrapolation|range"):
        api().mechanics(t, config={**config, "grid": [-1, 0, 1]})


@pytest.mark.parametrize("method", ["overlay", "mean_error"])
def test_mechanics_rejects_loading_unloading_connectivity_instead_of_sorting(tmp_path, method):
    t = pd.DataFrame({"x": [0, 2, 1, 3] * 2, "y": [0, 2, 4, 3] * 2, "sample": ["a"] * 4 + ["b"] * 4})
    with pytest.raises(ValueError, match="monotonic|increasing"):
        api().mechanics(
            t, config={"method": method, "x": "x", "y": "y", "sample": "sample", "output_dir": str(tmp_path)}
        )


def test_csv_export_accepts_list_valued_fields(tmp_path):
    frame = pd.DataFrame({"sample": ["s1", "s2"], "peaks": [[1.0, 2.0], [3.0]]})
    result = api().export_table(frame, config={"output_dir": str(tmp_path)})
    restored = pd.read_csv(result.data["file_path"], dtype=str, keep_default_na=False)
    assert restored["peaks"].tolist() == ["[1.0, 2.0]", "[3.0]"]

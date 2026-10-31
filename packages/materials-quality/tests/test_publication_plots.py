import json
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz
import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest
from matplotlib import pyplot as plt
from PIL import Image

from materials_quality.context import table_fingerprint
from materials_quality.science import visualization as viz


def observations():
    frame = pd.DataFrame(
        {
            "group": ["A"] * 3 + ["B"] * 3,
            "x": range(6),
            "stress": [1.234567890123456, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )
    frame.attrs["units"] = {"stress": "MPa"}
    return frame


def test_paper_bundle_has_editable_vectors_exact_size_tiff_and_traceable_data(tmp_path):
    frame = observations()
    result = viz.performance(
        frame,
        config={
            "profile": "paper",
            "data_kind": "synthetic",
            "method": "bar",
            "group": "group",
            "y": "stress",
            "width_mm": 150,
            "output_dir": str(tmp_path),
        },
    )
    files = {Path(p).suffix: Path(p) for p in result.artifacts}
    assert set(files) == {".png", ".svg", ".pdf", ".tiff", ".json", ".md"}
    svg_bytes = files[".svg"].read_bytes()
    assert b"\r" not in svg_bytes
    assert all(line == line.rstrip() for line in svg_bytes.splitlines())
    tree = ET.parse(files[".svg"])
    assert tree.findall(".//{http://www.w3.org/2000/svg}text")
    with fitz.open(files[".pdf"]) as doc:
        assert doc[0].rect.width == pytest.approx(150 / 25.4 * 72, abs=0.01)
        assert "SYNTHETIC" in doc[0].get_text()
        assert "MPa" in doc[0].get_text()
    with Image.open(files[".tiff"]) as im:
        im.load()
        assert min(im.info["dpi"]) >= 599
        assert im.width / im.info["dpi"][0] * 25.4 == pytest.approx(150, abs=0.1)
    manifest = json.loads(files[".json"].read_text(encoding="utf-8"))
    assert manifest["source"]["table_sha256"] == table_fingerprint(frame)
    assert manifest["plot_data"]["groups"][0]["y"][0] == frame["stress"].iloc[0]
    assert manifest["figure_contract"]["data_kind"] == "synthetic"
    caption = files[".md"].read_text(encoding="utf-8")
    assert "Synthetic demonstration" in caption and "sample SD" in caption
    assert result.data["labels"]["y"] == "stress (MPa)"


def test_semantic_styles_are_stable_across_group_order_and_data_unchanged(tmp_path):
    frame = observations()
    before = frame.copy(deep=True)
    configs = {"method": "scatter", "x": "x", "y": "stress", "group": "group", "output_dir": str(tmp_path)}
    first = viz.performance(frame, config=configs)
    second = viz.performance(frame.iloc[::-1], config=configs)
    assert first.data["figure_contract"]["series_styles"] == second.data["figure_contract"]["series_styles"]
    pd.testing.assert_frame_equal(before, frame)
    assert [g["n"] for g in first.data["plot_data"]["groups"]] == [3, 3]


def test_render_restores_global_rc_rng_and_closes_only_its_failed_figures(tmp_path):
    keeper = plt.figure()
    original = mpl.rcParams.copy()
    state = np.random.get_state()
    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0], "y": [0.0, 1.0, 0.0]})
    try:
        with pytest.raises(ValueError, match="annotation"):
            viz.spectra(
                frame, config={"x": "x", "columns": ["y"], "peaks": [{"x": 9}], "output_dir": str(tmp_path)}
            )
        assert plt.get_fignums() == [keeper.number]
        assert dict(mpl.rcParams) == dict(original)
        now = np.random.get_state()
        assert state[0] == now[0] and np.array_equal(state[1], now[1]) and state[2:] == now[2:]
    finally:
        plt.close(keeper)


def test_paper_group_comparison_keeps_raw_observations_and_error_definitions(tmp_path):
    frame = observations()
    result = viz.performance(
        frame,
        config={
            "method": "box",
            "y": "stress",
            "group": "group",
            "data_kind": "synthetic",
            "output_dir": str(tmp_path),
        },
    )
    assert result.data["figure_contract"]["observations_displayed"] == 6
    assert "1.5" in result.data["figure_contract"]["statistical_definition"]


def test_paper_profile_validates_dpi_and_reports_explicit_style_overrides(tmp_path):
    with pytest.raises(ValueError, match="dpi"):
        viz.performance(
            observations(),
            config={"profile": "paper", "x": "x", "y": "stress", "dpi": 0, "output_dir": str(tmp_path)},
        )
    result = viz.performance(
        observations(),
        config={
            "x": "x",
            "y": "stress",
            "group": "group",
            "color_map": {"A": "#112233", "B": "#D55E00"},
            "output_dir": str(tmp_path),
        },
    )
    assert result.data["figure_contract"]["series_styles"]["A"]["color"] == "#112233"


def test_publication_distribution_and_report_use_one_preview_per_logical_figure(tmp_path):
    from lfx.schema import DataFrame

    from materials_quality.science.catalog import component_class

    node = component_class("stats.distribution")().set(
        input_table=DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 6.0]}),
        config_json=json.dumps(
            {"profile": "paper", "data_kind": "synthetic", "column": "x", "output_dir": str(tmp_path)}
        ),
    )
    report = node.build_report()
    assert len(report.data["data"]["figure_previews"]) == 2
    export = component_class("export.report")().set(
        reports=[report], config_json=json.dumps({"output_dir": str(tmp_path)})
    )
    assert export.build_report().data["data"]["embedded_figures_verified"] == 2


def test_long_uncertainty_footer_fits_actual_paper_canvas(tmp_path):
    frame = pd.DataFrame(
        {
            "strain": [0.0, 1.0, 2.0] * 3,
            "stress": [0, 2, 4, 0, 3, 6, 0, 4, 8],
            "sample": ["a"] * 3 + ["b"] * 3 + ["c"] * 3,
            "group": ["Baseline"] * 9,
        }
    )
    result = viz.mechanics(
        frame,
        config={
            "profile": "paper",
            "formats": ["png"],
            "data_kind": "synthetic",
            "method": "mean_error",
            "error": "ci95",
            "x": "strain",
            "y": "stress",
            "sample": "sample",
            "group": "group",
            "output_dir": str(tmp_path),
        },
    )
    assert not result.data["figure_contract"]["layout_warnings"]


@pytest.mark.parametrize("units", [{"y_true": "MPa", "y_pred": "Pa"}, {"y_true": "MPa"}])
def test_predicted_and_observed_units_must_match_before_drawing(tmp_path, units):
    with pytest.raises(ValueError, match="unit"):
        viz.statistics_plot(
            pd.DataFrame({"y_true": [1.0, 2.0, 3.0], "y_pred": [1.0, 2.0, 4.0]}),
            config={"method": "prediction", "units": units, "output_dir": str(tmp_path)},
        )


def test_reject_excessive_raster_size_before_render_allocation():
    from materials_quality.science.plot_style import figure

    before = set(plt.get_fignums())
    try:
        with pytest.raises(ValueError, match="pixel|raster"):
            figure({"profile": "paper", "figsize": [30, 30]})
    finally:
        for number in set(plt.get_fignums()) - before:
            plt.close(number)


@pytest.mark.parametrize("operation", ["distribution", "histogram"])
def test_histogram_cannot_silently_hide_values_outside_explicit_bins(tmp_path, operation):
    from materials_quality.science.statistics import distribution

    options = {"column": "x", "bins": [0, 2, 4], "output_dir": str(tmp_path)}
    with pytest.raises(ValueError, match="bins|cover"):
        if operation == "distribution":
            distribution(pd.DataFrame({"x": [-100.0, 1.0, 2.0, 3.0, 100.0]}), config=options)
        else:
            viz.statistics_plot(
                pd.DataFrame({"x": [-100.0, 1.0, 2.0, 3.0, 100.0]}), config={**options, "method": "histogram"}
            )


def test_shipped_gallery_links_and_full_precision_sources_exist():
    import hashlib

    root = Path(__file__).resolve().parents[1] / "examples/paper_figures"
    rows = json.loads((root / "gallery.json").read_text(encoding="utf-8"))
    assert len(rows) == 6
    for row in rows:
        assert (root / row["preview"]).is_file()
        assert all((root / path).is_file() for path in row["artifacts"])
        assert hashlib.sha256((root / row["source"]).read_bytes()).hexdigest() == row["source_sha256"]


@pytest.mark.parametrize("unit", ["wt.%", "arbitrary units", "AU"])
def test_matching_descriptive_units_are_preserved_without_forced_pint_parsing(tmp_path, unit):
    result = viz.statistics_plot(
        pd.DataFrame({"y_true": [1.0, 2.0, 3.0], "y_pred": [1.0, 2.0, 4.0]}),
        config={
            "method": "prediction",
            "units": {"y_true": unit, "y_pred": unit},
            "output_dir": str(tmp_path),
        },
    )
    assert result.data["figure_contract"]["units"] == {"y_true": unit, "y_pred": unit}


def test_cjk_titles_and_labels_render_when_a_cjk_font_is_installed(tmp_path):
    from matplotlib import font_manager

    names = {font.name for font in font_manager.fontManager.ttflist}
    if not names.intersection({"Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "WenQuanYi Zen Hei"}):
        pytest.skip("requires an installed CJK font")
    result = viz.performance(
        pd.DataFrame({"组别": ["对照组"] * 3 + ["处理组"] * 3, "强度": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}),
        config={
            "profile": "paper",
            "formats": ["png", "pdf"],
            "method": "box",
            "group": "组别",
            "y": "强度",
            "title": "材料性能对比",
            "output_dir": str(tmp_path),
        },
    )
    assert not [w for w in result.warnings if "Glyph" in w]
    pdf = next(Path(path) for path in result.artifacts if path.endswith(".pdf"))
    with fitz.open(pdf) as document:
        assert "材料性能对比" in document[0].get_text()

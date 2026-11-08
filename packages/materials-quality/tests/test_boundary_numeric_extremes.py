import json

import numpy as np
import pandas as pd
import pytest

from materials_quality.science import materials, plot_style, statistics, visualization, viz_report


def boundary_dir(tmp_path, name):
    target = tmp_path / name
    target.mkdir()
    return str(target)


def test_export_table_excel_rejects_non_finite_floats_cleanly(tmp_path):
    frame = pd.DataFrame({"v": [1.0, float("inf"), -float("inf"), float("nan")]})
    with pytest.raises(ValueError, match="non-finite|CSV"):
        visualization.export_table(
            frame, config={"format": "excel", "output_dir": boundary_dir(tmp_path, "x")}
        )
    csv_result = visualization.export_table(
        frame, config={"format": "csv", "output_dir": boundary_dir(tmp_path, "csv")}
    )
    assert csv_result.data["verified"] is True


def test_plot_style_rejects_non_numeric_figsize_cleanly(tmp_path):
    frame = pd.DataFrame({"v": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="figsize"):
        visualization.statistics_plot(
            frame,
            config={
                "method": "histogram",
                "column": "v",
                "figsize": ["10", 4],
                "output_dir": boundary_dir(tmp_path, "fig"),
            },
        )
    with pytest.raises(ValueError, match="figsize"):
        plot_style.figure({"figsize": [4]})


def test_morphology_rejects_overflowing_pixel_size_cleanly(tmp_path):
    image = np.array([[0.0, 1.0], [1.0, 0.0]])
    with pytest.raises(ValueError, match="pixel_size"):
        materials.microstructure(
            config={
                "threshold": 0.5,
                "pixel_size": 1e308,
                "spatial_unit": "um",
                "output_dir": boundary_dir(tmp_path, "img"),
            },
            data={"image": image},
        )


def test_report_figure_item_requires_path_cleanly(tmp_path):
    with pytest.raises(ValueError, match="figure"):
        viz_report.build_report(
            None,
            {"format": "html", "output_dir": boundary_dir(tmp_path, "rep")},
            {"figures": [123]},
        )
    with pytest.raises(ValueError, match="figure"):
        viz_report.build_report(
            None,
            {"format": "html", "output_dir": boundary_dir(tmp_path, "rep2")},
            {"figures": [{"caption": "no path"}]},
        )


def test_significance_extreme_data_stays_strict_json():
    frame = pd.DataFrame({"g": ["a", "a", "b", "b"], "v": [0.0, 1e308, -1e308, 5e-324]})
    result = statistics.significance(frame, config={"group": "g", "column": "v", "method": "welch"})
    json.dumps(result.data, allow_nan=False)
    interval = result.data["confidence_interval"]
    assert len(interval) == 2
    assert all(value is None or np.isfinite(value) for value in interval)

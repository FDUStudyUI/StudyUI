import numpy as np
import pandas as pd
import pytest

from materials_quality.science.series_dynamics import analyze_series


def test_linear_trend_and_growth_are_per_whole_curve():
    t = np.arange(20.0)
    frame = pd.DataFrame(
        {"curve_id": ["a"] * 20 + ["b"] * 20, "time": np.tile(t, 2), "value": np.r_[2 * t + 3, -t]}
    )
    result = analyze_series(frame, {"time_unit": "s", "growth_min_points": 5})
    assert result.features.slope.tolist() == pytest.approx([2, -1])
    assert result.features.slope_ci_low.tolist() == pytest.approx([2, -1])
    assert len([e for e in result.data["events"] if e["event"] == "sustained_growth"]) == 1
    assert len(result.table) == 40
    assert result.features.spike_count.tolist() == [0, 0]
    assert result.table.attrs["units"]["linear_trend"] == "unspecified"


def test_invalid_curve_and_irregular_savgol_rejected():
    f = pd.DataFrame({"curve_id": ["a"] * 4, "time": [0.0, 1, 1, 4], "value": [0, 1, 2, 3]})
    with pytest.raises(ValueError, match="duplicate"):
        analyze_series(f, {"time_unit": "s"})
    f.time = [0.0, 1, 3, 4]
    with pytest.raises(ValueError, match="uniform"):
        analyze_series(f, {"time_unit": "s", "smoothing": "savgol", "smooth_window": 3, "smooth_order": 1})


def test_spike_and_window_change_score():
    t = np.arange(40.0)
    y = np.r_[np.zeros(20), np.ones(20) * 10]
    y[8] = 20
    r = analyze_series(
        pd.DataFrame({"curve_id": "a", "time": t, "value": y}),
        {
            "time_unit": "s",
            "smoothing": "moving",
            "smooth_window": 5,
            "change_window": 5,
            "change_threshold": 3,
        },
    )
    assert r.table.loc[8, "spike"]
    assert any(e["event"] == "change_point" and 18 <= e["time"] <= 22 for e in r.data["events"])


def test_native_component_direct_base():
    import asyncio

    from lfx.custom import Component
    from lfx.custom.eval import eval_custom_component_code
    from lfx.graph import Graph
    from lfx.schema import DataFrame

    from components.materials_batch.series_dynamics import SeriesDynamics

    assert SeriesDynamics.__bases__ == (Component,)
    assert all(i.name != "config_json" for i in SeriesDynamics.inputs)
    node = SeriesDynamics().set(
        input_table=DataFrame(pd.DataFrame({"curve_id": "a", "time": range(10), "value": range(10)})),
        time_unit="s",
    )
    results, _ = asyncio.run(node.build_results())
    assert len(results["features"]) == 1
    assert len(results["curves"]) == 10
    payload = Graph(start=node, end=node).dump()
    source = payload["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert eval_custom_component_code(source).__name__ == "SeriesDynamics"

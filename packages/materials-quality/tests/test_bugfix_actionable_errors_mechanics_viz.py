from pathlib import Path

import pandas as pd
import pytest

from materials_quality.science import materials, visualization

DEMO = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "materials_quality"
    / "demos"
    / "data"
    / "01_钛合金拉伸力学性能_Ti64.csv"
)


def ti64():
    return pd.read_csv(DEMO)


def ti64_mechanics(**extra):
    config = {"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0.0, 0.0008]}
    config.update(extra)
    return materials.mechanics(ti64(), config=config)


def test_missing_offset_crossing_warning_reports_fit_and_input_ranges():
    result = materials.mechanics(
        ti64(),
        config={"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0.001, 0.004]},
    )
    assert result.data["yield_stress_MPa"] is None
    message = next(w for w in result.warnings if "offset-line crossing" in w)
    for token in ("fit_range", "1000", "strain range", "stress range", "initial linear", "candidate"):
        assert token in message, (token, message)
    diagnostics = result.data["offset_line_diagnostics"]
    assert diagnostics["fitted_modulus_MPa"] == pytest.approx(1000.0, rel=1e-6)
    assert diagnostics["fit_range_fraction"] == pytest.approx([0.001, 0.004])
    assert diagnostics["input_strain_range_fraction"] == pytest.approx([0.0, 0.02])
    assert diagnostics["input_stress_range_MPa"] == pytest.approx([0.0, 219.0])


def test_elastic_region_candidate_is_reported_without_auto_selection():
    result = materials.mechanics(
        ti64(),
        config={"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0.001, 0.004]},
    )
    diagnostics = result.data["offset_line_diagnostics"]
    candidate = diagnostics["elastic_region_candidate_fraction"]
    assert candidate is not None
    assert candidate[0] == 0.0
    assert 0.0005 < candidate[1] <= 0.0015


def test_mechanics_missing_columns_lists_available_and_suggests_derived_names():
    source = ti64_mechanics()
    with pytest.raises(ValueError) as caught:
        materials.mechanics(
            source.table,
            config={"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0.0, 0.0008]},
        )
    message = str(caught.value)
    for token in ("strain_fraction", "stress_MPa", "cfg_x", "raw_y", "available columns"):
        assert token in message.lower() if token == "available columns" else token in message


def test_viz_mechanics_unknown_columns_are_actionable_for_derived_tables():
    source = ti64_mechanics()
    with pytest.raises(ValueError) as caught:
        visualization.mechanics(
            source.table,
            config={
                "method": "overlay",
                "x": "strain",
                "y": "stress",
                "sample": "specimen",
                "output_dir": str(Path(__file__).parents[0] / "__viz_tmp__"),
            },
        )
    message = str(caught.value)
    for token in ("strain_fraction", "stress_MPa", "cfg_x", "cfg_y", "available columns"):
        assert token in message.lower() if token == "available columns" else token in message


def test_viz_mechanics_unit_declaration_lists_columns_and_mapping_format(tmp_path):
    frame = pd.DataFrame(
        {
            "sample_id": ["a", "a", "a"],
            "strain_fraction": [0.0, 0.001, 0.002],
            "stress_MPa": [0.0, 200.0, 400.0],
        }
    )
    with pytest.raises(ValueError) as caught:
        visualization.mechanics(
            frame,
            config={
                "method": "overlay",
                "x": "strain_fraction",
                "y": "stress_MPa",
                "sample": "sample_id",
                "units": {"strain": "1"},
                "output_dir": str(tmp_path),
            },
        )
    message = str(caught.value)
    assert "available columns" in message.lower()
    assert "strain_fraction" in message and "stress_MPa" in message
    assert '{"<column>": "<unit>"}' in message


def test_viz_mechanics_valid_input_still_plots(tmp_path):
    frame = pd.DataFrame(
        {
            "sample_id": ["a"] * 4 + ["b"] * 4,
            "strain_fraction": [0.0, 0.001, 0.002, 0.003] * 2,
            "stress_MPa": [0.0, 200.0, 400.0, 600.0, 0.0, 210.0, 420.0, 630.0],
        }
    )
    result = visualization.mechanics(
        frame,
        config={
            "method": "overlay",
            "x": "strain_fraction",
            "y": "stress_MPa",
            "sample": "sample_id",
            "units": {"strain_fraction": "1", "stress_MPa": "MPa"},
            "output_dir": str(tmp_path),
        },
    )
    assert result.artifacts
    assert result.data["plot_data"]["curves"]

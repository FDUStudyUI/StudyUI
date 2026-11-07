import numpy as np
import pandas as pd

from materials_quality.science.research_plan import run_research_plan


def test_visual_plan_reuses_raw_branch_when_normalization_changes():
    table = pd.DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 2.0, 5.0, 8.0]})
    first, prior = run_research_plan(table)
    assert first.data["execution_status"] == "completed"
    assert first.data["execution_count"] == 3
    second, run = run_research_plan(table, {"normalization": "minmax"}, previous=prior)
    assert second.data["reuse_count"] == 1
    assert second.data["execution_count"] == 2
    assert run.records["raw_summary"].status == "reused"
    assert np.allclose(second.table["mean"], [1 / 14, 11 / 14])


def test_spectra_preset_uses_one_primary_peak_per_curve():
    rows = []
    for i, peak in enumerate([700.0, 710.0, 740.0, 750.0]):
        for x in np.linspace(600, 850, 101):
            rows.append(
                {
                    "curve_id": f"c{i}",
                    "group": "a" if i < 2 else "b",
                    "x": x,
                    "y": np.exp(-(((x - peak) / 10) ** 2)),
                }
            )
    result, run = run_research_plan(
        pd.DataFrame(rows),
        {
            "task": "spectra",
            "x_unit": "nm",
            "y_unit": "counts",
        },
    )
    assert run.status == "success", result.data
    assert result.table["count"].tolist() == [2, 2]
    assert result.table["mean"].tolist() == [705.0, 745.0]
    assert len(result.features) == 4


def test_failed_plan_returns_status_diagnostics_and_repair_preserves_raw_branch():
    table = pd.DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 2.0, 5.0, 8.0]})
    failed, prior = run_research_plan(table, {"normalization": "bad"})
    assert failed.data["execution_status"] != "completed"
    assert "status" in failed.table
    repaired, _ = run_research_plan(table, {"normalization": "zscore"}, prior)
    assert repaired.data["execution_status"] == "completed"
    assert repaired.data["reuse_count"] == 1


def test_batch_snv_keeps_processed_units_and_warnings():
    from materials_quality.science.spectrum_batch import analyze_spectra

    table = pd.DataFrame(
        {"curve_id": ["a"] * 21, "x": np.arange(21.0), "y": 1 + np.exp(-(((np.arange(21.0) - 10) / 3) ** 2))}
    )
    result = analyze_spectra(
        table,
        {"x_unit": "nm", "intensity_unit": "counts", "normalization": "snv", "allow_intensity_loss": True},
    )
    assert result.table.attrs["units"]["normalized"] == "dimensionless"
    assert result.table.attrs["units"]["smoothed"] == "counts"
    assert any("SNV" in warning for warning in result.warnings)

"""Independent numerical expectations and failure identities for skill tasks."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from materials_quality.skills.planning import make_plan


def run(table, task, parameters, tmp_path):
    from materials_quality.skills.execution import execute_plan

    p = make_plan(table, task=task, parameters={"data_kind": "synthetic", **parameters})
    assert p["ready"], p["issues"]
    return execute_plan(table, p, output_dir=tmp_path)


def test_spectrum_pipeline_has_16_peaks_8_candidates_correct_means_and_verified_files(tmp_path):
    from scripts.build_research_examples import synthetic_records

    f = pd.DataFrame(synthetic_records())
    raw = f.copy(deep=True)
    result = run(
        f,
        "spectra",
        {
            "x_unit": "nm",
            "y_unit": "counts",
            "peak_window": [650, 850],
            "baseline": "constant",
            "baseline_value": 2,
        },
        tmp_path,
    )
    assert len(result.features) == 16
    assert len(result.table) == 8
    assert result.groups["mean"].tolist() == pytest.approx([715, 755])
    assert result.groups["count"].tolist() == [4, 4]
    assert result.report["status"] == "completed"
    assert result.report["counts"]["completed"] == 8
    pd.testing.assert_frame_equal(raw, f)
    assert result.report["provenance"]["raw_preserved"]
    html = next(Path(p) for p in result.artifacts if p.endswith(".html"))
    assert "data:image/png;base64," in html.read_text("utf-8")
    manifest = json.loads(
        next(Path(p) for p in result.artifacts if p.endswith("manifest.json")).read_text("utf-8")
    )
    assert len(manifest["files"]) >= 5
    assert all(len(item["sha256"]) == 64 for item in manifest["files"])


def test_missing_candidates_are_retained_not_zero_or_counted(tmp_path):
    from scripts.build_research_examples import synthetic_records

    result = run(
        pd.DataFrame(synthetic_records()),
        "spectra",
        {"x_unit": "nm", "y_unit": "counts", "peak_window": [720, 850]},
        tmp_path,
    )
    assert len(result.table) == 8
    assert result.table["lambda10_nm"].isna().sum() == 2
    assert result.groups["count"].tolist() == [2, 4]
    assert result.groups["mean"].tolist() == pytest.approx([725, 755])
    assert any("候选" in w for w in result.report["warnings"])


def test_mechanics_correct_units_and_partial_failure_retains_sample(tmp_path):
    strain = np.linspace(0, 0.02, 401)
    stress = np.where(strain <= 0.001, 200000 * strain, 200 + 1000 * (strain - 0.001))
    f = pd.DataFrame({"sample_id": ["good"] * 401, "strain": strain, "stress": stress})
    bad = f.assign(sample_id="bad", stress=0)
    result = run(
        pd.concat([f, bad]),
        "mechanics",
        {"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.0008]},
        tmp_path,
    )
    assert len(result.table) == 2
    good = result.table.iloc[0]
    assert good["elastic_modulus_MPa"] == pytest.approx(200000)
    assert good["yield_stress_MPa"] == pytest.approx(202.01005025125627)
    assert result.table.iloc[1]["status"] == "failed"
    assert result.report["status"] == "partial_failed"
    assert len(result.curves) == 401


def test_contrast_aggregates_technical_repeats_and_reports_inference(tmp_path):
    rows = [
        {
            "group": g,
            "variable": "strength",
            "sample_id": f"{g}{i}-{r}",
            "experimental_unit": f"{g}{i}",
            "value": i + delta + r / 10,
        }
        for g, delta in [("A", 0), ("B", 4)]
        for i in range(4)
        for r in range(3)
    ]
    result = run(pd.DataFrame(rows), "contrast", {"design": "independent", "value_unit": "MPa"}, tmp_path)
    assert len(result.table) == 8
    assert result.groups["count"].tolist() == [4, 4]
    assert len(result.features) == 1
    assert result.features.iloc[0]["method"] == "welch_t"
    assert result.features.iloc[0]["p_adjusted"] < 0.05


def test_execution_rejects_pending_plan_and_changed_data(tmp_path):
    from materials_quality.skills.execution import execute_plan

    f = pd.DataFrame({"strain": [0, 1, 2], "stress": [0, 1, 2]})
    with pytest.raises(ValueError, match="补充|信息"):
        execute_plan(f, make_plan(f, task="mechanics"), output_dir=tmp_path)


def test_html_escapes_group_and_sample_text(tmp_path):
    f = pd.DataFrame(
        {
            "sample_id": ["<script>alert(1)</script>"] * 4,
            "strain": [0, 0.0004, 0.0008, 0.004],
            "stress": [0, 80, 160, 203],
        }
    )
    result = run(
        f, "mechanics", {"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.0008]}, tmp_path
    )
    html = next(Path(p).read_text("utf-8") for p in result.artifacts if p.endswith(".html"))
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_unit_synonyms_work_without_mutating_original_metadata(tmp_path):
    f = pd.DataFrame({"curve_id": ["001"] * 3, "x": [650, 700, 750], "y": [1.0, 3.0, 1.0]})
    f.attrs["units"] = {"x": "nanometer", "y": "counts"}
    result = run(f, "spectra", {"x_unit": "nm", "y_unit": "counts", "peak_window": [650, 750]}, tmp_path)
    assert result.report["counts"]["completed"] == 1
    assert f.attrs["units"]["x"] == "nanometer"

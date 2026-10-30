"""Regression cases for independent review of scientific edge conditions."""

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from materials_quality.science.materials import mechanics, microstructure, sem_eds, spectra, thermal


def test_two_endotherms_have_local_onsets_and_no_exotherm_in_their_positive_valley():
    x = np.linspace(0, 100, 1001)
    y = sum(np.exp(-0.5 * ((x - center) / 5) ** 2) for center in (30, 70))
    peaks = thermal(
        pd.DataFrame({"x": x, "y": y}),
        config={"kind": "dsc", "x_unit": "s", "y_unit": "W/g", "endotherm": "positive"},
    ).data["peaks"]
    assert [p["event"] for p in peaks] == ["endothermic", "endothermic"]
    assert [p["peak_coordinate"] for p in peaks] == pytest.approx([30, 70])
    assert [p["onset"] for p in peaks] == pytest.approx([20, 60], abs=0.05)


def test_tg_onset_depends_on_observed_plateau_not_stage_threshold():
    x = np.linspace(0, 100, 1001)
    frame = pd.DataFrame({"x": x, "y": 20 - 4 / (1 + np.exp(-(x - 50) / 2))})
    for threshold in (0.01, 2.4):
        stage = thermal(
            frame, config={"kind": "tg", "x_unit": "degC", "y_unit": "mg", "stage_threshold": threshold}
        ).data["stages"][0]
        assert stage["onset"] == pytest.approx(46, abs=0.02)
        assert stage["baseline_level"] == pytest.approx(100, abs=0.01)
        assert stage["plateau_range"][1] < stage["peak_loss_coordinate"]


def test_tg_abstains_from_onset_when_acquisition_begins_during_mass_loss():
    x = np.linspace(47, 70, 231)
    frame = pd.DataFrame({"x": x, "y": 20 - 4 / (1 + np.exp(-(x - 50) / 2))})
    result = thermal(frame, config={"kind": "tg", "x_unit": "degC", "y_unit": "mg", "stage_threshold": 2})
    assert result.data["stages"][0]["onset"] is None
    assert result.data["stages"][0]["baseline_level"] is None
    assert any("plateau" in warning for warning in result.warnings)


def test_offset_endpoint_roundoff_only_and_no_extrapolation():
    config = {"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.0008]}
    frame = pd.DataFrame({"strain": [0, 0.0004, 0.0008, 0.006], "stress": [0.0, 4.0, 8.0, 40.0]})
    assert mechanics(frame, config=config).data["yield_stress_MPa"] == pytest.approx(40)
    frame.loc[3, "stress"] = 40 + 1e-9
    assert mechanics(frame, config=config).data["yield_stress_MPa"] is None


def test_offset_intersection_itself_must_follow_fit_interval():
    frame = pd.DataFrame({"strain": [0, 0.1, 0.2, 0.8], "stress": [0, 1, 2, 1]})
    result = mechanics(frame, config={"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.3]})
    assert result.data["yield_stress_MPa"] is None


def test_string_false_cannot_confirm_fracture_or_authorize_sorting():
    frame = pd.DataFrame({"strain": [0, 0.001, 0.002], "stress": [0, 1, 2]})
    with pytest.raises(ValueError, match="fracture_confirmed"):
        mechanics(
            frame,
            config={
                "strain_unit": "fraction",
                "stress_unit": "MPa",
                "fit_range": [0, 0.002],
                "fracture_confirmed": "false",
            },
        )
    with pytest.raises(ValueError, match="sort"):
        spectra(pd.DataFrame({"x": [2, 1, 0], "y": [0, 1, 0]}), config={"sort": "false"})


def test_cmyk_black_channel_is_used_when_segmenting_tiff(tmp_path):
    image = Image.new("CMYK", (2, 2))
    image.putdata([(0, 0, 0, 0), (0, 0, 0, 255)] * 2)
    path = tmp_path / "black-ink.tif"
    image.save(path)
    result = microstructure(config={"path": str(path), "threshold": 127, "output_dir": str(tmp_path)})
    with Image.open(result.artifacts[0]) as mask:
        np.testing.assert_array_equal(np.asarray(mask), [[255, 0], [255, 0]])


def test_eds_totals_are_per_composition_and_ambiguous_duplicates_are_rejected():
    frame = pd.DataFrame(
        {"spot": ["A", "A", "B", "B"], "element": ["Si", "O", "Si", "O"], "wt_percent": [46, 54, 47, 53]}
    )
    with pytest.raises(ValueError, match="group_by"):
        sem_eds(frame, config={"method": "eds"})
    result = sem_eds(frame, config={"method": "eds", "group_by": "spot"})
    assert result.data["totals"] is None
    assert result.data["group_totals"] == [
        {"group": "A", "totals": {"wt_percent": 100}},
        {"group": "B", "totals": {"wt_percent": 100}},
    ]
    assert not any("differ from 100" in warning for warning in result.warnings)

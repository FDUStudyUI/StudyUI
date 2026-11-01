import numpy as np
import pandas as pd
import pytest
from scipy.stats import t

from materials_quality.science.visualization import spectra


def frame():
    return pd.DataFrame(
        {
            "curve_id": np.repeat(["a", "b", "c"], 3),
            "group": "G",
            "x": np.tile([1.0, 2.0, 3.0], 3),
            "y": np.r_[[0.0, 2.0, 4.0], [2.0, 4.0, 6.0], [4.0, 6.0, 8.0]],
        }
    )


@pytest.mark.parametrize("band", ["iqr", "sd", "ci95"])
def test_analytic_bands_and_complete_curve_count(tmp_path, band):
    r = spectra(
        frame(),
        config={
            "method": "band",
            "x": "x",
            "y": "y",
            "curve_id": "curve_id",
            "group": "group",
            "band": band,
            "data_kind": "synthetic",
            "output_dir": str(tmp_path),
        },
    )
    b = r.data["plot_data"]["bands"][0]
    assert b["n_curves"] == 3
    assert b["mean"] == pytest.approx([2, 4, 6])
    delta = 1 if band == "iqr" else 2 if band == "sd" else t.ppf(0.975, 2) * 2 / np.sqrt(3)
    assert b["lower"] == pytest.approx(np.array([2, 4, 6]) - delta)
    assert b["upper"] == pytest.approx(np.array([2, 4, 6]) + delta)


def test_mismatched_grid_requires_explicit_intersection(tmp_path):
    f = frame()
    f.loc[f.curve_id == "b", "x"] = [1.0, 2.5, 3.0]
    c = {"method": "band", "x": "x", "y": "y", "curve_id": "curve_id", "output_dir": str(tmp_path)}
    with pytest.raises(ValueError, match="grid"):
        spectra(f, config=c)
    r = spectra(f, config={**c, "grid": [1.0, 2.0, 3.0]})
    assert r.data["plot_data"]["bands"][0]["interpolated"]
    with pytest.raises(ValueError, match="shared"):
        spectra(f, config={**c, "grid": [0.0, 2.0, 3.0]})


def test_ci_rejects_single_curve_and_cross_group_identity(tmp_path):
    f = frame()
    c = {
        "method": "band",
        "x": "x",
        "y": "y",
        "curve_id": "curve_id",
        "band": "ci95",
        "group": "group",
        "output_dir": str(tmp_path),
    }
    with pytest.raises(ValueError, match="two"):
        spectra(f.loc[f.curve_id == "a"], config=c)
    f.loc[0, "group"] = "H"
    with pytest.raises(ValueError, match="whole curve"):
        spectra(f, config=c)


def test_native_band_controls_and_mixed_units_rejected(tmp_path):
    from materials_quality.science.ui_schema import science_inputs

    controls = {i.name: i for i in science_inputs("viz.spectra", {"method": "overlay"})}
    assert "band" in controls["cfg_method"].options
    assert controls["cfg_band"].__class__.__name__ == "DropdownInput"
    f = frame()
    f["unit"] = ["counts"] * 8 + ["V"]
    with pytest.raises(ValueError, match="consistent"):
        spectra(
            f,
            config={
                "method": "band",
                "x": "x",
                "y": "y",
                "unit_column": "unit",
                "curve_id": "curve_id",
                "output_dir": str(tmp_path),
            },
        )

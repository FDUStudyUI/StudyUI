import numpy as np
import pandas as pd
import pytest

from materials_quality.science.contracts import NodeResult
from materials_quality.science.materials import spectra, xrd


def test_feature_table_maps_actual_peak_keys_and_units_without_nm_guessing():
    from materials_quality.science.features import features_for

    x = np.linspace(400, 800, 401)
    frame = pd.DataFrame({"x": x, "y": 3 + 8 * np.exp(-0.5 * ((x - 600) / 20) ** 2)})
    config = {"baseline": {"method": "constant", "value": 3}, "x_unit": "cm^-1", "intensity_unit": "counts"}
    result = spectra(frame, config=config)
    features = features_for("materials.spectra", result, curve_id="001", group="control")
    row = features.iloc[0]
    assert row["peak_position"] == 600
    assert row["baseline"] == 3
    assert row["area"] == pytest.approx(401.0605, rel=1e-4)
    assert row["fwhm"] == pytest.approx(47.0964, rel=1e-3)
    assert row["curve_id"] == "001" and row["group"] == "control"
    assert row["x_unit"] == "cm^-1"
    assert not any(c.endswith("_nm") for c in features)
    assert features.attrs["units"]["area"] == "counts*cm^-1"
    assert set(features.attrs["units"]) <= set(features.columns)


def test_feature_nm_aliases_and_xrd_mapping_do_not_drop_missing_widths():
    from materials_quality.science.features import features_for

    result = NodeResult(
        table=pd.DataFrame({"baseline": [2.0, 2.0, 2.0]}),
        data={
            "peaks": [
                {
                    "index": 1,
                    "position": 550.0,
                    "height": 4.0,
                    "prominence": 3.0,
                    "fwhm": None,
                    "area_between_bases": 8.0,
                }
            ],
            "x_unit": "nm",
            "transform": {"parameters": {"intensity_unit": "a.u."}},
        },
    )
    features = features_for("materials.xrd", result)
    assert features.loc[0, "peak_position_nm"] == 550
    assert pd.isna(features.loc[0, "fwhm"])
    assert features.loc[0, "area"] == 8
    assert features.loc[0, "baseline"] == 2


def test_no_peak_result_has_stable_feature_columns_and_no_ghost_unit_attrs():
    from materials_quality.science.features import features_for

    result = xrd(pd.DataFrame({"x": [1, 2, 3], "y": [1, 1, 1]}), config={"x_unit": "deg"})
    features = features_for("materials.xrd", result)
    assert features.empty
    assert {"curve_id", "group", "peak_position", "area", "fwhm"} <= set(features)
    assert set(features.attrs.get("units", {})) <= set(features)


def test_xrd_declared_intensity_unit_propagates_to_feature_table():
    from materials_quality.science.features import features_for

    x = np.arange(7, dtype=float)
    y = np.array([0, 1, 3, 9, 3, 1, 0], dtype=float)
    result = xrd(
        pd.DataFrame({"two_theta_deg": x, "intensity_counts": y}),
        config={
            "x": "two_theta_deg",
            "y": "intensity_counts",
            "x_unit": "deg",
            "intensity_unit": "counts",
            "prominence": 1,
        },
    )
    features = features_for("materials.xrd", result)

    assert len(features) == 1
    assert features.attrs["units"]["height"] == "counts"
    assert features.attrs["units"]["area"] == "counts*deg"
    assert features.attrs["units"]["peak_position"] == "deg"

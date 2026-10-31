"""Scientific regression fixtures; all samples are synthetic, not material identifications."""

import importlib

import numpy as np
import pandas as pd
import pytest


def run(name, table=None, **kwargs):
    module = importlib.import_module("materials_quality.science.materials")
    return getattr(module, name)(table, **kwargs)


def gaussian(x, center=0, sigma=1, amplitude=1):
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def test_xrd_peak_position_absolute_fwhm_and_raw_preservation():
    x = np.linspace(-8, 8, 1601)
    frame = pd.DataFrame({"x": x, "y": 3 + 0.1 * x + gaussian(x, sigma=1.2, amplitude=7)})
    before = frame.copy(deep=True)
    result = run("xrd", frame, config={"baseline": {"method": "linear"}, "prominence": 1})
    peak = result.data["peaks"][0]
    assert peak["position"] == pytest.approx(0, abs=0.01)
    assert peak["fwhm"] == pytest.approx(2.82578, abs=0.001)
    pd.testing.assert_frame_equal(frame, before)
    assert result.table is not frame
    np.testing.assert_allclose(result.table["raw_y"], frame.y)


def test_reference_mixture_and_library_match_require_actual_references():
    x = np.linspace(0, 20, 401)
    a, b = gaussian(x, 5, 0.5), gaussian(x, 14, 0.8)
    refs = [
        {"name": "synthetic-A", "x": x.tolist(), "y": a.tolist()},
        {"name": "synthetic-B", "x": x.tolist(), "y": b.tolist()},
    ]
    result = run(
        "xrd",
        pd.DataFrame({"x": x, "y": 2 * a + 3 * b}),
        config={"match": "profile", "whole_pattern": "reference"},
        data={"references": refs},
    )
    assert result.data["fit"]["coefficients"] == pytest.approx({"synthetic-A": 2, "synthetic-B": 3})
    assert result.data["fit"]["rmse"] < 1e-10
    assert result.data["matches"][0]["name"] == "synthetic-B"
    with pytest.raises(ValueError, match="reference"):
        run("xrd", pd.DataFrame({"x": x, "y": a}), config={"match": "profile"})


def test_empirical_gaussian_whole_pattern_recovers_parameters():
    x = np.linspace(0, 20, 801)
    result = run(
        "xrd",
        pd.DataFrame({"x": x, "y": gaussian(x, 6, 0.6, 4) + gaussian(x, 13, 1.1, 2)}),
        config={
            "whole_pattern": "gaussian",
            "fit_peaks": [
                {"center": 6.1, "sigma": 0.8, "amplitude": 3},
                {"center": 12.8, "sigma": 1, "amplitude": 3},
            ],
        },
    )
    assert result.data["fit"]["model"] == "empirical sum of Gaussian profiles"
    assert result.data["fit"]["peaks"][0]["sigma"] == pytest.approx(0.6, abs=1e-5)
    assert result.data["fit"]["peaks"][1]["center"] == pytest.approx(13, abs=1e-5)


def test_spectral_baseline_smooth_area_and_library_normalization():
    x = np.linspace(-8, 8, 1601)
    y = gaussian(x, sigma=1, amplitude=2)
    result = run(
        "spectra",
        pd.DataFrame({"x": x, "y": 1 + 0.02 * x + y}),
        config={
            "baseline": {"method": "anchors", "points": [[-8, 0.84], [8, 1.16]]},
            "smooth_window": 11,
            "normalization": "max",
            "area_ranges": [[-8, 8]],
            "match": "profile",
        },
        data={"references": [{"name": "synthetic", "x": x.tolist(), "y": y.tolist()}]},
    )
    assert result.data["areas"][0]["area"] == pytest.approx(5.01325655, abs=1e-5)
    assert result.table.normalized.max() == pytest.approx(1)
    assert result.data["matches"][0]["score"] > 0.99999


def test_peak_list_matching_is_one_to_one_and_reports_coverage():
    x = np.linspace(0, 10, 1001)
    result = run(
        "xrd",
        pd.DataFrame({"x": x, "y": gaussian(x, 3, 0.1) + gaussian(x, 7, 0.1)}),
        config={"match": "peaks", "match_tolerance": 0.05, "prominence": 0.2},
        data={"references": [{"name": "synthetic", "peaks": [3.01, 7.01, 9]}]},
    )
    assert result.data["matches"][0]["matched_count"] == 2
    assert result.data["matches"][0]["reference_coverage"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("x", [[0, 2, 1, 3], [0, 1, 1, 2]])
def test_xy_rejects_unordered_or_duplicate_coordinates(x):
    with pytest.raises(ValueError, match="increasing"):
        run("xrd", pd.DataFrame({"x": x, "y": [0, 1, 2, 0]}))


def test_explicit_sort_and_nonfinite_rejection():
    result = run("spectra", pd.DataFrame({"x": [2, 1, 0], "y": [0, 1, 0]}), config={"sort": True})
    assert result.table.x.tolist() == [0, 1, 2]
    assert result.data["transform"]["sorted"] is True
    with pytest.raises(ValueError, match="missing|finite"):
        run("spectra", pd.DataFrame({"x": [0, 1, 2], "y": [0, np.nan, 1]}))


def test_dsc_temperature_integration_converts_heating_rate_to_seconds():
    x = np.linspace(0, 100, 1001)
    result = run(
        "thermal",
        pd.DataFrame({"x": x, "y": 0.01 + gaussian(x, 50, 5, 2)}),
        config={
            "kind": "dsc",
            "x_unit": "degC",
            "y_unit": "W/g",
            "endotherm": "positive",
            "heating_rate": 10,
            "heating_rate_unit": "K/min",
            "baseline": {"method": "constant", "value": 0.01},
            "area_ranges": [[0, 100]],
        },
    )
    assert result.data["areas"][0]["enthalpy"] == pytest.approx(150.3976965, rel=1e-5)
    assert result.data["areas"][0]["unit"] == "J/g"
    assert result.data["peaks"][0]["peak_temperature"] == pytest.approx(50)
    assert result.data["peaks"][0]["onset"] == pytest.approx(40, abs=0.05)


def test_dsc_negative_endotherm_minute_time_and_non_grid_bounds():
    result = run(
        "thermal",
        pd.DataFrame({"x": [0, 1, 2, 3], "y": [-2, -2, -2, -2]}),
        config={
            "kind": "dsc",
            "x_unit": "min",
            "y_unit": "mW",
            "endotherm": "negative",
            "area_ranges": [[0.5, 2.5]],
        },
    )
    assert result.data["areas"][0]["enthalpy"] == pytest.approx(-0.24)
    assert result.data["areas"][0]["endothermic_positive_enthalpy"] == pytest.approx(0.24)
    assert result.data["areas"][0]["unit"] == "J"


def test_tg_known_mass_loss_and_stage_detection():
    x = np.linspace(0, 100, 1001)
    y = 20 - 4 / (1 + np.exp(-(x - 50) / 2))
    result = run(
        "thermal",
        pd.DataFrame({"x": x, "y": y}),
        config={"kind": "tg", "x_unit": "degC", "y_unit": "mg", "stage_threshold": 0.01},
    )
    assert result.data["total_mass_loss_percent"] == pytest.approx(20, abs=1e-5)
    assert len(result.data["stages"]) == 1
    assert result.data["stages"][0]["peak_loss_coordinate"] == pytest.approx(50)
    assert result.data["stages"][0]["onset"] == pytest.approx(46, abs=0.2)


def test_mechanical_modulus_yield_stress_units_and_measured_end():
    e = np.linspace(0, 0.02, 2001)
    stress = np.where(e <= 0.001, 200000 * e, 200 + 1000 * (e - 0.001))
    frame = pd.DataFrame({"strain": e * 100, "stress": stress / 1000})
    result = run(
        "mechanics",
        frame,
        config={"strain_unit": "%", "stress_unit": "GPa", "fit_range": [0, 0.08], "fracture_confirmed": True},
    )
    assert result.data["elastic_modulus_MPa"] == pytest.approx(200000)
    assert result.data["yield_stress_MPa"] == pytest.approx(202.01005025, abs=1e-5)
    assert result.data["ultimate_strength_MPa"] == pytest.approx(219)
    assert result.data["fracture_strain"] == pytest.approx(0.02)
    assert result.data["work_density_MJ_m3"] == pytest.approx(4.0805, abs=1e-5)
    pd.testing.assert_frame_equal(frame, pd.DataFrame({"strain": e * 100, "stress": stress / 1000}))


def test_mechanics_requires_fit_region_and_warns_missing_yield_rupture():
    frame = pd.DataFrame({"strain": [0, 0.001, 0.002, 0.003], "stress": [0, 1, 2, 3]})
    with pytest.raises(ValueError, match="fit_range"):
        run("mechanics", frame, config={"strain_unit": "fraction", "stress_unit": "MPa"})
    result = run(
        "mechanics", frame, config={"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.002]}
    )
    assert result.data["yield_stress_MPa"] is None
    assert result.data["fracture_strain"] is None
    assert len(result.warnings) >= 2


def test_morphology_calibrated_areas_and_roundtrip_mask(tmp_path):
    image = np.zeros((20, 20))
    image[2:5, 2:6] = 1
    image[10:14, 10:15] = 1
    result = run(
        "microstructure",
        config={
            "threshold": 0.5,
            "pixel_size": 2,
            "spatial_unit": "um",
            "feature": "pore",
            "output_dir": str(tmp_path),
        },
        data={"image": image},
    )
    assert result.table.area.tolist() == [48, 80]
    assert result.data["area_fraction"] == pytest.approx(0.08)
    assert result.data["porosity_area_fraction"] == pytest.approx(0.08)
    assert result.data["component_count"] == 2
    labels = np.load(result.artifacts[1])
    assert (labels > 0).sum() == 32
    assert image.sum() == 32


def test_pixel_units_and_otsu_identification(tmp_path):
    image = np.zeros((10, 10))
    image[2:4, 3:6] = 255
    result = run("sem_eds", config={"output_dir": str(tmp_path)}, data={"image": image.tolist()})
    assert result.table.area.tolist() == [6]
    assert result.data["length_unit"] == "px"
    assert any("calibration" in w for w in result.warnings)


def test_supervised_segmentation_uses_supplied_labels(tmp_path):
    image = np.zeros((20, 20))
    image[5:15, 5:15] = 1
    labels = np.full(image.shape, -1)
    labels[0:3, :] = 0
    labels[7:13, 7:13] = 1
    result = run(
        "microstructure",
        config={"segmentation": "ml", "output_dir": str(tmp_path)},
        data={"image": image, "training_labels": labels},
    )
    assert result.data["area_fraction"] == pytest.approx(0.25)
    assert result.data["segmentation"]["training_pixels"] == 96
    assert "held-out" in " ".join(result.warnings)
    with pytest.raises(ValueError, match="training_labels"):
        run("microstructure", config={"segmentation": "ml"}, data={"image": image})


def test_external_quantified_eds_table_and_csv(tmp_path):
    frame = pd.DataFrame({"element": ["Si", "O"], "wt_percent": [46.7, 53.3]})
    path = tmp_path / "quantified.csv"
    frame.to_csv(path, index=False)
    for kwargs in [{"table": frame}, {"config": {"method": "eds", "path": str(path)}}]:
        result = run("sem_eds", **({"config": {"method": "eds"}} | kwargs))
        pd.testing.assert_frame_equal(result.table, frame)
        assert result.data["quantification"] == "externally supplied"
        assert result.data["totals"]["wt_percent"] == pytest.approx(100)


@pytest.mark.parametrize(
    "config",
    [
        {"kind": "dsc", "x_unit": "degC", "y_unit": "W/g", "endotherm": "positive"},
        {"kind": "dsc", "x_unit": "s", "y_unit": "unknown", "endotherm": "positive"},
        {"kind": "dsc", "x_unit": "s", "y_unit": "W/g"},
    ],
)
def test_thermal_rejects_missing_or_incompatible_units(config):
    with pytest.raises(ValueError):
        run("thermal", pd.DataFrame({"x": [0, 1, 2], "y": [0, 1, 0]}), config=config)


def test_out_of_domain_reference_and_integral_bounds_rejected():
    frame = pd.DataFrame({"x": [0, 1, 2, 3], "y": [0, 1, 1, 0]})
    with pytest.raises(ValueError, match="cover"):
        run(
            "xrd",
            frame,
            config={"whole_pattern": "reference"},
            data={"references": [{"name": "short", "x": [1, 2], "y": [1, 1]}]},
        )
    with pytest.raises(ValueError, match="range"):
        run("spectra", frame, config={"area_ranges": [[-1, 2]]})


def test_reject_degenerate_image_calibration_and_negative_eds():
    with pytest.raises(ValueError, match="constant"):
        run("microstructure", data={"image": np.zeros((3, 3))})
    with pytest.raises(ValueError, match="pixel_size"):
        run(
            "microstructure",
            config={"threshold": 0.5, "pixel_size": 0, "spatial_unit": "um"},
            data={"image": np.eye(3)},
        )
    with pytest.raises(ValueError, match="percent"):
        run("sem_eds", pd.DataFrame({"element": ["Si"], "wt_percent": [-1]}), config={"method": "eds"})


def test_reference_nonzero_only_outside_measurement_is_rejected():
    with pytest.raises(ValueError, match="measured"):
        run(
            "xrd",
            pd.DataFrame({"x": [0, 1, 2], "y": [0, 1, 0]}),
            config={"match": "profile"},
            data={"references": [{"name": "outside", "x": [-1, 0, 1, 2, 3], "y": [1, 0, 0, 0, 1]}]},
        )


def test_yield_crossing_at_last_measured_point_is_included():
    # Exactly representable binary strains: the last point lies exactly on the shifted line.
    frame = pd.DataFrame({"strain": np.array([0, 1, 2, 4, 6]) / 1024, "stress": [0, 1, 2, 3, 4]})
    result = run(
        "mechanics",
        frame,
        config={
            "strain_unit": "fraction",
            "stress_unit": "MPa",
            "fit_range": [0, 2 / 1024],
            "yield_offset": 2 / 1024,
        },
    )
    assert result.data["yield_stress_MPa"] == pytest.approx(4)


@pytest.mark.parametrize("normalization", ["area", "l2"])
def test_spectrum_normalization_explicit_norm(normalization):
    result = run(
        "spectra", pd.DataFrame({"x": [0, 1, 2], "y": [0, 2, 0]}), config={"normalization": normalization}
    )
    assert result.table.normalized.tolist() == [0, 1, 0]


def test_image_filters_dark_pores_and_reads_actual_png(tmp_path):
    from PIL import Image

    image = np.ones((10, 10), dtype=np.uint8) * 255
    image[2:4, 2:4] = 0
    image[8, 8] = 0
    source = tmp_path / "source.png"
    Image.fromarray(image).save(source)
    before = source.read_bytes()
    result = run(
        "sem_eds",
        config={
            "path": str(source),
            "output_dir": str(tmp_path),
            "threshold": 100,
            "foreground": "dark",
            "feature": "pore",
            "min_area_pixels": 2,
        },
    )
    assert result.data["area_fraction_before_size_filter"] == pytest.approx(0.05)
    assert result.data["area_fraction"] == pytest.approx(0.04)
    assert result.table.area.tolist() == [4]
    assert source.read_bytes() == before


def test_nonuniform_smoothing_and_degenerate_elastic_fit_rejected():
    with pytest.raises(ValueError, match="evenly"):
        run(
            "spectra", pd.DataFrame({"x": [0, 1, 2, 4, 6], "y": [0, 1, 2, 1, 0]}), config={"smooth_window": 3}
        )
    with pytest.raises(ValueError):
        run(
            "mechanics",
            pd.DataFrame({"strain": [0, 1, 2, 3], "stress": [1, 1, 1, 1]}),
            config={"strain_unit": "%", "stress_unit": "MPa", "fit_range": [0, 2]},
        )

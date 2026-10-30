"""Generate explicitly synthetic fixtures, execute all six materials nodes and read back outputs.

Run from the package root: python examples/science/materials/run_demo.py
No external material database, instrument data, credentials or pretrained model is used.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from materials_quality.science import materials


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    fixtures = Path(__file__).resolve().parent / "fixtures"
    output = Path("artifacts/materials-demo").resolve()
    fixtures.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    x = np.linspace(0, 20, 401)
    a = np.exp(-0.5 * ((x - 5) / 0.5) ** 2)
    b = np.exp(-0.5 * ((x - 14) / 0.8) ** 2)
    pd.DataFrame({"x": x, "y": 2 * a + 3 * b}).to_csv(fixtures / "synthetic_xrd.csv", index=False)
    refs = [
        {"name": "synthetic-A", "x": x.tolist(), "y": a.tolist(), "source": "analytic Gaussian"},
        {"name": "synthetic-B", "x": x.tolist(), "y": b.tolist(), "source": "analytic Gaussian"},
    ]
    (fixtures / "synthetic_references.json").write_text(json.dumps({"references": refs}), encoding="utf-8")
    sx = np.linspace(-8, 8, 401)
    pd.DataFrame({"x": sx, "y": 1 + 0.02 * sx + 2 * np.exp(-(sx**2) / 2)}).to_csv(
        fixtures / "synthetic_spectrum.csv", index=False
    )
    tx = np.linspace(0, 100, 501)
    pd.DataFrame({"x": tx, "y": 20 - 4 / (1 + np.exp(-(tx - 50) / 2))}).to_csv(
        fixtures / "synthetic_tg.csv", index=False
    )
    pd.DataFrame({"x": tx, "y": 0.01 + 2 * np.exp(-0.5 * ((tx - 50) / 5) ** 2)}).to_csv(
        fixtures / "synthetic_dsc.csv", index=False
    )
    strain = np.linspace(0, 0.02, 401)
    stress = np.where(strain <= 0.001, 200000 * strain, 200 + 1000 * (strain - 0.001))
    pd.DataFrame({"strain": strain, "stress": stress}).to_csv(fixtures / "synthetic_tensile.csv", index=False)
    image = np.zeros((20, 20), dtype=np.uint8)
    image[2:5, 2:6] = 255
    image[10:14, 10:15] = 255
    Image.fromarray(image).save(fixtures / "synthetic_micrograph.png")
    labels = np.full(image.shape, -1)
    labels[0:2, :] = 0
    labels[3, 3:5] = 1
    labels[11:13, 11:14] = 1
    np.save(fixtures / "synthetic_training_labels.npy", labels, allow_pickle=False)
    pd.DataFrame({"element": ["Si", "O"], "wt_percent": [46.7, 53.3]}).to_csv(
        fixtures / "synthetic_quantified_eds.csv", index=False
    )
    inputs = {p.name: digest(p) for p in fixtures.iterdir() if p.is_file()}

    def load(name):
        return pd.read_csv(fixtures / name)

    reference_data = json.loads((fixtures / "synthetic_references.json").read_text(encoding="utf-8"))
    runs = {
        "xrd_reference": materials.xrd(
            load("synthetic_xrd.csv"),
            config={"whole_pattern": "reference", "match": "profile"},
            data=reference_data,
        ),
        "xrd_gaussian": materials.xrd(
            load("synthetic_xrd.csv"),
            config={
                "whole_pattern": "gaussian",
                "fit_peaks": [
                    {"amplitude": 2, "center": 5.1, "sigma": 0.6},
                    {"amplitude": 3, "center": 13.9, "sigma": 0.7},
                ],
            },
        ),
        "spectra": materials.spectra(
            load("synthetic_spectrum.csv"),
            config={
                "baseline": {"method": "anchors", "points": [[-8, 0.84], [8, 1.16]]},
                "smooth_window": 5,
                "normalization": "area",
                "area_ranges": [[-8, 8]],
            },
        ),
        "tg": materials.thermal(
            load("synthetic_tg.csv"),
            config={"kind": "tg", "x_unit": "degC", "y_unit": "mg", "stage_threshold": 0.01},
        ),
        "dsc": materials.thermal(
            load("synthetic_dsc.csv"),
            config={
                "kind": "dsc",
                "x_unit": "degC",
                "y_unit": "W/g",
                "endotherm": "positive",
                "heating_rate": 10,
                "heating_rate_unit": "K/min",
                "baseline": {"method": "constant", "value": 0.01},
            },
        ),
        "mechanics": materials.mechanics(
            load("synthetic_tensile.csv"),
            config={
                "strain_unit": "fraction",
                "stress_unit": "MPa",
                "fit_range": [0, 0.0008],
                "fracture_confirmed": True,
            },
        ),
        "sem": materials.sem_eds(
            config={
                "path": str(fixtures / "synthetic_micrograph.png"),
                "pixel_size": 2,
                "spatial_unit": "um",
                "output_dir": str(output / "sem"),
            }
        ),
        "eds": materials.sem_eds(
            config={"method": "eds", "path": str(fixtures / "synthetic_quantified_eds.csv")}
        ),
        "microstructure": materials.microstructure(
            config={
                "threshold": 127,
                "feature": "pore",
                "pixel_size": 2,
                "spatial_unit": "um",
                "output_dir": str(output / "microstructure"),
            },
            data={"image": image},
        ),
        "microstructure_ml": materials.microstructure(
            config={"segmentation": "ml", "feature": "pore", "output_dir": str(output / "microstructure_ml")},
            data={"image": image, "training_labels": labels},
        ),
    }
    np.testing.assert_allclose(list(runs["xrd_reference"].data["fit"]["coefficients"].values()), [2, 3])
    np.testing.assert_allclose(runs["dsc"].data["areas"][0]["enthalpy"], 150.3976965, rtol=1e-5)
    np.testing.assert_allclose(runs["mechanics"].data["elastic_modulus_MPa"], 200000)
    np.testing.assert_allclose(runs["microstructure_ml"].data["area_fraction"], 0.08)
    for name, result in runs.items():
        result.table.to_csv(output / f"{name}.csv", index=False)
        pd.testing.assert_frame_equal(
            pd.read_csv(output / f"{name}.csv"), result.table, check_dtype=False, atol=1e-10, rtol=1e-10
        )
        target = output / f"{name}.json"
        target.write_text(
            json.dumps(
                {"data": result.data, "warnings": result.warnings, "artifacts": result.artifacts},
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        assert json.loads(target.read_text(encoding="utf-8"))["data"]
        if result.artifacts:
            with Image.open(result.artifacts[0]) as saved:
                assert np.asarray(saved).astype(bool).sum() == 32
            assert (np.load(result.artifacts[1]) > 0).sum() == 32
    assert inputs == {p.name: digest(p) for p in fixtures.iterdir() if p.is_file()}
    verification = {
        "synthetic_only": True,
        "executed_variants": list(runs),
        "fixture_sha256_before_and_after": inputs,
        "readback_passed": True,
    }
    (output / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    print(json.dumps({"variants": len(runs), "verification": str(output / "verification.json")}, indent=2))


if __name__ == "__main__":
    main()

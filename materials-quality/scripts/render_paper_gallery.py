"""Reproduce six independent synthetic examples and publication-format QA artifacts."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

from materials_quality.science import visualization as viz

ROOT = Path(__file__).resolve().parents[1]


def render(output, publish_previews=False):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    strain = np.linspace(0, 0.018, 61)
    for group, modulus in [("Baseline", 180000), ("Modified", 200000)]:
        for i, factor in enumerate([0.96, 1.0, 1.04]):
            stress = (
                np.where(strain <= 0.002, modulus * strain, modulus * 0.002 + 5000 * (strain - 0.002))
                * factor
            )
            rows.extend(
                {"group": group, "specimen": f"{group}-{i + 1}", "strain": x, "stress": y}
                for x, y in zip(strain, stress, strict=True)
            )
    curves = pd.DataFrame(rows)
    curves.attrs["units"] = {"strain": "dimensionless", "stress": "MPa"}
    performance = curves.groupby(["group", "specimen"], sort=False, as_index=False).stress.max()
    performance.attrs["units"] = {"stress": "MPa"}
    x = np.linspace(20, 65, 501)
    spectra = pd.DataFrame(
        {
            "two_theta": x,
            "Baseline": np.exp(-0.5 * ((x - 32) / 1.2) ** 2) + 0.6 * np.exp(-0.5 * ((x - 50) / 1.6) ** 2),
            "Modified": np.exp(-0.5 * ((x - 34) / 1.2) ** 2) + 0.6 * np.exp(-0.5 * ((x - 50) / 1.6) ** 2),
        }
    )
    spectra.attrs["units"] = {"two_theta": "degree", "Baseline": "dimensionless", "Modified": "dimensionless"}
    observed = np.linspace(40, 150, 24)
    prediction = pd.DataFrame({"observed": observed, "predicted": observed + 5 * np.sin(observed / 35)})
    prediction.attrs["units"] = {"observed": "MPa", "predicted": "MPa"}
    correlation = prediction.assign(
        contrast=-observed, oscillation=np.sin(np.linspace(0, 4 * np.pi, len(observed)))
    )
    correlation.attrs["units"] = {
        **prediction.attrs["units"],
        "contrast": "MPa",
        "oscillation": "dimensionless",
    }
    common = {
        "profile": "paper",
        "data_kind": "synthetic",
        "width_mm": 150,
        "color_map": {"Baseline": "#0072B2", "Modified": "#D55E00"},
    }
    cases = [
        (
            "01-box",
            viz.performance,
            performance,
            {
                "method": "box",
                "y": "stress",
                "group": "group",
                "labels": {"stress": "Peak stress"},
                "title": "Specimen-level comparison",
            },
        ),
        (
            "02-bars",
            viz.performance,
            performance,
            {
                "method": "bar",
                "y": "stress",
                "group": "group",
                "labels": {"stress": "Peak stress"},
                "title": "Mean and observed spread",
            },
        ),
        (
            "03-spectra",
            viz.spectra,
            spectra,
            {
                "method": "overlay",
                "x": "two_theta",
                "columns": ["Baseline", "Modified"],
                "labels": {"two_theta": r"$2\theta$"},
                "y_label": "Normalized intensity",
                "peaks": [{"x": 32, "label": "32.0°"}],
                "title": "Peak position comparison",
            },
        ),
        (
            "04-mechanics",
            viz.mechanics,
            curves,
            {
                "method": "mean_error",
                "x": "strain",
                "y": "stress",
                "sample": "specimen",
                "group": "group",
                "error": "ci95",
                "labels": {"strain": "Strain", "stress": "Stress"},
                "title": "Specimen response and uncertainty",
            },
        ),
        (
            "05-prediction",
            viz.statistics_plot,
            prediction,
            {
                "method": "prediction",
                "y_true": "observed",
                "y_pred": "predicted",
                "title": "Supplied prediction pairs",
                "purpose": "Visualize supplied pairs; this plot does not establish a held-out test split.",
            },
        ),
        (
            "06-correlation",
            viz.statistics_plot,
            correlation,
            {
                "method": "correlation",
                "columns": ["observed", "contrast", "oscillation"],
                "title": "Association, not causation",
            },
        ),
    ]
    records = []
    for key, operation, table, config in cases:
        directory = output / key
        directory.mkdir(exist_ok=True)
        source = directory / "source.csv"
        table.to_csv(source, index=False, lineterminator="\n")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        result = operation(table, config={**common, **config, "output_dir": str(directory)})
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        assert not result.data["figure_contract"]["layout_warnings"], result.warnings
        for path in result.artifacts:
            assert Path(path).is_file()
        records.append(
            {
                "key": key,
                "config": {**common, **config, "units": table.attrs.get("units", {})},
                "source_sha256": before,
                "preview": result.data["figure_previews"][0],
                "artifacts": result.artifacts,
                "figure_contract": result.data["figure_contract"],
            }
        )
        print("Rendered " + key, flush=True)
    with matplotlib.rc_context({"font.family": "DejaVu Sans", "font.size": 11}):
        fig, axes = plt.subplots(3, 2, figsize=(12, 12.4), layout="constrained")
        for ax, record in zip(axes.flat, records, strict=True):
            ax.imshow(plt.imread(record["preview"]))
            ax.axis("off")
        fig.suptitle("Independent synthetic examples — scientific plotting gallery", fontsize=13)
        contact = output / "contact-sheet.png"
        fig.savefig(contact, dpi=160)
        plt.close(fig)
    (output / "gallery.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    if publish_previews:
        destination = ROOT / "examples/paper_figures"
        destination.mkdir(exist_ok=True)
        for record in records:
            shutil.copyfile(record["preview"], destination / (record["key"] + ".png"))
            case_dir = destination / record["key"]
            case_dir.mkdir(exist_ok=True)
            for artifact in record["artifacts"]:
                path = Path(artifact)
                target = case_dir / ("figure" + path.suffix)
                shutil.copyfile(path, target)
                if path.suffix == ".json":
                    info = json.loads(target.read_text(encoding="utf-8"))
                    info["figure_previews"] = ["figure.png"]
                    for entry in info["figure_verification"]:
                        entry["path"] = "figure." + entry["format"]
                    target.write_text(
                        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
                    )
            shutil.copyfile(output / record["key"] / "source.csv", case_dir / "source.csv")
        shutil.copyfile(contact, destination / "contact-sheet.png")
        clean = [
            {
                **r,
                "preview": r["key"] + ".png",
                "source": r["key"] + "/source.csv",
                "artifacts": [r["key"] + "/figure" + Path(p).suffix for p in r["artifacts"]],
            }
            for r in records
        ]
        (destination / "gallery.json").write_text(
            json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/paper-figures")
    parser.add_argument("--publish-previews", action="store_true")
    args = parser.parse_args()
    render(args.output, args.publish_previews)


if __name__ == "__main__":
    main()

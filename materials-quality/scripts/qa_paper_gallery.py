"""Audit shipped plot values, actual export dimensions, fonts and grayscale proofs."""

import argparse
import hashlib
import json
from pathlib import Path

import fitz
import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from PIL import Image
from scipy.stats import t

from materials_quality.context import table_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def audit(root, output):
    output.mkdir(parents=True, exist_ok=True)
    records = json.loads((root / "gallery.json").read_text(encoding="utf-8"))
    results = []
    for record in records:
        case = root / record["key"]
        info = json.loads((case / "figure.json").read_text(encoding="utf-8"))
        csv = root / record["source"]
        assert hashlib.sha256(csv.read_bytes()).hexdigest() == record["source_sha256"]
        frame = pd.read_csv(csv, float_precision="round_trip")
        frame.attrs["units"] = record["config"]["units"]
        assert table_fingerprint(frame) == info["source"]["table_sha256"]
        for file in info["figure_verification"]:
            assert hashlib.sha256((case / file["path"]).read_bytes()).hexdigest() == file["sha256"]
        data = info["plot_data"]
        if record["key"] in {"01-box", "02-bars"}:
            for group in data["groups"]:
                np.testing.assert_array_equal(group["y"], frame.loc[frame.group.eq(group["label"]), "stress"])
        elif record["key"] == "03-spectra":
            for curve in data["curves"]:
                np.testing.assert_array_equal(curve["x"], frame.two_theta)
                np.testing.assert_array_equal(curve["y"], frame[curve["label"]])
        elif record["key"] == "04-mechanics":
            for curve in data["curves"]:
                block = frame[frame.group.eq(curve["label"])]
                matrix = block.pivot(index="specimen", columns="strain", values="stress").to_numpy()
                np.testing.assert_array_equal(curve["x"], np.sort(block.strain.unique()))
                np.testing.assert_allclose(curve["y"], matrix.mean(axis=0), rtol=1e-13, atol=1e-13)
                error = matrix.std(axis=0, ddof=1) / np.sqrt(len(matrix)) * t.ppf(0.975, len(matrix) - 1)
                np.testing.assert_allclose(curve["error"], error, rtol=1e-13, atol=1e-13)
        elif record["key"] == "05-prediction":
            np.testing.assert_array_equal(data["y_true"], frame.observed)
            np.testing.assert_array_equal(data["y_pred"], frame.predicted)
        else:
            np.testing.assert_allclose(data["matrix"], frame[data["columns"]].corr().to_numpy(), rtol=1e-13)
        with Image.open(case / "figure.tiff") as image:
            assert min(image.info["dpi"]) >= 599
        with fitz.open(case / "figure.pdf") as pdf:
            assert abs(pdf[0].rect.width / 72 * 25.4 - 150) <= 0.01
            spans = [
                span
                for b in pdf[0].get_text("dict")["blocks"]
                if "lines" in b
                for line in b["lines"]
                for span in line["spans"]
                if span["text"].strip()
            ]
            assert min(s["size"] for s in spans) >= 7.9
            assert "SYNTHETIC DEMONSTRATION" in pdf[0].get_text()
            pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
            proof = output / (record["key"] + "-150mm.png")
            pixmap.save(proof)
        with matplotlib.rc_context({"font.family": "DejaVu Sans"}):
            image = plt.imread(proof)
            gray = image[..., :3] @ np.array([0.2126, 0.7152, 0.0722])
            fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), layout="constrained")
            axes[0].imshow(image)
            axes[0].set_title("Color")
            axes[1].imshow(gray, cmap="gray", vmin=0, vmax=1)
            axes[1].set_title("Grayscale")
            for ax in axes:
                ax.axis("off")
            fig.savefig(output / (record["key"] + "-grayscale.png"), dpi=150)
            plt.close(fig)
        results.append(
            {
                "case": record["key"],
                "values_verified": True,
                "source_identity_verified": True,
                "width_mm": 150,
                "minimum_pdf_text_points": min(s["size"] for s in spans),
                "tiff_dpi": 600,
                "visual_proof": proof.name,
            }
        )
    (output / "audit.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"QA passed: {len(results)} bundles; source identity, plotted values, 150 mm and fonts verified")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "examples/paper_figures")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/paper-qa")
    args = parser.parse_args()
    audit(args.root, args.output)


if __name__ == "__main__":
    main()

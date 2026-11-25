"""Generate every required figure/export submethod from synthetic fixtures."""

import argparse
import json
from pathlib import Path

import pandas as pd

from materials_quality.science import visualization as nodes


def run(output_dir):
    source = Path(__file__).resolve().parent
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    performance = pd.DataFrame(
        {
            "group": ["a"] * 4 + ["b"] * 4,
            "x": range(8),
            "value": [1, 2, 3, 4, 4, 5, 6, 7],
            "sample": [f"{i:03d}" for i in range(8)],
        }
    )
    spectra = pd.read_csv(source / "spectra.csv")
    mechanics = pd.read_csv(source / "mechanics.csv")
    predictions = pd.DataFrame({"y_true": [1, 2, 3, 4], "y_pred": [1, 3, 2, 5]})
    records, figures = [], []

    def invoke(name, method, table, config=None, data=None):
        config = {"data_kind": "synthetic", **(config or {}), "output_dir": str(output / f"{name}-{method}")}
        result = getattr(nodes, name)(table, config=config, data=data)
        records.append(
            {
                "node": name,
                "method": method,
                "config": config,
                "data": result.data,
                "artifacts": result.artifacts,
                "warnings": result.warnings,
            }
        )
        if name in {"performance", "spectra", "mechanics", "statistics_plot"}:
            figures.append(result.artifacts[0])
        return result

    for method in ["scatter", "bar", "box", "violin"]:
        invoke(
            "performance",
            method,
            performance,
            {"method": method, "x": "x", "y": "value", "group": "group", "units": {"value": "MPa"}},
        )
    for method in ["line", "overlay", "difference"]:
        invoke(
            "spectra",
            method,
            spectra,
            {
                "method": method,
                "x": "x",
                "columns": ["a", "b"],
                "peaks": [{"x": 2, "label": "synthetic peak"}],
            },
        )
    for method in ["overlay", "mean_error"]:
        invoke(
            "mechanics",
            method,
            mechanics,
            {
                "method": method,
                "x": "strain",
                "y": "stress",
                "sample": "sample",
                "group": "group",
                "units": {"stress": "MPa"},
            },
        )
    invoke(
        "mechanics",
        "explicit_grid",
        mechanics,
        {
            "method": "mean_error",
            "x": "strain",
            "y": "stress",
            "sample": "sample",
            "group": "group",
            "grid": [0, 0.005, 0.01],
            "units": {"stress": "MPa"},
        },
    )
    for method in ["histogram", "correlation", "residual", "prediction"]:
        invoke(
            "statistics_plot",
            method,
            predictions,
            {"method": method, "column": "y_true", "columns": ["y_true", "y_pred"]},
        )
    for format in ["csv", "excel"]:
        invoke(
            "export_table",
            format,
            performance,
            {"format": format, "id_columns": ["sample"], "units": {"value": "MPa"}},
        )
    invoke(
        "export_table",
        "csv_text_schema",
        pd.DataFrame({"note": ["001", "002"], "v": [1, 2]}),
        {"format": "csv"},
    )
    invoke(
        "export_table",
        "excel_formula_text",
        pd.DataFrame({"=1+1": ["=3+3"], "id": ["001"]}),
        {"format": "excel", "units": {"=1+1": "=2+2"}},
    )
    for format in ["html", "markdown"]:
        invoke(
            "export_report",
            format,
            performance,
            {"format": format},
            {
                "title": "Synthetic materials analysis demonstration",
                "sources": [
                    str(source / "spectra.csv"),
                    str(source / "mechanics.csv"),
                    "in-memory synthetic performance table",
                ],
                "parameters": {"mechanics_error": "sample standard deviation", "synthetic": True},
                "results": {
                    "material-A stress at strain 0.01": {"mean": 3, "std": 1.4142135623730951, "unit": "MPa"}
                },
                "figures": figures,
                "warnings": ["Synthetic fixtures; these are not experimental conclusions."],
            },
        )
    manifest = output / "visualization-demo.json"
    manifest.write_text(
        json.dumps({"synthetic": True, "runs": records}, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    json.loads(manifest.read_text(encoding="utf-8"))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/science-visualization-demo")
    print(run(parser.parse_args().output_dir))

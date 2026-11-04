"""Build a self-contained workflow for the DNA-origami nanogap paper data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

from lfx.graph import Graph

from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer
from components.materials_batch.series_dynamics import SeriesDynamics
from components.materials_sources.science_fixture_bundle import ScienceFixtureBundle
from materials_quality.science.catalog import component_class
from materials_quality.science.ui_config_import import config_to_form
from materials_quality.science.ui_schema import contract_for, fields_for


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = PROJECT / ".demo-runtime" / "datasets" / "cam97152"
DEFAULT_OUTPUT = PROJECT / "packages" / "materials-quality" / "examples" / "research_flows"

SOURCE_FILES = {
    "fig3_0cy5_time.csv": "repository/fig3/0cy5/fig3iiid_SERS_time dependent spectra.csv",
    "fig3_1cy3_time.csv": "repository/fig3/1cy3/fig3iv_d_SERS time dependent spectra.csv",
    "fig3_1cy5_time.csv": "repository/fig3/1cy5/fig3ii_d_SERS_time dependent spectra.csv",
    "fig3_2cy5_time.csv": "repository/fig3/2cy5/fig3i_d_SERS time dependent spectra.csv",
}

CONDITIONS = {
    "0": ("fig3_0cy5_time.csv", 0),
    "1": ("fig3_1cy3_time.csv", 1),
    "2": ("fig3_1cy5_time.csv", 2),
    "3": ("fig3_2cy5_time.csv", 3),
}
TIME_COLUMNS = ["0s", "30s", "60s", "90s", "120s", "150s"]
TIME_HEADERS = [str(value) for value in (0, 30, 60, 90, 120, 150)]


def _id(node, alias):
    node.set_id(f"{node.name}-{alias}")
    return node


class PaperFlow:
    def __init__(self, assets):
        bundle = {
            "records": [],
            "synthetic": False,
            "data": {
                "source_kind": "measured",
                "paper_doi": "10.1021/acs.nanolett.3c01016",
                "repository_handle": "1810/352700",
                "repository_license": "CC BY 4.0",
                "dataset_scope": "Figure 3 time-dependent SERS spectra for 0, 1 Cy3, 1 Cy5 and 2 Cy5 conditions",
                "analysis_boundary": "Descriptive reproduction from published CSV source data; no independent-replicate significance claim.",
            },
            "assets": {},
        }
        for name, raw in assets.items():
            bundle["assets"][name] = {
                "base64": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        packed = base64.b64encode(
            json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        self.source = _id(ScienceFixtureBundle().set(bundle_base64=packed), "dna-origami")
        self.nodes = {}
        self.operations = {}
        self.depth = {self.source.get_id(): 0}

    def _register(self, alias, node, parents):
        self.nodes[alias] = node
        self.operations[alias] = getattr(node, "ui_operation_key", node.name)
        self.depth[node.get_id()] = 1 + max(self.depth[parent.get_id()] for parent in parents)
        return node

    def science(self, alias, key, config, *, table=None, upstream=None, input_tables=None, reports=None):
        node = _id(component_class(key)(), alias)
        config = {"output_dir": "@asset:output", **config}
        if key.startswith("viz.") or key == "stats.distribution":
            config = {"profile": "paper", "data_kind": "measured", **config}
        field_paths = {field["path"] for field in fields_for(key)}
        if "output_dir" not in field_paths and not contract_for(key)["artifacts_output"]:
            config.pop("output_dir", None)
        if config.get("output_dir") == "@asset:output":
            reports = [*(reports or []), (self.source, "build_data")]
        values = config_to_form(key, config)
        parents = []
        if upstream:
            values["input_data"] = self.nodes[upstream].build_report
            parents.append(self.nodes[upstream])
        else:
            values["input_data"] = self.source.build_data
            parents.append(self.source)
        if table is not None:
            table_node, table_method = table
            values["input_table"] = getattr(table_node, table_method)
            parents.append(table_node)
        if input_tables:
            values["input_tables"] = [getattr(node, method) for node, method in input_tables]
            parents.extend(node for node, _method in input_tables)
        if reports:
            values["reports"] = [getattr(node, method) for node, method in reports]
            parents.extend(node for node, _method in reports)
        node.set(**values)
        return self._register(alias, node, parents)

    def batch_spectrum(self, alias, upstream):
        node = _id(BatchSpectrumAnalyzer(), alias)
        node.set(
            input_table=self.nodes[upstream].build_table,
            curve_column="curve_key",
            x_column="Wavelength (nm)",
            y_column="intensity_mean",
            group_column="condition_code",
            x_unit="nm",
            intensity_unit="a.u.",
            baseline_method="linear",
            baseline_value=0.0,
            smooth=False,
            smooth_window=7,
            smooth_order=2,
            auto_prominence=True,
            prominence=0.1,
            peak_distance=3,
            area_ranges=[{"lower": 550.0, "upper": 850.0}],
            normalization="none",
            lambda10_enabled=True,
            lambda10_min_nm=650.0,
            lambda10_max_nm=850.0,
            lambda10_selection="highest_prominence",
            sort=True,
            on_error="continue",
            bootstrap_samples=0,
            bootstrap_seed=0,
        )
        return self._register(alias, node, [self.nodes[upstream]])

    def series_dynamics(self, alias, upstream):
        node = _id(SeriesDynamics(), alias)
        node.set(
            input_table=self.nodes[upstream].build_table,
            curve_column="condition_code",
            time_column="time_s",
            value_column="intensity_mean",
            group_column="",
            time_unit="s",
            value_unit="a.u.",
            smoothing="none",
            smooth_window=5,
            smooth_order=2,
            spike_threshold=3.5,
            growth_min_points=3,
            growth_min_duration=0.0,
            growth_min_slope=0.0,
            change_method="window",
            change_window=2,
            change_threshold=3.0,
            hac_lags=1,
            alpha=0.05,
            sort=True,
        )
        return self._register(alias, node, [self.nodes[upstream]])

    def report(self, title):
        node = _id(component_class("export.report")(), "paper-report")
        config = config_to_form(
            "export.report",
            {
                "format": "html",
                "title": title,
                "filename": "dna-origami-nanogaps-report.html",
                "output_dir": "@asset:output",
            },
        )
        node.set(
            **config,
            input_data=self.source.build_data,
            reports=[node_.build_report for node_ in self.nodes.values() if hasattr(node_, "build_report")],
        )
        return self._register("paper-report", node, [self.source, *self.nodes.values()])

    def dump(self):
        end = self.report("DNA origami scaffolded single dyes in nanogaps: measured-data workflow")
        payload = Graph(
            start=self.source,
            end=end,
            flow_name="DNA origami scaffolded single dyes in nanogaps",
        ).dump(
            name="DNA origami scaffolded single dyes in nanogaps",
            description=(
                "Published measured CSV source data. The workflow aggregates repeated wavelength samples, "
                "extracts spectral features and summarizes time-dependent intensity descriptively."
            ),
        )
        ranks = defaultdict(int)
        for vertex in payload["data"]["nodes"]:
            depth = self.depth.get(vertex["id"], 0)
            vertex["position"] = {"x": depth * 560, "y": ranks[depth] * 620}
            ranks[depth] += 1
            vertex["type"] = "genericNode"
        return payload


def _read_assets(source_dir=None, zip_path=None):
    if source_dir:
        root = Path(source_dir).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"source directory does not exist: {root}")
        return {name: (root / name).read_bytes() for name in SOURCE_FILES}
    if zip_path:
        archive = Path(zip_path).expanduser().resolve()
        if not archive.is_file():
            raise ValueError(f"source zip does not exist: {archive}")
        with zipfile.ZipFile(archive) as source:
            return {name: source.read(member) for name, member in SOURCE_FILES.items()}
    raise ValueError("provide --source-dir or --zip containing the Cambridge repository data")


def build_flow(assets):
    flow = PaperFlow(assets)
    raw = {}
    keyed = {}
    long = {}
    for alias, (filename, condition_code) in CONDITIONS.items():
        raw[alias] = flow.science(
            f"raw-{alias}",
            "io.table_import",
            {"path": f"@asset:{filename}", "delimiter": ","},
        )
        renamed = {source: target for source, target in zip(TIME_COLUMNS, TIME_HEADERS, strict=True)}
        clipped = flow.science(
            f"clip-{alias}",
            "preprocess.filter",
            {
                "conditions": [
                    {"column": "Wavelength (nm)", "op": "ge", "value": 550},
                    {"column": "Wavelength (nm)", "op": "le", "value": 850},
                ],
                "rename": renamed,
                "derived_columns": [
                    {"column": "condition_code", "expression": str(condition_code)},
                ],
            },
            table=(raw[alias], "build_table"),
            upstream=f"raw-{alias}",
        )
        reshaped = flow.science(
            f"long-{alias}",
            "preprocess.reshape",
            {
                "method": "wide_to_long",
                "id_vars": ["Wavelength (nm)", "condition_code"],
                "value_vars": TIME_HEADERS,
                "var_name": "time_s",
                "value_name": "intensity",
            },
            table=(clipped, "build_table"),
            upstream=f"clip-{alias}",
        )
        typed = flow.science(
            f"typed-{alias}",
            "preprocess.reshape",
            {
                "method": "types",
                "types": {
                    "Wavelength (nm)": "number",
                    "condition_code": "number",
                    "time_s": "number",
                    "intensity": "number",
                },
            },
            table=(reshaped, "build_table"),
            upstream=f"long-{alias}",
        )
        keyed[alias] = flow.science(
            f"keyed-{alias}",
            "preprocess.filter",
            {
                "derived_columns": [
                    {
                        "column": "curve_key",
                        "expression": "condition_code * 1000 + time_s",
                        "unit": "dimensionless",
                    }
                ]
            },
            table=(typed, "build_table"),
            upstream=f"typed-{alias}",
        )
        long[alias] = keyed[alias]

    merged = flow.science(
        "merged-long",
        "preprocess.merge",
        {"method": "append", "ignore_index": True},
        upstream="keyed-0",
        input_tables=[(long[alias], "build_table") for alias in ("0", "1", "2", "3")],
    )
    spectrum_stats = flow.science(
        "spectrum-stats",
        "stats.grouped",
        {
            "group": "condition_code",
            "group_by": ["condition_code", "curve_key", "time_s", "Wavelength (nm)"],
            "columns": ["intensity"],
            "output_format": "wide",
            "units": {"intensity": "a.u."},
        },
        table=(merged, "build_table"),
        upstream="merged-long",
    )
    time_stats = flow.science(
        "time-stats",
        "stats.grouped",
        {
            "group": "condition_code",
            "group_by": ["condition_code", "time_s"],
            "columns": ["intensity"],
            "output_format": "wide",
            "units": {"intensity": "a.u."},
        },
        table=(merged, "build_table"),
        upstream="merged-long",
    )
    analyzer = flow.batch_spectrum("spectrum-analysis", "spectrum-stats")
    series = flow.series_dynamics("time-analysis", "time-stats")
    spectra_figure = flow.science(
        "spectral-band-figure",
        "viz.spectra",
        {
            "method": "band",
            "x": "x",
            "y": "corrected",
            "curve_id": "curve_id",
            "group": "group",
            "band": "iqr",
            "grid": list(range(550, 851)),
            "title": "Time-dependent SERS spectra by dye condition",
            "purpose": "Compare the measured spectral envelopes across the four published conditions.",
            "evidence_role": "comparison",
        },
        table=(analyzer, "build_curves"),
        upstream="spectrum-analysis",
    )
    primary = flow.science(
        "primary-peaks",
        "preprocess.filter",
        {"conditions": [{"column": "is_primary", "op": "eq", "value": True}]},
        table=(analyzer, "build_features"),
        upstream="spectrum-analysis",
    )
    area_stats = flow.science(
        "area-stats",
        "stats.grouped",
        {
            "group": "group",
            "group_by": ["group"],
            "columns": ["area"],
            "output_format": "wide",
            "units": {"area": "a.u.*nm"},
        },
        table=(primary, "build_table"),
        upstream="primary-peaks",
    )
    area_figure = flow.science(
        "area-box-figure",
        "viz.performance",
        {
            "method": "box",
            "y": "area",
            "group": "group",
            "title": "Primary spectral area by dye condition",
            "purpose": "Show the distribution of one primary feature per analyzed spectrum.",
            "evidence_role": "comparison",
        },
        table=(primary, "build_table"),
        upstream="primary-peaks",
    )
    time_figure = flow.science(
        "time-scatter-figure",
        "viz.performance",
        {
            "method": "scatter",
            "x": "time_s",
            "y": "intensity_mean",
            "group": "condition_code",
            "title": "Mean measured spectral intensity over time",
            "purpose": "Summarize the measured time-dependent intensity changes without inferential pooling.",
            "evidence_role": "comparison",
        },
        table=(time_stats, "build_table"),
        upstream="time-stats",
    )
    flow.science(
        "features-csv",
        "export.table",
        {"format": "csv", "filename": "primary-spectral-features.csv", "id_columns": ["curve_id"]},
        table=(primary, "build_table"),
        upstream="primary-peaks",
    )
    flow.science(
        "time-features-csv",
        "export.table",
        {"format": "csv", "filename": "time-series-features.csv", "id_columns": ["curve_id"]},
        table=(series, "build_features"),
        upstream="time-analysis",
    )
    return flow.dump()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "03-dna-origami-nanogaps.json")
    args = parser.parse_args(argv)
    source_dir = args.source_dir if args.source_dir and args.source_dir.is_dir() else None
    assets = _read_assets(source_dir=source_dir, zip_path=args.zip_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_flow(assets), ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()

"""Build and verify portable, connected Langflow science examples from the repository root."""

import argparse
import base64
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from lfx.graph import Graph
from PIL import Image

from examples.science_flows.fixture_source import ScienceFixtureBundle
from materials_quality.science.catalog import component_class, entries
from materials_quality.science.ui_config_import import config_to_form
from materials_quality.science.ui_schema import REPORT_COLLECTION_KEYS, contract_for, fields_for

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "examples/science_flows"
IO = ROOT / "examples/science/io/fixtures"
MAT = ROOT / "examples/science/materials/fixtures"
CATALOG = {item["key"]: item for item in entries()}


def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class Flow:
    def __init__(self, slug, title, *, records=None, data=None, assets=None):
        self.slug, self.title = slug, title
        bundle = {"records": records or [], "data": data or {}, "assets": {}}
        for name, content in (assets or {}).items():
            raw = content.read_bytes() if isinstance(content, Path) else content
            bundle["assets"][name] = {
                "base64": base64.b64encode(raw).decode("ascii"),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        packed = base64.b64encode(encoded(bundle).encode("utf-8")).decode("ascii")
        self.source = ScienceFixtureBundle().set(bundle_base64=packed)
        self.source.set_id(f"ScienceFixtureBundle-{slug}")
        self.nodes = {}
        self.depth = {self.source.get_id(): 0}
        self.operations = {}

    def add(self, alias, key, config=None, *, table=None, upstream=None, tables=(), reports=()):
        node = component_class(key)()
        node.set_id(f"{node.name}-{alias}")
        config = {"output_dir": "@asset:output", **(config or {})}
        if key.startswith("viz.") or key == "stats.distribution":
            config = {"profile": "paper", "data_kind": "synthetic", **config}
        task = None
        if (
            key == "stats.predict"
            and upstream
            and self.operations[upstream] in {"stats.regression", "stats.predict"}
        ):
            task = "saved"
        paths = {field["path"] for field in fields_for(key)}
        # The previous builder injected this key into every operation. Remove it
        # only where it cannot direct a generated file; all other keys stay exact.
        conditional_no_files = (
            task == "saved"
            or key == "stats.evaluate" and bool(config.get("y_true") and config.get("y_pred"))
            or key == "materials.sem_eds" and config.get("method") == "eds"
        )
        if conditional_no_files or not contract_for(key)["artifacts_output"] and "output_dir" not in paths:
            config.pop("output_dir", None)
        data_node = self.nodes[upstream] if upstream else self.source
        inputs = {
            **config_to_form(key, config, task=task),
            "input_data": data_node.build_report if upstream else self.source.build_data,
        }
        parents = [data_node]
        if table is not None:
            table_node = self.source if table == "fixture" else self.nodes[table]
            inputs["input_table"] = table_node.build_table
            parents.append(table_node)
        if tables:
            inputs["input_tables"] = [self.nodes[t].build_table for t in tables]
            parents.extend(self.nodes[t] for t in tables)
        if reports:
            if key not in REPORT_COLLECTION_KEYS:
                raise ValueError(f"{key} does not accept a report collection")
            inputs["reports"] = [self.nodes[r].build_report for r in reports]
            parents.extend(self.nodes[r] for r in reports)
        node.set(**inputs)
        self.nodes[alias] = node
        self.operations[alias] = key
        self.depth[node.get_id()] = 1 + max(self.depth[p.get_id()] for p in parents)
        return alias

    def dump(self):
        sink = self.add(
            "report", "export.report", {"format": "html", "title": self.title}, reports=list(self.nodes)
        )
        graph = Graph(start=self.source, end=self.nodes[sink], flow_name=self.title)
        payload = graph.dump(
            name=self.title,
            description="内嵌合成输入。运行后检查每个节点的结果与追溯，并打开最终 HTML 报告。",
        )
        count = Counter()
        for vertex in payload["data"]["nodes"]:
            depth = self.depth[vertex["id"]]
            vertex["position"] = {"x": depth * 575, "y": count[depth] * 740}
            count[depth] += 1
            vertex["type"] = "genericNode"
        return payload


def table_flow():
    f = Flow(
        "01-tables",
        "01 表格整理与单位换算（合成）",
        assets={"samples.csv": b"sample,value\nA1,12\nB2,\nC3,56\n", "samples.sqlite": IO / "samples.sqlite"},
    )
    f.add("csv", "io.table_import", {"path": "@asset:samples.csv"})
    f.add(
        "sql",
        "io.database_import",
        {
            "method": "sqlite",
            "path": "@asset:samples.sqlite",
            "query": "SELECT sample, value AS reference_MPa FROM samples",
        },
    )
    f.add(
        "types",
        "preprocess.reshape",
        {"method": "types", "types": {"value": "number"}},
        table="csv",
        upstream="csv",
    )
    f.add(
        "fill",
        "preprocess.missing",
        {"method": "median", "columns": ["value"]},
        table="types",
        upstream="types",
    )
    f.add(
        "units",
        "preprocess.units",
        {"source_units": {"value": "MPa"}, "target_units": {"value": "kPa"}},
        table="fill",
        upstream="fill",
    )
    f.add("select", "preprocess.filter", {"rename": {"value": "value_kPa"}}, table="units", upstream="units")
    f.add(
        "join",
        "preprocess.merge",
        {"method": "join", "on": ["sample"]},
        tables=["select", "sql"],
        reports=["select", "sql"],
    )
    f.add(
        "scale",
        "preprocess.normalize",
        {"method": "minmax", "columns": ["value_kPa"]},
        table="join",
        upstream="join",
    )
    f.add(
        "csvout", "export.table", {"format": "csv", "id_columns": ["sample"]}, table="scale", upstream="scale"
    )
    return f


def documents_flow():
    f = Flow(
        "02-documents",
        "02 PDF 与定宽文本提取（合成）",
        assets={"native.pdf": IO / "native.pdf", "fixed.txt": IO / "fixed-width.txt"},
    )
    f.add("pdf", "io.pdf_import", {"path": "@asset:native.pdf"})
    f.add("text", "extract.pdf_text", {"method": "native"}, upstream="pdf")
    f.add("grid", "extract.pdf_tables", {"method": "lines"}, upstream="pdf")
    f.add(
        "fixed",
        "io.text_import",
        {"path": "@asset:fixed.txt", "method": "fixed_width", "widths": [2, 4], "names": ["sample", "value"]},
    )
    f.add("convert", "extract.convert_file", {"target": "csv"}, table="fixed", upstream="fixed")
    return f


def images_flow():
    f = Flow(
        "03-images",
        "03 图像 OCR、表格与标定曲线（合成）",
        assets={"table.png": IO / "table.png", "curve.png": IO / "curve.png"},
    )
    f.add("image", "io.image_import", {"path": "@asset:table.png"})
    f.add("words", "extract.image_ocr", {}, upstream="image")
    f.add("grid", "extract.image_tables", {}, upstream="image")
    f.add(
        "digitize",
        "extract.chart_digitize",
        {
            "path": "@asset:curve.png",
            "color": [255, 0, 0],
            "color_tolerance": 5,
            "calibration": {"x": [[20, 0], [120, 10]], "y": [[120, 0], [20, 100]]},
        },
    )
    f.add("digitized-csv", "export.table", {"format": "csv"}, table="digitize", upstream="digitize")
    return f


def spectra_flow():
    raw = pd.read_csv(MAT / "synthetic_xrd.csv")
    xy = raw.to_csv(index=False, header=False, sep=" ").encode()
    refs = json.loads((MAT / "synthetic_references.json").read_text(encoding="utf-8"))
    f = Flow(
        "04-spectra",
        "04 仪器衍射与振动光谱（合成）",
        data=refs,
        assets={"mixture.xy": xy, "spectrum.csv": MAT / "synthetic_spectrum.csv"},
    )
    f.add("instrument", "io.instrument_import", {"path": "@asset:mixture.xy"})
    f.add(
        "xrd",
        "materials.xrd",
        {"whole_pattern": "reference", "match": "profile"},
        table="instrument",
        reports=["instrument"],
    )
    f.add("spectrum", "io.table_import", {"path": "@asset:spectrum.csv"})
    f.add(
        "raman",
        "materials.spectra",
        {"baseline": {"method": "linear"}, "normalization": "max", "area_ranges": [[-8, 8]]},
        table="spectrum",
        upstream="spectrum",
    )
    f.add(
        "overlay",
        "viz.spectra",
        {
            "method": "overlay",
            "x": "x",
            "columns": ["raw_y", "corrected"],
            "title": "Raw and baseline-corrected spectrum",
        },
        table="raman",
        upstream="raman",
    )
    return f


def mechanical_flow():
    records = pd.read_csv(MAT / "synthetic_tensile.csv").assign(specimen="synthetic-1").to_dict("records")
    f = Flow(
        "05-mechanics-thermal",
        "05 拉伸与热分析（合成）",
        records=records,
        assets={"dsc.csv": MAT / "synthetic_dsc.csv"},
    )
    f.add(
        "mechanics",
        "materials.mechanics",
        {"strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, 0.0008]},
        table="fixture",
    )
    f.add(
        "curve",
        "viz.mechanics",
        {"method": "overlay", "x": "strain", "y": "stress", "sample": "specimen", "units": {"stress": "MPa"}},
        table="fixture",
        upstream="mechanics",
    )
    f.add("heat", "io.table_import", {"path": "@asset:dsc.csv"})
    f.add(
        "dsc",
        "materials.thermal",
        {
            "kind": "dsc",
            "x_unit": "degC",
            "y_unit": "W/g",
            "endotherm": "positive",
            "heating_rate": 10,
            "heating_rate_unit": "K/min",
            "baseline": {"method": "constant", "value": 0.01},
        },
        table="heat",
        upstream="heat",
    )
    return f


def morphology_flow():
    f = Flow(
        "06-morphology",
        "06 显微孔隙与 EDS 成分（合成）",
        assets={
            "micrograph.png": MAT / "synthetic_micrograph.png",
            "composition.csv": MAT / "synthetic_quantified_eds.csv",
        },
    )
    f.add("image", "io.image_import", {"path": "@asset:micrograph.png"})
    f.add(
        "pores",
        "materials.microstructure",
        {"feature": "pore", "threshold": 127, "pixel_size": 2, "spatial_unit": "um"},
        upstream="image",
    )
    # read_path accepts path/file_path identically; EDS exposes the latter in its native form.
    f.add("eds", "materials.sem_eds", {"method": "eds", "file_path": "@asset:composition.csv"})
    f.add(
        "areas",
        "export.table",
        {"format": "excel", "units": {"area": "um^2"}},
        table="pores",
        upstream="pores",
    )
    return f


def statistics_flow():
    groups = pd.read_csv(ROOT / "examples/science/statistics/groups.csv", dtype={"sample": str})
    f = Flow("07-statistics", "07 分组统计与组间比较（合成）", records=groups.to_dict("records"))
    f.add("grouped", "stats.grouped", {"group": "group", "columns": ["value"]}, table="fixture")
    f.add("distribution", "stats.distribution", {"column": "value"}, table="fixture")
    f.add("correlation", "stats.correlation", {"columns": ["x", "y"], "method": "pearson"}, table="fixture")
    f.add(
        "anova",
        "stats.significance",
        {"group": "group", "column": "value", "method": "anova", "subject": "sample"},
        table="fixture",
    )
    f.add(
        "tukey",
        "stats.multiple",
        {"group": "group", "column": "value", "method": "tukey"},
        table="fixture",
        upstream="anova",
    )
    f.add(
        "box",
        "viz.performance",
        # The box branch uses group/y; x is read only for scatter plots.
        {"method": "box", "group": "group", "y": "value"},
        table="fixture",
        reports=["grouped", "tukey"],
    )
    return f


def model_flow():
    rows = [
        {
            "sample": f"S{i:02d}",
            "x": i / 5,
            "y": 2 * i / 5 + 3,
            "partition": "external" if i % 5 == 4 else "development",
        }
        for i in range(50)
    ]
    f = Flow("08-model", "08 线性回归、保存模型预测与评估（合成）", records=rows)
    for alias in ("development", "external"):
        f.add(
            alias,
            "preprocess.filter",
            {"conditions": [{"column": "partition", "op": "eq", "value": alias}]},
            table="fixture",
        )
    f.add(
        "train",
        "stats.regression",
        {"method": "linear", "features": ["x"], "target": "y", "id_column": "sample", "seed": 42},
        table="development",
        upstream="development",
    )
    f.add("predict", "stats.predict", {}, table="external", upstream="train", reports=["external"])
    f.add(
        "evaluate", "stats.evaluate", {"y_true": "y", "y_pred": "y_pred"}, table="predict", upstream="predict"
    )
    f.add(
        "plot",
        "viz.statistics",
        {"method": "prediction", "y_true": "y", "y_pred": "y_pred"},
        table="predict",
        reports=["evaluate"],
    )
    return f


def literature_flow():
    docs = [
        {
            "source_id": f"synthetic-{label}",
            "page": page,
            "table_id": f"T{page}",
            "text": (
                f"Title: Synthetic ZnO {label}\nAuthors: A Li; B Wu\nYear: 2024\n"
                f"ZnO grown by sputtering at 300 K has strength {value}."
            ),
        }
        for label, page, value in [("a", 2, "100 MPa"), ("b", 3, "0.12 GPa")]
    ]
    f = Flow("09-literature", "09 合成文献证据、单位对齐与摘要", data={"documents": docs})
    f.add("search", "lit.search", {"provider": "local", "method": "boolean", "query": "ZnO AND NOT GaN"})
    f.add("metadata", "lit.metadata", {"provider": "local"}, table="search", upstream="search")
    pattern = (
        r"(?P<material>ZnO) grown by (?P<preparation>sputtering) at "
        r"(?P<test_condition>300 K) has strength (?P<value>\d+(?:\.\d+)?) (?P<unit>MPa|GPa)"
    )
    f.add(
        "extract",
        "lit.extract",
        {"method": "regex", "patterns": {"strength": pattern}},
        table="search",
        upstream="search",
    )
    f.add(
        "compare", "lit.compare", {"target_units": {"strength": "MPa"}}, table="extract", upstream="extract"
    )
    f.add("sources", "lit.sources", {"save": True}, upstream="extract")
    f.add("summary", "lit.summary", {"question": "strength", "top_k": 2}, upstream="sources")
    return f


FACTORIES = [
    table_flow,
    documents_flow,
    images_flow,
    spectra_flow,
    mechanical_flow,
    morphology_flow,
    statistics_flow,
    model_flow,
    literature_flow,
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all", help="all or a numbered flow slug")
    parser.add_argument("--verify", action="store_true", help="reopen serialized graphs and execute them")
    parser.add_argument(
        "--verify-only", action="store_true", help="execute existing JSONs without rebuilding"
    )
    args = parser.parse_args()
    if args.verify_only:
        if args.case == "all":
            results = verify_committed_flows()
            print(f"Verified {len(results)} committed flows covering {len(CATALOG)} operations")
        else:
            result = verify_flow(DEST / (args.case + ".json"))
            print(encoded(result["evidence"]))
        return
    covered = set()
    results = {}
    for factory in FACTORIES:
        flow = factory()
        if args.case not in {"all", flow.slug}:
            continue
        payload = flow.dump()
        path = DEST / (flow.slug + ".json")
        raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        if re.search(r"[A-Za-z]:\\\\", raw) or str(ROOT).replace("\\", "/") in raw:
            raise ValueError(f"Host path in serialized flow {flow.slug}")
        path.write_text(raw, encoding="utf-8", newline="\n")
        print(f"Built {path.name}: {len(flow.operations)} science nodes", flush=True)
        covered.update(flow.operations.values())
        if args.verify:
            results[flow.slug] = verify_flow(path)
            print(f"Verified {path.name}", flush=True)
    if args.case == "all" and covered != set(CATALOG):
        raise RuntimeError(f"Missing operations: {set(CATALOG) - covered}")
    if not covered:
        parser.error("Unknown --case")
    if results:
        report = {"verified_flows": len(results), "operation_count": len(covered), "flows": results}
        if args.case == "all":
            target = DEST / "verification.json"
            target.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
            )


def verify_committed_flows(directory=DEST):
    """Reopen all nine delivered JSONs directly. Usable from CI and pytest."""
    paths = sorted(Path(directory).glob("[0-9][0-9]-*.json"))
    if len(paths) != len(FACTORIES):
        raise ValueError(f"Expected {len(FACTORIES)} committed flows, found {len(paths)}")
    results = {path.stem: verify_flow(path) for path in paths}
    covered = {key for result in results.values() for key in result["operations"].values()}
    if covered != set(CATALOG):
        raise ValueError(f"Unexpected committed flow coverage: {set(CATALOG) ^ covered}")
    return results


def verify_flow(path):
    """Verify only the on-disk payload; the original fixture files are not consulted."""
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    operations, node_ids = {}, {}
    classes = {item["class_name"]: key for key, item in CATALOG.items()}
    source = None
    for node in payload["data"]["nodes"]:
        cls = node["data"]["type"]
        if cls == "ScienceFixtureBundle":
            source = node
            continue
        alias = node["id"].removeprefix(cls + "-")
        operations[alias], node_ids[alias] = classes[cls], node["id"]
    if source is None:
        raise ValueError("Missing portable fixture source")
    source_id = source["id"]
    packed = source["data"]["node"]["template"]["bundle_base64"]["value"]
    bundle = json.loads(base64.b64decode(packed, validate=True))
    graph = Graph.from_payload(payload)
    for step in graph.start():
        if hasattr(step, "valid") and not step.valid:
            raise RuntimeError(f"Graph failure in {path.stem}: {step}")
    reports = {}
    artifacts = []
    for alias, key in operations.items():
        vertex = graph.get_vertex(node_ids[alias])
        envelope = vertex.results["report"].data
        assert envelope["operation"] == key and envelope["execution_status"] == "completed"
        assert envelope["schema_version"] == "science-result/1"
        assert envelope["provenance"]["lineage"][-1]["operation"] == key
        reports[alias] = envelope
        for artifact in envelope["artifacts"]:
            artifacts.append(read_artifact(Path(artifact)))
    final = reports["report"]
    assert final["data"]["verified"]
    assert set(operations.values()) <= {item["operation"] for item in final["provenance"]["lineage"]}
    fixture_data = graph.get_vertex(source_id).results["data"].data
    for name, blob in bundle["assets"].items():
        materialized = Path(fixture_data["asset_paths"][name]).read_bytes()
        assert hashlib.sha256(materialized).hexdigest() == blob["sha256"]
    evidence = verify_values(path.stem, reports, graph, node_ids)
    return {
        "operations": operations,
        "edges": len(graph.edges),
        "artifacts_read_back": artifacts,
        "fixture_hashes_rechecked": len(bundle["assets"]),
        "evidence": evidence,
    }


def read_artifact(path):
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"Empty artifact {path.name}")
    if path.suffix in {".png", ".tiff"}:
        with Image.open(path) as image:
            image.load()
            assert min(image.size) > 0
            if path.suffix == ".tiff":
                assert min(image.info["dpi"]) >= 599
    elif path.suffix == ".svg":
        from xml.etree import ElementTree as ET

        assert ET.parse(path).getroot().tag.endswith("svg")
    elif path.suffix == ".pdf":
        import fitz

        with fitz.open(path) as document:
            assert len(document) == 1 and document[0].rect.width > 0
    elif path.suffix == ".csv":
        assert len(pd.read_csv(path).columns)
    elif path.suffix == ".xlsx":
        assert len(pd.read_excel(path).columns)
    elif path.suffix == ".json":
        json.loads(raw)
    elif path.suffix == ".npy":
        assert np.load(path, allow_pickle=False).ndim == 2
    elif path.suffix == ".skops":
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
    elif path.suffix == ".html":
        html = raw.decode("utf-8")
        assert all(title in html for title in ["Data sources", "Node parameters", "Results", "Warnings"])
    return {"name": path.name, "bytes": len(raw), "format": path.suffix}


def verify_values(slug, reports, graph, node_ids):
    def info(alias):
        return reports[alias]["data"]

    def table(alias):
        return graph.get_vertex(node_ids[alias]).results["table"]

    if slug.startswith("01-"):
        frame = pd.read_csv(reports["csvout"]["artifacts"][0])
        np.testing.assert_allclose(frame.sort_values("sample").value_kPa, [0, 0.5, 1])
        return {"normalized_values": [0, 0.5, 1]}
    if slug.startswith("02-"):
        assert reports["text"]["table_summary"]["rows"] and reports["grid"]["table_summary"]["rows"]
        assert len(pd.read_csv(reports["convert"]["artifacts"][0])) > 0
        return {"native_text_and_table": True}
    if slug.startswith("03-"):
        assert reports["words"]["table_summary"]["rows"] >= 2
        assert reports["grid"]["table_summary"]["rows"] >= 2
        curve = pd.read_csv(reports["digitized-csv"]["artifacts"][0])
        assert len(curve) == 101
        np.testing.assert_allclose(curve.y, 10 * curve.x, atol=1e-9)
        return {"ocr_rows": reports["words"]["table_summary"]["rows"], "curve_points": len(curve)}
    if slug.startswith("04-"):
        coefficients = info("xrd")["fit"]["coefficients"]
        np.testing.assert_allclose([coefficients["synthetic-A"], coefficients["synthetic-B"]], [2, 3])
        np.testing.assert_allclose(info("raman")["areas"][0]["area"], 5.01325655, rtol=1e-4)
        return {"reference_coefficients": coefficients, "spectrum_area": info("raman")["areas"][0]["area"]}
    if slug.startswith("05-"):
        modulus = info("mechanics")["elastic_modulus_MPa"]
        enthalpy = info("dsc")["areas"][0]["enthalpy"]
        np.testing.assert_allclose([modulus, enthalpy], [200000, 150.39769648], rtol=1e-6)
        return {"modulus_MPa": modulus, "enthalpy_J_g": enthalpy}
    if slug.startswith("06-"):
        np.testing.assert_allclose(info("pores")["area_fraction"], 0.08)
        assert info("eds")["totals"]["wt_percent"] == 100
        assert (np.load(reports["pores"]["artifacts"][1]) > 0).sum() == 32
        return {"foreground_pixels": 32, "EDS_wt_total": 100}
    if slug.startswith("07-"):
        assert reports["grouped"]["table_summary"]["rows"] >= 3
        assert reports["tukey"]["table_summary"]["rows"] == 3
        return {"group_count": 3, "pairwise_comparisons": 3}
    if slug.startswith("08-"):
        metrics = info("evaluate")["metrics"]
        assert metrics["r2"] > 0.99999999 and metrics["mae"] < 1e-8
        assert info("predict")["n"] == 10
        assert not set(info("train")["train_ids"]) & set(table("predict")["sample"])
        return {"external_rows": 10, "r_squared": metrics["r2"], "mae": metrics["mae"]}
    normalized = table("extract")
    assert normalized is not None and len(normalized) == 2
    assert len(info("compare")["conflicts"]) == 1
    assert {r["source_id"] for r in info("summary")["points"]} == {"synthetic-a", "synthetic-b"}
    return {"evidence_points": 2, "aligned_conflicts": 1}


if __name__ == "__main__":
    main()

"""Separate workflow construction, method contracts, cold replay and numeric checks.

Nine attributed instrument files. Reference mode builds fixed editable flows;
--live measures an external Agent on explicitly prepared real measurement tables.
Replays freeze the graph and run in fresh Python processes without model access.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from materials_quality.agent.file_workflow_client import FileWorkflowClient
from materials_quality.agent.harness import StudyUIAgent
from materials_quality.agent.model import ChatModel
from materials_quality.agent.workflow import apply_actions
from materials_quality.material_examples import compile_example, examples, prepared_input, read_source
from materials_quality.science.catalog import component_class


def catalog():
    keys = [
        "io.table_import",
        "io.instrument_import",
        "preprocess.filter",
        "materials.mechanics",
        "materials.spectra",
        "materials.xrd",
        "viz.spectra",
        "export.table",
        "export.report",
    ]
    return {
        "materials_analysis": {
            component_class(k)().name: component_class(k)().to_frontend_node()["data"]["node"] for k in keys
        }
    }


def reference_peaks(x, y, threshold):
    """Direct definition of local maxima and topographic prominence, no SciPy calls."""
    selected = []
    i = 1
    while i < len(y) - 1:
        end = i
        while end + 1 < len(y) and y[end + 1] == y[i]:
            end += 1
        if y[i] > y[i - 1] and end + 1 < len(y) and y[end] > y[end + 1]:
            left, right = i - 1, end + 1
            while left > 0 and y[left - 1] <= y[i]:
                left -= 1
            while right < len(y) - 1 and y[right + 1] <= y[i]:
                right += 1
            prominence = y[i] - max(min(y[left : i + 1]), min(y[end : right + 1]))
            if prominence >= threshold:
                selected.append(float(x[(i + end) // 2]))
        i = end + 1
    return selected


def numeric_reference(item, observed):
    """Independent source parser and closed-form arithmetic, outside the node code."""
    from io import BytesIO, StringIO

    raw = read_source(item["id"])
    if item["protocol"]["task"] == "mechanics":
        frame = pd.read_excel(BytesIO(raw), sheet_name="Sheet2", header=1)
        p = item["preparation"]
        x = frame[p["extension_column"]].to_numpy(float) / p["gauge_mm"]
        y = frame[p["force_column"]].to_numpy(float) / p["area_mm2"]
        select = (frame.Index <= p["last_index"]) & (x >= p["strain_range"][0]) & (x <= p["strain_range"][1])
        order = np.argsort(x[select], kind="stable")
        x, y = x[select][order], y[select][order]
        lo, hi = item["protocol"]["fit_range"]
        a, b = x[(x >= lo) & (x <= hi)], y[(x >= lo) & (x <= hi)]
        slope = float(sum((a - a.mean()) * (b - b.mean())) / sum((a - a.mean()) ** 2))
        intercept = float(b.mean() - slope * a.mean())
        delta = y - (slope * (x - 0.002) + intercept)
        offset = None
        for index in range(len(x) - 1):
            if delta[index] > 0 >= delta[index + 1] and x[index + 1] > hi:
                fraction = delta[index] / (delta[index] - delta[index + 1])
                root = x[index] + fraction * (x[index + 1] - x[index])
                if root >= 0.002 and root > hi:
                    offset = float(y[index] + fraction * (y[index + 1] - y[index]))
                    break
        expected = [slope, offset]
        valid = offset is not None and np.allclose(observed, expected, rtol=1e-8, atol=1e-7)
        return {
            "passed": bool(valid),
            "expected": expected,
            "reference": "closed_form_OLS_and_segment_intersection",
            "instrument_summary": item["instrument_summary"],
            "modulus_difference_from_instrument_percent": 100
            * (slope / item["instrument_summary"]["modulus_MPa"] - 1),
        }
    text = raw.decode("cp1252" if item["protocol"]["task"] == "spectra" else "utf-8-sig")
    array = np.loadtxt(StringIO(text), comments="#")
    expected = reference_peaks(array[:, 0], array[:, 1], item["protocol"]["prominence"])
    valid = len(observed) == len(expected) and np.allclose(sorted(observed), expected, rtol=0, atol=1e-9)
    return {
        "passed": bool(valid),
        "expected_peak_positions": expected,
        "reference": "direct_local_maximum_and_topographic_prominence_definition",
    }


def method_contract(flow, item):
    nodes = flow["data"]["nodes"]
    expected_type = (
        "ScienceMaterials"
        + {"mechanics": "Mechanics", "spectra": "Spectra", "xrd": "Xrd"}[item["protocol"]["task"]]
    )
    analyses = [n for n in nodes if n["data"]["type"] == expected_type]
    if len(analyses) != 1:
        return False
    fields = analyses[0]["data"]["node"]["template"]
    p = item["protocol"]
    values = {"cfg_x": p["x"], "cfg_y": p["y"]}
    if p["task"] == "mechanics":
        values.update(
            cfg_strain_unit="fraction",
            cfg_stress_unit="MPa",
            cfg_fit_range_min=0.0005,
            cfg_fit_range_max=0.001,
            cfg_yield_offset=0.002,
            cfg_sort="是",
        )
    else:
        values.update(cfg_x_unit=p["x_unit"], cfg_baseline_method="none", cfg_prominence=100)
    # Some LFX bool controls expose a native bool, others the Chinese selector.
    return all(
        fields.get(k, {}).get("value") == v or (k == "cfg_sort" and fields.get(k, {}).get("value") is True)
        for k, v in values.items()
    )


def replay(manifest_path, output):
    from lfx.graph import Graph

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    records = []
    Path(output).write_text("[]", encoding="utf-8")
    for entry in manifest:
        started = time.monotonic()
        row = {"id": entry["id"], "execution": False}
        try:
            raw = Path(entry["flow_file"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == entry["flow_sha256"], "Frozen graph changed"
            graph = Graph.from_payload(json.loads(raw))
            for step in graph.start():
                if hasattr(step, "valid") and not step.valid:
                    raise ValueError("Native graph execution failed")
            flow = json.loads(raw)
            node = next(
                n
                for n in flow["data"]["nodes"]
                if n["data"]["type"]
                in {"ScienceMaterialsMechanics", "ScienceMaterialsSpectra", "ScienceMaterialsXrd"}
            )
            results = graph.get_vertex(node["id"]).results
            data = results["report"].data["data"]
            row["observed"] = (
                [data["elastic_modulus_MPa"], data["yield_stress_MPa"]]
                if entry["task"] == "mechanics"
                else results["features"]["peak_position"].tolist()
            )
            row["result_table_sha256"] = hashlib.sha256(
                results["table"].to_csv(index=False, float_format="%.12g").encode()
            ).hexdigest()
            exports = [n for n in flow["data"]["nodes"] if n["data"]["type"] == "ScienceExportReport"]
            artifacts = [
                p for n in exports for p in graph.get_vertex(n["id"]).results["report"].data["artifacts"]
            ]
            row["execution"] = bool(artifacts) and all(
                Path(p).is_file() and Path(p).stat().st_size > 0 for p in artifacts
            )
        except Exception as exc:
            row.update(error_type=type(exc).__name__, error=str(exc)[:500])
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        records.append(row)
        Path(output).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def evaluate(output, live=False, repeats=3):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    installed = catalog()
    rows, manifest = [], []
    for item in examples():
        runroot = output / item["id"]
        runroot.mkdir(exist_ok=True)
        source = runroot / item["filename"]
        source.write_bytes(read_source(item["id"]))
        client = FileWorkflowClient(
            runroot / "flows", runroot / "components", catalog_loader=lambda: installed
        )
        started = time.monotonic()
        row = {"id": item["id"], "workflow_built": False, "method_contract": False}
        try:
            if live:
                # Mechanical geometry and loading selection are explicit preprocessing,
                # not credited to the Agent. The Agent receives the prepared measurement table.
                spec, (table, _, _, _) = prepared_input(item["id"], source)
                path = runroot / "prepared_measurement.csv"
                table.to_csv(path, index=False)
                spec = {k: v for k, v in spec.items() if k not in {"import_options", "file_format"}}
                spec["path"] = str(path)
                agent = StudyUIAgent(runroot / "state.db", langflow=client, model=ChatModel())
                project = agent.store.create_project("Real instrument benchmark")
                agent.store.add_project_directory(project, str(runroot))
                agent.permissions.set_preset(project, "project_collaboration")
                session = agent.new_session(project_id=project)
                response = agent.run_turn(
                    session,
                    "请按以下已确认的测量参数创建并保存可编辑材料分析工作流，"
                    "含曲线和 HTML 报告；先保存，不运行。" + json.dumps(spec, ensure_ascii=False),
                )
                row["agent_status"] = response["task_status"]
                row["tool_steps"] = [
                    {k: s[k] for k in ("name", "ok", "duration_ms") if k in s}
                    for s in response.get("tool_steps", [])
                ]
                row["token_usage"] = response.get("token_usage")
                flows = client.list_flows()
                if response["task_status"] != "completed" or len(flows) != 1:
                    raise ValueError("Agent did not complete exactly one workflow")
                flow = client.get_flow(flows[0]["id"])
            else:
                created = client.create_flow(item["title"])
                created = client.get_flow(created["id"])
                compiled = compile_example(item["id"], source)
                flow, _ = apply_actions(created, compiled["actions"], installed)
                flow["studyui_protocol"] = compiled["protocol"]
                client.update_flow(flow["id"], flow)
            row["workflow_built"] = True
            row["method_contract"] = method_contract(flow, item)
            frozen = runroot / "frozen_workflow.json"
            frozen.write_text(json.dumps(flow, ensure_ascii=False, indent=2), encoding="utf-8")
            manifest.append(
                {
                    "id": item["id"],
                    "task": item["protocol"]["task"],
                    "flow_file": str(frozen),
                    "flow_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
                }
            )
        except Exception as exc:
            row.update(error_type=type(exc).__name__, error=str(exc)[:500])
        row["build_seconds"] = round(time.monotonic() - started, 3)
        rows.append(row)
        (output / "build.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = output / "frozen.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Independent cold processes receive no credentials and cannot rebuild the graph.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("STUDYUI_MODEL")}
    environment.update(
        PYTHONFAULTHANDLER="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1"
    )
    replays = []
    for trial in range(repeats):
        target = output / f"replay-{trial}.json"
        with (output / f"replay-{trial}.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [sys.executable, __file__, "--replay", str(manifest_path), "--output", str(target)],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=300,
            )
        replays.append(json.loads(target.read_text(encoding="utf-8")))
    items = {i["id"]: i for i in examples()}
    for row in rows:
        attempts = [r for trial in replays for r in trial if r["id"] == row["id"]]
        row["execution"] = len(attempts) == repeats and all(r["execution"] for r in attempts)
        row["repeatable"] = row["execution"] and len({r.get("result_table_sha256") for r in attempts}) == 1
        row["numerical_reference"] = (
            numeric_reference(items[row["id"]], attempts[0]["observed"])
            if row["execution"]
            else {"passed": False}
        )
    report = {
        "mode": "live_agent_prepared_real_measurements" if live else "reference_original_instruments",
        "model": os.environ.get("STUDYUI_MODEL") if live else None,
        "cases": len(rows),
        "cold_replays": repeats,
        "expert_method_review": (
            "not_collected; method_contract checks declared units, settings and method prerequisites"
        ),
        "runs": rows,
        "counts": {
            key: sum(bool(r[key]) for r in rows)
            for key in ["workflow_built", "method_contract", "execution", "repeatable"]
        },
        "numeric_reference_passed": sum(r["numerical_reference"]["passed"] for r in rows),
    }
    (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/material-instruments")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(2, 6), default=3)
    parser.add_argument("--replay")
    args = parser.parse_args()
    if args.replay:
        replay(args.replay, args.output)
    else:
        result = evaluate(args.output, args.live, args.repeats)
        print(
            json.dumps(
                {"counts": result["counts"], "numeric_reference_passed": result["numeric_reference_passed"]}
            )
        )
        raise SystemExit(
            0
            if all(v == result["cases"] for v in result["counts"].values())
            and result["numeric_reference_passed"] == result["cases"]
            else 1
        )

"""Build material flows through the Agent and execute them against analytic data.

Default mode uses scripted tool responses to test orchestration reproducibly.
--live uses the configured external model and reports those results separately.
Synthetic cases test engineering and numerical behavior, not real instrument validity.
"""

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from materials_quality.agent.file_workflow_client import FileWorkflowClient
from materials_quality.agent.harness import StudyUIAgent
from materials_quality.agent.model import ChatModel
from materials_quality.science.catalog import component_class


def cases(root):
    root.mkdir(parents=True, exist_ok=True)
    for task in ["mechanics", "spectra", "xrd"]:
        x = np.linspace(0, 0.02, 401) if task == "mechanics" else np.linspace(10, 80, 701)
        y = (
            np.where(x <= 0.001, 200000 * x, 200 + 1000 * (x - 0.001))
            if task == "mechanics"
            else (100 * np.exp(-(((x - 40) / 2) ** 2)))
        )
        path = root / (task + ".csv")
        pd.DataFrame({"x": x, "y": y}).to_csv(path, index=False)
        spec = {
            "task": task,
            "path": str(path.resolve()),
            "x": "x",
            "y": "y",
            "x_unit": "fraction" if task == "mechanics" else "deg" if task == "xrd" else "nm",
            "y_unit": "MPa" if task == "mechanics" else "counts",
        }
        spec.update(
            {"fit_range": [0, 0.0008], "yield_offset": 0.002}
            if task == "mechanics"
            else {"baseline": "none", "prominence": 1}
        )
        yield spec


class ProtocolModel:
    model = "scripted-protocol-contract"

    def __init__(self, spec):
        self.spec = spec
        self.calls = 0

    def complete(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "tool_calls": [
                    {
                        "id": "build",
                        "function": {
                            "name": "build_workflow",
                            "arguments": json.dumps(
                                {
                                    "name": self.spec["task"],
                                    "rationale": "显式确认参数",
                                    "protocol": self.spec,
                                }
                            ),
                        },
                    }
                ]
            }
        return {"content": "流程已生成，尚未执行。"}


def evaluate(output, repeats=3, live=False):
    from lfx.graph import Graph

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if live and not all(os.environ.get(k) for k in ["STUDYUI_MODEL_BASE_URL", "STUDYUI_MODEL"]):
        raise ValueError(
            "--live requires STUDYUI_MODEL_BASE_URL and STUDYUI_MODEL; configure the key securely."
        )
    keys = [
        "io.table_import",
        "materials.mechanics",
        "materials.spectra",
        "materials.xrd",
        "viz.spectra",
        "export.report",
        "export.table",
    ]
    catalog = {
        "materials_analysis": {
            component_class(k)().name: component_class(k)().to_frontend_node()["data"]["node"] for k in keys
        }
    }
    record = {
        "mode": "live_model" if live else "scripted_tool_contract",
        "model": os.environ.get("STUDYUI_MODEL") if live else "scripted-protocol-contract",
        "data": "analytic_synthetic",
        "repeats_per_task": repeats,
        "runs": [],
        "passed": False,
    }
    for spec in cases(output / "inputs"):
        for index in range(repeats):
            run_root = output / f"{spec['task']}-{index}"
            run_root.mkdir(parents=True, exist_ok=True)
            local_input = run_root / "input.csv"
            local_input.write_bytes(Path(spec["path"]).read_bytes())
            spec = dict(spec, path=str(local_input))
            client = FileWorkflowClient(
                run_root / "workflows", run_root / "components", catalog_loader=lambda: catalog
            )
            model = ChatModel() if live else ProtocolModel(spec)
            agent = StudyUIAgent(run_root / "state.db", langflow=client, model=model)
            project = agent.store.create_project("Stability evaluation")
            agent.store.add_project_directory(project, str(run_root))
            agent.permissions.set_preset(project, "project_collaboration")
            session = agent.new_session(project_id=project)
            started = time.monotonic()
            result = {
                "task": spec["task"],
                "trial": index,
                "workflow_built": False,
                "method_contract": False,
                "execution": False,
                "numeric_reference": False,
            }
            try:
                prompt = (
                    f"请创建 {spec['task']} 单曲线分析工作流，使用文件 {spec['path']} 。"
                    f"横坐标列 x，单位 {spec['x_unit']}；纵坐标列 y，单位 {spec['y_unit']}。"
                    + (
                        "弹性拟合区间 0 到 0.0008，偏移应变 0.002。"
                        if spec["task"] == "mechanics"
                        else "不扣基线，寻峰突出度为 1。"
                    )
                    + "生成可编辑表单、曲线和 HTML 报告节点，先保存流程。"
                )
                turn = agent.run_turn(session, prompt)
                result["agent_status"] = turn["task_status"]
                result["tool_steps"] = [
                    {k: step[k] for k in ("name", "ok", "duration_ms") if k in step}
                    for step in turn.get("tool_steps", [])
                ]
                result["token_usage"] = turn.get("token_usage")
                flows = client.list_flows()
                if turn["task_status"] != "completed" or len(flows) != 1:
                    raise ValueError("Agent did not produce exactly one completed workflow")
                flow = client.get_flow(flows[0]["id"])
                result["workflow_built"] = True
                # A declaration alone is not execution proof. Check the compiled native controls too.
                protocol = flow.get("studyui_protocol", {})
                params = protocol.get("parameters", {})
                expected = {k: v for k, v in spec.items() if k != "path"}
                result["method_contract"] = all(params.get(k) == v for k, v in expected.items())
                node = next(n for n in flow["data"]["nodes"] if n["id"] == "analysis")
                fields = node["data"]["node"]["template"]
                expected_fields = {"cfg_x": "x", "cfg_y": "y"}
                if spec["task"] == "mechanics":
                    expected_fields.update(
                        cfg_strain_unit="fraction",
                        cfg_stress_unit="MPa",
                        cfg_fit_range_min=0,
                        cfg_fit_range_max=0.0008,
                        cfg_yield_offset=0.002,
                    )
                else:
                    expected_fields.update(
                        cfg_baseline_method="none", cfg_prominence=1, cfg_x_unit=spec["x_unit"]
                    )
                result["method_contract"] = result["method_contract"] and all(
                    fields.get(k, {}).get("value") == v for k, v in expected_fields.items()
                )
                graph = Graph.from_payload(flow)
                for step in graph.start():
                    if hasattr(step, "valid") and not step.valid:
                        raise ValueError("Graph step failed")
                analysis = graph.get_vertex("analysis").results
                if spec["task"] == "mechanics":
                    observed = analysis["report"].data["data"]["elastic_modulus_MPa"]
                    result["numeric_reference"] = bool(np.isclose(observed, 200000, rtol=1e-8))
                else:
                    observed = analysis["features"]["peak_position"].tolist()
                    result["numeric_reference"] = len(observed) == 1 and abs(observed[0] - 40) < 0.11
                artifacts = graph.get_vertex("report").results["report"].data["artifacts"]
                result["execution"] = bool(artifacts) and all(Path(p).is_file() for p in artifacts)
                result["observed"] = observed
                result["flow_file"] = str(client.store.root / (flow["id"] + ".json"))
            except Exception as exc:
                result["error_type"] = type(exc).__name__
                result["error"] = str(exc)[:500]
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            record["runs"].append(result)
            (output / "result.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    record["repeatable"] = (
        None
        if repeats < 2
        else all(
            len(rows := [r for r in record["runs"] if r["task"] == task and "observed" in r]) == repeats
            and all(np.allclose(r["observed"], rows[0]["observed"], rtol=1e-8, atol=1e-8) for r in rows)
            for task in ["mechanics", "spectra", "xrd"]
        )
    )
    record["passed"] = record["repeatable"] is not False and all(
        all(r[k] for k in ["workflow_built", "method_contract", "execution", "numeric_reference"])
        for r in record["runs"]
    )
    (output / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/agent-stability")
    parser.add_argument("--repeats", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    record = evaluate(args.output, args.repeats, args.live)
    print(json.dumps({"mode": record["mode"], "passed": record["passed"], "runs": len(record["runs"])}))
    raise SystemExit(0 if record["passed"] else 1)

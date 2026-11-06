"""User-initiated execution of packaged reference graphs, without a model call."""

import json
import time

from .tasks import TaskCancelled, checkpoint
from .workflow import flow_digest


def _reference_info(dataset_id):
    from materials_quality.demos.catalog import get_dataset
    from materials_quality.demos.reference import load_reference_flow

    return get_dataset(dataset_id), load_reference_flow(dataset_id)


def _pin_reference_source(flow, template):
    """Keep source identity fixed while leaving analysis/plot settings editable."""
    kinds = {"ScienceFixtureBundle", "ScienceIoTableImport"}

    def protected(payload):
        return {
            node["id"]: node for node in payload["data"]["nodes"] if node.get("data", {}).get("type") in kinds
        }

    expected, actual = protected(template), protected(flow)
    if actual.keys() != expected.keys():
        raise ValueError("参考流程的数据来源节点已变化；自有数据请使用 Agent 载入入口。")
    for node_id, original in expected.items():
        left = original["data"]["node"]["template"]
        right = actual[node_id]["data"]["node"]["template"]
        keys = {key for key in left if key.startswith("cfg_")} | {
            "bundle_base64",
            "source_file",
            "ui_mode",
            "config_json",
        }
        for key in keys:
            if left.get(key, {}).get("value") != right.get(key, {}).get("value"):
                raise ValueError("参考流程的原始数据或导入设置已变化；请重新打开参考案例。")

    def incoming(payload):
        result = []
        for edge in payload["data"].get("edges", []):
            if edge.get("target") not in expected:
                continue
            signature = {key: edge.get(key) for key in ("source", "target", "sourceHandle", "targetHandle")}
            for key in ("sourceHandle", "targetHandle"):
                signature[key] = edge.get("data", {}).get(key, signature[key])
                try:
                    signature[key] = json.loads(signature[key])
                except (TypeError, ValueError):
                    pass
            result.append(json.dumps(signature, sort_keys=True))
        return sorted(result)

    if incoming(flow) != incoming(template):
        raise ValueError("参考流程的数据导入连接已变化；请恢复原始来源连接。")


def run_reference_canvas(harness, flow, session_id, *, on_progress=None):
    metadata = flow.get("studyui_demo")
    if not isinstance(metadata, dict):
        raise ValueError("参考流程标识无效；请重新打开演示案例。")
    item, template = _reference_info(metadata.get("dataset_id"))
    if metadata.get("source_sha256") != item["sha256"]:
        raise ValueError("参考流程来源与安装的数据不一致；请重新打开演示案例。")
    _pin_reference_source(flow, template)
    allowed = {node["data"]["type"] for node in template["data"]["nodes"]}
    nodes = flow.get("data", {}).get("nodes", [])
    if not nodes or any(
        node.get("data", {}).get("type") not in allowed
        or node.get("data", {}).get("type") == "StudyUIAIAnalysis"
        for node in nodes
    ):
        raise ValueError("流程包含参考范围以外的节点；请使用普通研究流程或重新打开参考案例。")
    project = flow.get("folder_id")
    decision = harness.permissions.authorize(project_id=project, action="workflow.run", task_authorized=True)
    if not decision.get("allowed"):
        raise PermissionError("当前项目权限不允许运行参考流程；请在项目设置中核对权限。")
    digest = flow_digest(flow)
    event = {"flow_id": flow["id"], "flow_digest": digest, "dataset_id": item["id"]}
    harness.store.append_message(session_id, {"role": "user", "content": "运行当前参考工作流。"})
    harness.store.append_event(session_id, "reference_workflow_started", event)
    tick = time.perf_counter()
    try:
        checkpoint()
        if on_progress:
            on_progress(
                {
                    "type": "tool_start",
                    "model": "本地参考工作流",
                    "step": {"name": "run_workflow", "title": "运行参考工作流"},
                }
            )
        result = harness.langflow.run_flow(
            flow["id"],
            external_data_approved=False,
            expected_digest=digest,
            expected_project_id=project,
        )
        checkpoint()
        artifacts = harness._store_generated_artifacts(result, session_id, flow=flow)
    except TaskCancelled:
        harness.store.append_event(session_id, "reference_workflow_cancelled", event)
        raise
    except Exception as exc:
        harness.store.append_event(
            session_id, "reference_workflow_failed", {**event, "error_type": type(exc).__name__}
        )
        raise
    elapsed = time.perf_counter() - tick
    message = (
        "参考工作流已按画布中保存的参数完成本地计算。\n\n"
        "请查看各节点的结果表、图表与报告；修改参数后的结果以本次输出为准。"
        "该操作没有调用语言模型，演示结果不代表真实材料的实验验证。"
    )
    harness.store.append_message(session_id, {"role": "assistant", "content": message})
    harness.store.append_event(
        session_id, "reference_workflow_completed", {**event, "elapsed_seconds": elapsed}
    )
    return {
        "session_id": session_id,
        "message": message,
        "artifacts": artifacts,
        "model": "本地参考工作流",
        "task_status": "completed",
        "pending_proposals": harness.store.pending_proposals(session_id),
        "pending_approvals": harness.store.pending_approvals(session_id),
        "task_pending_approvals": [],
        "reasoning_content": "",
        "skill_selection": None,
        "tool_steps": [
            {
                "name": "run_workflow",
                "title": "运行参考工作流",
                "ok": True,
                "summary": "确定性节点执行完成",
                "duration_ms": round(elapsed * 1000),
            }
        ],
        "workflow_result": result,
        "canvas_run": {
            "session_id": session_id,
            "flow_id": flow["id"],
            "contains_ai_subagent": False,
            "reference": True,
        },
    }

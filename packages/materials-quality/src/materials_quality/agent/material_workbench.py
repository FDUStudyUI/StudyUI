"""Materials task forms share the Agent's protocol compiler and project permissions."""

import hashlib
from urllib.parse import urlencode

import pandas as pd
from jsonschema import validate

from materials_quality.science.material_tasks import assess_protocol, task_catalog

from .material_protocols import PROTOCOL_SCHEMA, load_protocol_input


def _input(harness, session, spec):
    if not harness.store.has_session(session):
        raise ValueError("请先打开研究会话。")
    harness._authorized_research_file(session, spec["path"], "检查材料数据 " + spec["path"])
    return load_protocol_input(spec)


def preview(harness, session, spec):
    table, raw, _, _ = _input(harness, session, spec)
    sheets = []
    if str(spec["path"]).lower().endswith((".xlsx", ".xlsm")):
        with pd.ExcelFile(spec["path"]) as book:
            sheets = book.sheet_names
    return {
        "row_count": len(table),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "sheets": sheets,
        "columns": [
            {
                "name": str(c),
                "dtype": str(table[c].dtype),
                "missing_rate": float(table[c].isna().mean()) if len(table) else 0,
            }
            for c in table
        ],
        "preview": table.head(20).astype(object).where(pd.notna(table.head(20)), None).to_dict("records"),
    }


def check(harness, session, spec):
    validate(spec, PROTOCOL_SCHEMA)
    table, raw, _, _ = _input(harness, session, spec)
    return {**assess_protocol(table, spec), "source_sha256": hashlib.sha256(raw).hexdigest()}


def build(harness, session, spec):
    task = next((t for t in task_catalog() if t["id"] == spec.get("task")), None)
    if task is None:
        raise ValueError("请选择材料任务。")
    context = harness.store.session_context(session)
    if not context.get("project_id"):
        raise ValueError("请在研究项目中创建工作流。")
    decision = harness.permissions.authorize(
        project_id=context["project_id"], action="workflow.create", task_authorized=True
    )
    if not decision["allowed"]:
        raise PermissionError("当前项目权限不允许直接建流；可在聊天中发起审批，或选择项目协作权限。")
    result = harness._dispatch(
        session,
        "build_workflow",
        {
            "name": task["title"] + " · 分析协议",
            "rationale": "用户在材料任务表单确认数据与方法参数",
            "protocol": spec,
        },
        "请创建材料分析工作流",
    )
    return {
        **result,
        "url": "/canvas/flow/" + result["flow_id"] + "?" + urlencode({"studyui_session_id": session}),
    }


def example(harness, session, spec):
    from materials_quality.material_examples import compile_example, get_example, read_source

    from .uploads import save_upload

    item = get_example(spec["id"])
    context = harness.store.session_context(session)
    project = context.get("project_id")
    if (
        not project
        or not harness.permissions.authorize(
            project_id=project, action="workflow.create", task_authorized=True
        )["allowed"]
    ):
        raise PermissionError("请在允许创建工作流的项目会话中打开案例。")
    uploaded = save_upload(harness, session, item["filename"], read_source(item["id"]))
    compiled = compile_example(item["id"], uploaded["path"])
    result = harness._dispatch(
        session,
        "build_workflow",
        {
            "name": item["title"] + " · 真实仪器案例",
            "description": item["scope"],
            "rationale": "用户打开固定来源的真实仪器案例",
            "actions": compiled["actions"],
        },
        "请创建材料分析工作流",
    )
    flow = harness.langflow.get_flow(result["flow_id"])
    flow["studyui_protocol"] = compiled["protocol"]
    harness.langflow.update_flow(result["flow_id"], flow)
    return {
        **result,
        "url": "/canvas/flow/" + result["flow_id"] + "?" + urlencode({"studyui_session_id": session}),
    }


def run_canvas(harness, flow, session, on_progress=None):
    import time

    from .harness import _compact_run_result
    from .tasks import checkpoint
    from .workflow import flow_digest

    project = flow.get("folder_id")
    if not harness.permissions.authorize(project_id=project, action="workflow.run", task_authorized=True)[
        "allowed"
    ]:
        raise PermissionError("当前项目权限不允许运行工作流。")
    if any(n.get("data", {}).get("type") == "StudyUIAIAnalysis" for n in flow["data"]["nodes"]):
        raise PermissionError("包含云端 AI 分析的流程请通过聊天完成数据传输确认。")
    for node in flow["data"]["nodes"]:
        if "import" in node["data"]["type"].lower():
            path = node["data"]["node"]["template"].get("cfg_path", {}).get("value")
            if path:
                harness._authorized_research_file(session, path, "运行材料分析工作流")
    checkpoint()
    started = time.monotonic()
    if on_progress:
        on_progress({"type": "tool_start", "step": {"name": "run_workflow", "title": "运行材料分析"}})
    result = harness.langflow.run_flow(
        flow["id"], include_all_nodes=True, expected_digest=flow_digest(flow), expected_project_id=project
    )
    artifacts = harness._store_generated_artifacts(result, session, flow=flow)
    summary = _compact_run_result(result, flow=flow)
    completed = summary["execution_status"] == "completed"
    message = (
        "材料分析已完成。请查看结果表、图表、报告和复现包。"
        if completed
        else "部分节点未完成，请查看节点诊断；已有结果已保留。"
    )
    if completed:
        analysis = next((r for r in summary.get("outputs", []) if r.get("node_id") == "analysis"), {})
        metrics = analysis.get("outputs", {}).get("report", {}).get("data", {})
        values = []
        for key, label, unit in (
            ("elastic_modulus_MPa", "弹性模量", "MPa"),
            ("yield_stress_MPa", "偏移屈服强度", "MPa"),
            ("fit_r_squared", "弹性段拟合 R²", ""),
        ):
            value = metrics.get(key)
            if isinstance(value, (int, float)):
                values.append(f"{label}：{value:.6g} {unit}".rstrip())
        if values:
            message += "\n\n" + "；".join(values) + "。"
    harness.store.append_message(session, {"role": "assistant", "content": message, "model": "本地材料分析"})
    harness.store.append_event(session, "material_workflow_run", {"flow_id": flow["id"], "summary": summary})
    return {
        "session_id": session,
        "message": message,
        "model": "本地材料分析",
        "task_status": "completed" if completed else "failed",
        "artifacts": artifacts,
        "workflow_result": result,
        "pending_proposals": harness.store.pending_proposals(session),
        "pending_approvals": harness.store.pending_approvals(session),
        "tool_steps": [
            {
                "name": "run_workflow",
                "title": "运行材料分析",
                "ok": completed,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        ],
        "canvas_run": {"session_id": session, "flow_id": flow["id"], "contains_ai_subagent": False},
    }

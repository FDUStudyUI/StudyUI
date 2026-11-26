"""Materials task forms share the Agent's protocol compiler and project permissions."""

from __future__ import annotations

import hashlib
from urllib.parse import urlencode

import pandas as pd
from jsonschema import validate

from materials_quality.science.material_tasks import assess_protocol, task_catalog
from materials_quality.science.runtime_guards import evaluate_runtime_guards

from .material_protocols import PROTOCOL_SCHEMA, load_protocol_input


def evaluate_spec_guards(table, spec):
    """Evaluate runtime GUARD checks for a protocol spec, matching material_protocols.py."""
    task = spec["task"]
    x, y = spec.get("x"), spec.get("y")
    if not x or not y or x not in table.columns or y not in table.columns:
        return None
    guard_table = table.sort_values(x, kind="stable") if spec.get("sort", False) else table
    guard_cfg = {
        "strain_col": x,
        "stress_col": y,
        "x_col": x,
        "y_col": y,
        "sort": bool(spec.get("sort", False)),
    }
    if task == "mechanics":
        if "fit_range" in spec:
            guard_cfg["fit_range"] = spec["fit_range"]
    elif task == "spectra":
        guard_cfg["mode"] = spec.get("signal_kind", "absorbance")
    elif task == "xrd":
        guard_cfg.update(has_reference_pattern=False, claims_phase_id=False)
    elif task == "battery":
        guard_cfg.update(
            cycle_col=x,
            c_rate_col=spec.get("c_rate_col"),
            requested_metric=spec.get("requested_metric", "retention"),
        )
    elif task == "thermal":
        guard_cfg.update(
            temp_col=x,
            signal_col=y,
            heating_rate=spec.get("heating_rate"),
            atmosphere=spec.get("atmosphere"),
        )
    return evaluate_runtime_guards(task, guard_table, config=guard_cfg).to_dict()


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
    assessment = (
        {"task": spec["task"], "status": "ready", "checks": [], "next_actions": []}
        if spec["task"] in {"battery", "thermal"}
        else assess_protocol(table, spec)
    )
    result = {**assessment, "source_sha256": hashlib.sha256(raw).hexdigest()}
    if assessment.get("status") == "need_info":
        return {**result, "guard_report": None}
    guard_report = evaluate_spec_guards(table, spec)
    result["guard_report"] = guard_report
    if guard_report and guard_report.get("status") == "block":
        result["status"] = "block"
        next_actions = list(result.get("next_actions") or [])
        for finding in guard_report.get("findings") or []:
            if finding.get("severity") == "block":
                msg = str(finding.get("recommendation") or finding.get("message") or "").strip()
                if msg and msg not in next_actions:
                    next_actions.append(msg)
        result["next_actions"] = next_actions
    return result


def build(harness, session, spec):
    task = next((t for t in task_catalog() if t["id"] == spec.get("task")), None)
    if task is None:
        raise ValueError("请选择材料任务。")
    context = harness.store.session_context(session)
    if not context.get("project_id"):
        raise ValueError("请在研究项目中创建工作流。")
    # The material form is a human surface: the explicit form submission is the
    # approval. Only read_only projects are blocked from building a flow here.
    if harness.permissions.get_preset(context["project_id"]) == "read_only":
        raise PermissionError("当前项目为只读，无法直接建流；请选择项目协作权限。")
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
    flow = harness.canvas.get_flow(result["flow_id"])
    flow["studyui_protocol"] = compiled["protocol"]
    harness.canvas.update_flow(result["flow_id"], flow)
    return {
        **result,
        "url": "/canvas/flow/" + result["flow_id"] + "?" + urlencode({"studyui_session_id": session}),
    }


def run_canvas(harness, flow, session, on_progress=None, *, ledger_run_id=None):
    import time
    import uuid

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
    effective_run_id = ledger_run_id or f"run_{uuid.uuid4().hex[:16]}"
    try:
        result = harness.canvas.run_flow(
            flow["id"],
            include_all_nodes=True,
            expected_digest=flow_digest(flow),
            expected_project_id=project,
            ledger=getattr(harness, "ledger", None),
            run_id=effective_run_id,
            session_id=session,
        )
    except TypeError as exc:
        if not any(flag in str(exc) for flag in ("ledger", "run_id", "session_id")):
            raise
        result = harness.canvas.run_flow(
            flow["id"],
            include_all_nodes=True,
            expected_digest=flow_digest(flow),
            expected_project_id=project,
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

"""Unit and integration tests for Sprint 2 runtime governance modules:

- Append-only WorkflowLedger + cross-restart TaskManager resume
- Runtime GUARD checks across all 5 typical material tasks
- Runtime HUMAN approval gates (suspend & resume)
- Checked Graph Updates (structural DAG cycle, policy, compile triple gate)
- Automatic Scope & Limitations disclosure in reports and replay bundles
"""

from __future__ import annotations

import json
import sqlite3
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from materials_quality.agent.graph_gate import apply_checked_graph_update, check_dag_acyclic
from materials_quality.agent.human_gates import HumanGateController
from materials_quality.agent.permissions import PermissionStore
from materials_quality.agent.run_bundle import create_bundle
from materials_quality.agent.store import SessionStore
from materials_quality.agent.tasks import TaskManager
from materials_quality.agent.workflow_ledger import WorkflowLedger
from materials_quality.science import checkpoints, viz_report
from materials_quality.science.contracts import NodeResult
from materials_quality.science.runtime_guards import (
    build_boundary_disclosure,
    evaluate_runtime_guards,
)


def _sample_flow(flow_id: str = "flow-s2") -> dict:
    return {
        "id": flow_id,
        "name": "Sprint2 Test Flow",
        "description": "Two-node flow for ledger and gate tests",
        "folder_id": "proj-1",
        "is_component": False,
        "data": {
            "nodes": [
                {"id": "node_a", "data": {"id": "node_a", "type": "ScienceIoTableImport", "node": {"template": {}}}},
                {"id": "node_b", "data": {"id": "node_b", "type": "ScienceMaterialsMechanics", "node": {"template": {}}}},
            ],
            "edges": [],
        },
    }


def test_workflow_ledger_and_cross_restart_task_resume(tmp_path):
    ledger_root = tmp_path / "workflow_runs"
    cp_root = tmp_path / "checkpoints"
    db_path = tmp_path / "tasks.sqlite3"

    ledger = WorkflowLedger(ledger_root)
    flow = _sample_flow()
    started = ledger.start_run("run-001", flow, session_id="sess-1")
    assert started["graph_version"] == 1

    # Write a verified disk checkpoint for a pure operation, simulating node_a completion.
    from materials_quality.science.analysis_plan import PURE_OPERATIONS

    pure_op = sorted(PURE_OPERATIONS)[0]
    table = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [2.0, 4.0, 6.0]})
    with checkpoints.checkpoint_scope(cp_root) as records:
        _, rec = checkpoints.invoke(
            pure_op,
            table,
            {"columns": ["x", "y"]},
            None,
            None,
            lambda: NodeResult(table=table, data={"execution_status": "completed", "mean_y": 4.0}),
        )
    assert rec is not None and rec["key"]
    ledger.append_event("run-001", "node_completed", {"node_id": "node_a", "checkpoint_key": rec["key"]})

    # Seed two running tasks before a simulated server crash/restart:
    # one with a valid ledger_run_id and one plain task without a ledger.
    tm1 = TaskManager(db_path, ledger_root=ledger_root)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO tasks(id,session_id,request_key,status,created_at,updated_at,fingerprint,ledger_run_id) "
            "VALUES('t-ledger','sess-1','req-1','running','2026-11-26T00:00:00Z','2026-11-26T00:00:00Z','fp1','run-001')"
        )
        db.execute(
            "INSERT INTO tasks(id,session_id,request_key,status,created_at,updated_at,fingerprint,ledger_run_id) "
            "VALUES('t-plain','sess-1','req-2','running','2026-11-26T00:00:00Z','2026-11-26T00:00:00Z','fp2','')"
        )
        db.commit()

    # Simulated restart: ledger-backed task becomes interrupted_resumable; plain task stays interrupted.
    tm2 = TaskManager(db_path, ledger_root=ledger_root)
    assert tm2.get("t-ledger")["status"] == "interrupted_resumable"
    assert tm2.get("t-plain")["status"] == "interrupted"

    plan = ledger.resume_plan("run-001", checkpoint_root=cp_root)
    assert plan["resumable"] is True
    assert plan["reusable_nodes"] == ["node_a"]
    assert plan["pending_nodes"] == ["node_b"]

    # Execute resume_task and wait for completion.
    resumed = tm2.resume_task("t-ledger", lambda _progress: {"resumed": True, "skipped": plan["reusable_nodes"]})
    deadline = time.monotonic() + 5.0
    while not resumed["terminal"] and time.monotonic() < deadline:
        time.sleep(0.02)
        resumed = tm2.get(resumed["id"])
    assert resumed["status"] == "completed"
    assert resumed["result"]["skipped"] == ["node_a"]


def test_runtime_guards_cover_five_material_tasks_and_block_out_of_scope():
    # 1. Mechanics: valid linear elastic vs. cyclic non-monotonic & negative slope.
    good_mech = pd.DataFrame({"strain": np.linspace(0.0, 0.01, 20), "stress": np.linspace(0.0, 2000.0, 20)})
    assert evaluate_runtime_guards("mechanics", good_mech, config={"fit_range": (0.001, 0.006)}).passed

    cyclic_mech = pd.DataFrame(
        {"strain": [0.0, 0.002, 0.004, 0.006, 0.003, 0.005, 0.008], "stress": [0, 400, 800, 1200, 600, 1000, 1500]}
    )
    rep_cyclic = evaluate_runtime_guards("mechanics", cyclic_mech, config={"fit_range": (0.0, 0.008)})
    assert not rep_cyclic.passed
    assert any(f.code == "MECHANICS_NON_MONOTONIC_ELASTIC_SEGMENT" for f in rep_cyclic.findings)

    neg_mech = pd.DataFrame({"strain": np.linspace(0.0, 0.01, 15), "stress": np.linspace(500.0, 100.0, 15)})
    rep_neg = evaluate_runtime_guards("mechanics", neg_mech, config={"fit_range": (0.001, 0.008)})
    assert not rep_neg.passed
    assert any(f.code == "MECHANICS_NON_POSITIVE_MODULUS" for f in rep_neg.findings)

    # 2. Spectra: valid absorbance peak vs. transmittance valley & non-monotonic axis.
    wn = np.linspace(400.0, 4000.0, 80)
    abs_y = 0.05 + 1.2 * np.exp(-0.5 * ((wn - 1600.0) / 40.0) ** 2)
    assert evaluate_runtime_guards("spectra", pd.DataFrame({"wavenumber": wn, "intensity": abs_y})).passed

    trans_y = 96.0 - 65.0 * np.exp(-0.5 * ((wn - 1600.0) / 40.0) ** 2)
    rep_trans = evaluate_runtime_guards("spectra", pd.DataFrame({"wavenumber": wn, "intensity": trans_y}))
    assert not rep_trans.passed
    assert any(f.code == "SPECTRA_LIKELY_TRANSMITTANCE_VALLEY" for f in rep_trans.findings)

    # 3. XRD: blocks phase ID without reference pattern; allows peak-only with not_verified note.
    rep_xrd_block = evaluate_runtime_guards(
        "xrd",
        pd.DataFrame({"two_theta": [20.0, 30.0, 40.0]}),
        config={"has_reference_pattern": False, "claims_phase_id": True},
    )
    assert not rep_xrd_block.passed
    assert any(f.code == "XRD_PHASE_ID_WITHOUT_REFERENCE" for f in rep_xrd_block.findings)

    rep_xrd_ok = evaluate_runtime_guards(
        "xrd",
        pd.DataFrame({"two_theta": [20.0, 30.0, 40.0]}),
        config={"has_reference_pattern": False, "claims_phase_id": False},
    )
    assert rep_xrd_ok.passed
    assert rep_xrd_ok.not_verified

    # 4. Battery: blocks single-cycle retention extrapolation; warns mixed C-rate.
    rep_bat_single = evaluate_runtime_guards(
        "battery", pd.DataFrame({"cycle": [1, 1, 1], "capacity_mAh": [150, 149, 148]})
    )
    assert not rep_bat_single.passed
    assert any(f.code == "BATTERY_SINGLE_CYCLE_RETENTION_BLOCKED" for f in rep_bat_single.findings)

    rep_bat_mixed = evaluate_runtime_guards(
        "battery",
        pd.DataFrame({"cycle": [1, 2, 3, 4], "c_rate": ["0.5C", "0.5C", "2C", "2C"]}),
        config={"c_rate_col": "c_rate"},
    )
    assert rep_bat_mixed.status == "warn"
    assert any(f.code == "BATTERY_MIXED_CRATE_UNGROUPED" for f in rep_bat_mixed.findings)

    # 5. Thermal: blocks heating+cooling ramp; passes clean ramp.
    rep_th_bad = evaluate_runtime_guards(
        "thermal",
        pd.DataFrame({"temperature_C": [30, 100, 200, 300, 250, 150], "mass_pct": [100, 99, 95, 80, 80, 80]}),
    )
    assert not rep_th_bad.passed
    assert any(f.code == "THERMAL_NON_MONOTONIC_TEMPERATURE" for f in rep_th_bad.findings)

    rep_th_ok = evaluate_runtime_guards(
        "thermal",
        pd.DataFrame({"temperature_C": [30, 100, 200, 300, 400], "mass_pct": [100, 99, 95, 80, 75]}),
        config={"heating_rate": 10.0, "atmosphere": "N2"},
    )
    assert rep_th_ok.passed
    assert not rep_th_ok.not_verified


def test_human_gate_suspends_and_resumes_with_ledger(tmp_path):
    store = SessionStore(tmp_path / "agent.sqlite3")
    session_id = store.create_session("HUMAN 门禁测试")
    ledger = WorkflowLedger(tmp_path / "workflow_runs")
    ledger.start_run("run-human", _sample_flow(), session_id=session_id)

    controller = HumanGateController(store, ledger)
    pending = controller.request_gate(
        session_id=session_id,
        run_id="run-human",
        node_id="node_b",
        gate_kind="select_fit_range",
        prompt="弹性段 R² 偏低，请确认是否将 fit_range 收窄至 [0.001, 0.004]。",
        proposed_parameters={"fit_range": [0.001, 0.004]},
    )
    assert pending["status"] == "waiting_human_gate"
    assert ledger.summarize_run("run-human")["status"] == "waiting_human_gate"
    assert ledger.resume_plan("run-human")["resumable"] is False

    resolved = controller.resolve_gate(
        pending["approval_id"],
        "approved",
        reviewer_note="已核对曲线，同意使用 [0.001, 0.0035]。",
        confirmed_parameters={"fit_range": [0.001, 0.0035]},
    )
    assert resolved["can_resume"] is True
    assert resolved["confirmed_parameters"] == {"fit_range": [0.001, 0.0035]}
    assert ledger.resume_plan("run-human")["resumable"] is True


def test_checked_graph_updates_triple_gate(tmp_path):
    from materials_quality.science.catalog import component_class, entries

    # Build a small real catalog with two compatible science components + AI node stub.
    by_name = {item["class_name"]: item["key"] for item in entries()}
    import_node = component_class(by_name["ScienceIoTableImport"])().to_frontend_node()["data"]["node"]
    filter_node = component_class(by_name["SciencePreprocessFilter"])().to_frontend_node()["data"]["node"]
    ai_node_stub = {
        "display_name": "StudyUIAIAnalysis",
        "template": {"input_table": {"type": "table", "input_types": ["DataFrame"], "value": None}},
        "outputs": [{"name": "report", "display_name": "Report", "types": ["Data"]}],
    }
    catalog = {
        "materials_sources": {"ScienceIoTableImport": import_node},
        "materials_preprocessing": {"SciencePreprocessFilter": filter_node},
        "materials_analysis": {"StudyUIAIAnalysis": ai_node_stub},
    }
    empty_flow = {
        "id": "flow-gate",
        "name": "Gate Test",
        "description": "",
        "folder_id": "proj-1",
        "is_component": False,
        "data": {"nodes": [], "edges": []},
    }
    ledger = WorkflowLedger(tmp_path / "workflow_runs")
    ledger.start_run("run-gate", empty_flow)
    perms = PermissionStore(tmp_path / "settings.json")

    # 1. Valid DAG passes structural, policy, and compile gates.
    ok_res = apply_checked_graph_update(
        empty_flow,
        [
            {"op": "add_node", "node_id": "raw", "component_type": "ScienceIoTableImport"},
            {"op": "add_node", "node_id": "filt", "component_type": "SciencePreprocessFilter"},
            {"op": "connect", "source": "raw", "output": "table", "target": "filt", "input": "input_table"},
        ],
        catalog,
        permissions=perms,
        project_id="proj-1",
        ledger=ledger,
        run_id="run-gate",
        rationale="Add import and filter nodes",
    )
    assert ok_res.accepted is True
    assert ok_res.graph_version == 2
    assert ok_res.gate_details == {"structural": "passed", "policy": "passed", "compile": "passed"}

    # 2. Cyclic edge is rejected by structural gate; original flow W^(k) stays intact.
    cyclic_res = apply_checked_graph_update(
        ok_res.flow,
        [
            {"op": "add_node", "node_id": "filt2", "component_type": "SciencePreprocessFilter"},
            {"op": "connect", "source": "filt", "output": "table", "target": "filt2", "input": "input_table"},
            {"op": "connect", "source": "filt2", "output": "table", "target": "filt", "input": "input_table"},
        ],
        catalog,
        permissions=perms,
        project_id="proj-1",
        ledger=ledger,
        run_id="run-gate",
    )
    assert cyclic_res.accepted is False
    assert cyclic_res.digest == ok_res.digest
    assert any(r["code"] == "DAG_CYCLE_DETECTED" for r in cyclic_res.rejections)
    assert len(ledger.summarize_run("run-gate")["rejected_updates"]) == 1

    # 3. Adding external-data StudyUIAIAnalysis node without approval is rejected by policy gate.
    ai_res = apply_checked_graph_update(
        ok_res.flow,
        [{"op": "add_node", "node_id": "ai", "component_type": "StudyUIAIAnalysis"}],
        catalog,
        permissions=perms,
        project_id="proj-1",
        ledger=ledger,
        run_id="run-gate",
    )
    assert ai_res.accepted is False
    assert any(r["code"] == "EXTERNAL_AI_APPROVAL_REQUIRED" for r in ai_res.rejections)

    # 4. Adding a SECOND StudyUIAIAnalysis node to a flow that already has one still requires approval.
    approved_ai = apply_checked_graph_update(
        ok_res.flow,
        [{"op": "add_node", "node_id": "ai1", "component_type": "StudyUIAIAnalysis"}],
        catalog,
        permissions=perms,
        project_id="proj-1",
        allow_external_ai_without_approval=True,
        ledger=ledger,
        run_id="run-gate",
    )
    assert approved_ai.accepted is True
    second_ai = apply_checked_graph_update(
        approved_ai.flow,
        [{"op": "add_node", "node_id": "ai2", "component_type": "StudyUIAIAnalysis"}],
        catalog,
        permissions=perms,
        project_id="proj-1",
        ledger=ledger,
        run_id="run-gate",
    )
    assert second_ai.accepted is False
    assert any(r["code"] == "EXTERNAL_AI_APPROVAL_REQUIRED" for r in second_ai.rejections)


def test_reports_and_run_bundles_include_scope_and_limitations(tmp_path):
    guard = evaluate_runtime_guards(
        "xrd",
        pd.DataFrame({"two_theta": [20.0, 30.0, 40.0]}),
        config={"has_reference_pattern": False, "claims_phase_id": False},
    )
    html_res = viz_report.build_report(
        pd.DataFrame({"peak_2theta": [26.6]}),
        {"output_dir": str(tmp_path), "format": "html", "filename": "xrd-report.html"},
        {
            "title": "XRD 测试报告",
            "task": "xrd",
            "guard_report": guard.to_dict(),
            "sources": ["sample.xy"],
            "parameters": {"prominence": 0.1},
            "results": {"peak_count": 1},
            "warnings": [],
            "figures": [],
        },
    )
    assert "Scope & Limitations" in html_res.data["sections"]
    html_text = Path(html_res.artifacts[0]).read_text(encoding="utf-8")
    assert "适用范围、未验证前提与技术限制" in html_text
    assert "未关联标准参考谱" in html_text

    md_res = viz_report.build_report(
        pd.DataFrame({"peak_2theta": [26.6]}),
        {"output_dir": str(tmp_path), "format": "markdown", "filename": "xrd-report.md"},
        {
            "title": "XRD 测试报告",
            "boundary_disclosure": build_boundary_disclosure("xrd", guard_report=guard),
            "sources": ["sample.xy"],
            "parameters": {},
            "results": {},
            "warnings": [],
            "figures": [],
        },
    )
    md_text = Path(md_res.artifacts[0]).read_text(encoding="utf-8")
    assert "## Scope & Limitations" in md_text
    assert "### 适用范围" in md_text
    assert "### 未验证前提" in md_text

    # Verify create_bundle writes scope_and_limitations.json for compile_material_protocol shape (no top-level 'task').
    flow = _sample_flow("flow-bundle")
    flow["studyui_protocol"] = {
        "id": "materials.xrd",
        "version": 1,
        "parameters": {"task": "xrd", "prominence": 0.1},
        "assessment": {"checks": []},
    }
    archive = create_bundle(flow, [], tmp_path / "bundles", checkpoints=[])
    with zipfile.ZipFile(archive, "r") as zf:
        names = set(zf.namelist())
        assert "scope_and_limitations.json" in names
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "scope_and_limitations.json" in manifest["files"]
        scope_doc = json.loads(zf.read("scope_and_limitations.json").decode("utf-8"))
        assert scope_doc["task"] == "xrd"
        assert scope_doc["applicability_scope"]
        assert scope_doc["known_limitations"]

    # Verify build_report infers material task from results[].operation (langflow_adapter export.report shape).
    inferred_res = viz_report.build_report(
        pd.DataFrame({"peak_2theta": [26.6]}),
        {"output_dir": str(tmp_path), "format": "html", "filename": "xrd-inferred.html"},
        {
            "title": "XRD 自动推断限制报告",
            "sources": ["sample.xy"],
            "parameters": {},
            "results": [{"operation": "materials.xrd", "data": {"peak_count": 1}}],
            "warnings": [],
            "figures": [],
        },
    )
    assert "Scope & Limitations" in inferred_res.data["sections"]
    assert "适用范围、未验证前提与技术限制" in Path(inferred_res.artifacts[0]).read_text(encoding="utf-8")


def test_harness_integrates_graph_gate_human_gate_protocol_guard_and_resume(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.harness import StudyUIAgent
    from materials_quality.agent.task_api import task_router
    from materials_quality.science.catalog import component_class, entries

    by_name = {item["class_name"]: item["key"] for item in entries()}
    catalog = {
        "materials_sources": {
            "ScienceIoTableImport": component_class(by_name["ScienceIoTableImport"])().to_frontend_node()["data"]["node"]
        },
        "materials_preprocessing": {
            "SciencePreprocessFilter": component_class(by_name["SciencePreprocessFilter"])().to_frontend_node()["data"]["node"]
        },
    }
    workflows_dir = tmp_path / "workflows"
    components_dir = tmp_path / "components"
    components_dir.mkdir()
    client = FileWorkflowClient(workflows_dir, components_dir, catalog_loader=lambda: catalog)
    agent = StudyUIAgent(tmp_path / "studyui.db", langflow=client)
    project_id = agent.store.create_project("集成测试项目", "Sprint 2 主链路")
    agent.permissions.set_preset(project_id, "project_collaboration")
    session_id = agent.new_session("主链路会话", project_id=project_id)

    # 1. Harness build_workflow rejects cyclic DAG via apply_checked_graph_update.
    try:
        agent._dispatch(
            session_id,
            "build_workflow",
            {
                "name": "Cyclic Test",
                "actions": [
                    {"op": "add_node", "node_id": "a", "component_type": "SciencePreprocessFilter"},
                    {"op": "add_node", "node_id": "b", "component_type": "SciencePreprocessFilter"},
                    {"op": "connect", "source": "a", "output": "table", "target": "b", "input": "input_table"},
                    {"op": "connect", "source": "b", "output": "table", "target": "a", "input": "input_table"},
                ],
            },
            "请搭建工作流",
        )
        raise AssertionError("Expected cyclic build_workflow to fail structural gate")
    except ValueError as exc:
        assert "环路" in str(exc)

    # 2. Harness decide_approval handles workflow.human_gate cleanly and updates WorkflowLedger.
    agent.ledger.start_run("run-hgate", _sample_flow(), session_id=session_id)
    pending = agent.human_gates.request_gate(
        session_id=session_id,
        run_id="run-hgate",
        node_id="node_b",
        gate_kind="select_fit_range",
        prompt="确认拟合区间",
        proposed_parameters={"fit_range": [0.0005, 0.001]},
    )
    decided = agent.decide_approval(pending["approval_id"], "approved")
    assert decided["status"] == "completed"
    assert decided["result"]["can_resume"] is True
    assert agent.ledger.resume_plan("run-hgate")["resumable"] is True

    # 3. compile_material_protocol executes runtime GUARD and attaches guard_report.
    good_csv = tmp_path / "good_spectra.csv"
    wn = np.linspace(400.0, 1800.0, 40)
    abs_y = 0.05 + 1.0 * np.exp(-0.5 * ((wn - 1000.0) / 30.0) ** 2)
    pd.DataFrame({"wavenumber": wn, "intensity": abs_y}).to_csv(good_csv, index=False)

    from materials_quality.agent.material_protocols import compile_material_protocol

    compiled = compile_material_protocol(
        {
            "task": "spectra",
            "path": str(good_csv),
            "x": "wavenumber",
            "y": "intensity",
            "x_unit": "cm^-1",
            "y_unit": "a.u.",
            "baseline": "none",
            "prominence": 0.2,
            "signal_kind": "absorbance",
        }
    )
    assert compiled["protocol"]["guard_report"]["status"] == "pass"

    bad_csv = tmp_path / "valley_spectra.csv"
    trans_y = 95.0 - 50.0 * np.exp(-0.5 * ((wn - 1000.0) / 30.0) ** 2)
    pd.DataFrame({"wavenumber": wn, "intensity": trans_y}).to_csv(bad_csv, index=False)
    try:
        compile_material_protocol(
            {
                "task": "spectra",
                "path": str(bad_csv),
                "x": "wavenumber",
                "y": "intensity",
                "x_unit": "cm^-1",
                "y_unit": "a.u.",
                "baseline": "none",
                "prominence": 5.0,
                "signal_kind": "absorbance",
            }
        )
        raise AssertionError("Expected transmittance valley to be blocked by protocol GUARD")
    except ValueError as exc:
        assert "透射率" in str(exc)

    # 5. compile_material_protocol supports thermal (TG/DSC) and battery cycling protocols.
    tg_csv = tmp_path / "tg_ramp.csv"
    pd.DataFrame(
        {"temp_C": [30.0, 100.0, 200.0, 300.0, 400.0], "mass_pct": [100.0, 99.5, 97.0, 82.0, 76.0]}
    ).to_csv(tg_csv, index=False)
    tg_compiled = compile_material_protocol(
        {
            "task": "thermal",
            "path": str(tg_csv),
            "x": "temp_C",
            "y": "mass_pct",
            "x_unit": "degC",
            "y_unit": "%",
            "baseline": "none",
            "prominence": 1.0,
            "thermal_kind": "tg",
            "heating_rate": 10.0,
            "atmosphere": "N2",
        }
    )
    assert tg_compiled["protocol"]["id"] == "materials.thermal"
    assert tg_compiled["protocol"]["guard_report"]["status"] == "pass"

    bat_csv = tmp_path / "battery_cycles.csv"
    pd.DataFrame(
        {
            "cell_id": ["cell_1", "cell_1", "cell_1", "cell_1"],
            "cycle": [1, 2, 3, 4],
            "discharge_mAh": [180.0, 178.5, 176.0, 174.2],
        }
    ).to_csv(bat_csv, index=False)
    bat_compiled = compile_material_protocol(
        {
            "task": "battery",
            "path": str(bat_csv),
            "x": "cycle",
            "y": "discharge_mAh",
            "x_unit": "cycle",
            "y_unit": "mAh",
            "cell_col": "cell_id",
            "requested_metric": "retention",
        }
    )
    assert bat_compiled["protocol"]["id"] == "materials.battery"
    assert bat_compiled["protocol"]["guard_report"]["status"] == "pass"
    assert any(a.get("component_type") == "BatteryCycles" for a in bat_compiled["actions"])

    # 6. recommend_analysis_methods & run_materials_solver expose all 5 domain cards and plugins.
    rec = agent._dispatch(
        session_id,
        "recommend_analysis_methods",
        {"query": "电池循环保持率与热分析TG", "task": "battery"},
        "推荐电池循环分析方法",
    )
    assert rec["domain_task_cards"]
    assert "battery" in rec["task_boundaries"]

    solver_res = agent._dispatch(
        session_id,
        "run_materials_solver",
        {"solver": "battery_single_cell", "model_name": "SPM", "c_rate": 3.0, "ambient_temp_C": 25.0},
        "运行单电芯仿真",
    )
    assert solver_res["plugin"] == "pybamm_battery"
    assert solver_res["status"] in {"ok", "unavailable"}
    assert solver_res["boundary_warnings"]

    # 4. task_router wires ledger_root into TaskManager and exposes /resume endpoint.
    flow = client.create_flow("Resumable Flow", project_id=project_id)
    agent.ledger.start_run("run-api-res", flow, session_id=session_id)
    router, manager = task_router(agent)
    assert manager.ledger_root == (tmp_path / "workflow_runs").resolve()
    with sqlite3.connect(manager.path) as db:
        db.execute(
            "INSERT INTO tasks(id,session_id,request_key,status,created_at,updated_at,fingerprint,ledger_run_id) "
            "VALUES('t-api-res',?, 'req-api','running','2026-11-26T00:00:00Z','2026-11-26T00:00:00Z','fp','run-api-res')",
            (session_id,),
        )
        db.commit()
    # Re-create router after simulated restart so TaskManager transitions task to interrupted_resumable.
    router2, manager2 = task_router(agent)
    assert manager2.get("t-api-res")["status"] == "interrupted_resumable"
    app = FastAPI()
    app.include_router(router2)
    agent.run_canvas_workflow = lambda fid, **kw: {"status": "resumed_ok", "flow_id": fid, "run_id": kw.get("ledger_run_id")}
    with TestClient(app, base_url="http://127.0.0.1:7880") as http:
        res = http.post(f"/api/sessions/{session_id}/tasks/t-api-res/resume")
        assert res.status_code == 202
        resumed_id = res.json()["id"]
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snap = http.get(f"/api/sessions/{session_id}/tasks/{resumed_id}").json()
            if snap["terminal"]:
                break
            time.sleep(0.02)
        assert snap["status"] == "completed"
        assert snap["result"]["status"] == "resumed_ok"


def test_material_workbench_check_returns_guard_report_and_reflects_block(tmp_path):
    from materials_quality.agent import material_workbench
    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.harness import StudyUIAgent
    from materials_quality.agent.uploads import save_upload

    workflows_dir = tmp_path / "workflows"
    components_dir = tmp_path / "components"
    components_dir.mkdir()
    client = FileWorkflowClient(workflows_dir, components_dir, catalog_loader=lambda: {})
    agent = StudyUIAgent(tmp_path / "studyui.db", langflow=client)
    project_id = agent.store.create_project("Workbench Guard 测试")
    session_id = agent.new_session("Workbench 会话", project_id=project_id)

    # 1. Valid absorbance spectrum passes runtime GUARD.
    wn = np.linspace(400.0, 1800.0, 40)
    abs_y = 0.05 + 1.0 * np.exp(-0.5 * ((wn - 1000.0) / 30.0) ** 2)
    good_bytes = pd.DataFrame({"wavenumber": wn, "intensity": abs_y}).to_csv(index=False).encode("utf-8")
    good_csv = save_upload(agent, session_id, "good_spectra.csv", good_bytes)["path"]
    ok_res = material_workbench.check(
        agent,
        session_id,
        {
            "task": "spectra",
            "path": str(good_csv),
            "x": "wavenumber",
            "y": "intensity",
            "x_unit": "cm^-1",
            "y_unit": "a.u.",
            "baseline": "none",
            "prominence": 0.2,
            "signal_kind": "absorbance",
        },
    )
    assert ok_res["status"] == "ready"
    assert ok_res["guard_report"]["status"] == "pass"

    # 2. Transmittance valley labeled as absorbance is reflected as status='block'.
    trans_y = 95.0 - 50.0 * np.exp(-0.5 * ((wn - 1000.0) / 30.0) ** 2)
    bad_bytes = pd.DataFrame({"wavenumber": wn, "intensity": trans_y}).to_csv(index=False).encode("utf-8")
    bad_csv = save_upload(agent, session_id, "valley_spectra.csv", bad_bytes)["path"]
    block_res = material_workbench.check(
        agent,
        session_id,
        {
            "task": "spectra",
            "path": str(bad_csv),
            "x": "wavenumber",
            "y": "intensity",
            "x_unit": "cm^-1",
            "y_unit": "a.u.",
            "baseline": "none",
            "prominence": 5.0,
            "signal_kind": "absorbance",
        },
    )
    assert block_res["status"] == "block"
    assert block_res["guard_report"]["status"] == "block"
    assert any(f["code"] == "SPECTRA_LIKELY_TRANSMITTANCE_VALLEY" for f in block_res["guard_report"]["findings"])
    assert block_res["next_actions"]

    # 3. Battery mixed C-rate surfaces BATTERY_MIXED_CRATE_UNGROUPED warning in guard_report.
    bat_bytes = (
        pd.DataFrame(
            {
                "cycle": [1, 2, 3, 4],
                "discharge_mAh": [160.0, 158.0, 130.0, 128.0],
                "c_rate": ["0.5C", "0.5C", "2C", "2C"],
            }
        )
        .to_csv(index=False)
        .encode("utf-8")
    )
    bat_csv = save_upload(agent, session_id, "mixed_crate_battery.csv", bat_bytes)["path"]
    warn_res = material_workbench.check(
        agent,
        session_id,
        {
            "task": "battery",
            "path": str(bat_csv),
            "x": "cycle",
            "y": "discharge_mAh",
            "x_unit": "cycle",
            "y_unit": "mAh",
            "c_rate_col": "c_rate",
            "requested_metric": "retention",
        },
    )
    assert warn_res["guard_report"]["status"] == "warn"
    assert any(f["code"] == "BATTERY_MIXED_CRATE_UNGROUPED" for f in warn_res["guard_report"]["findings"])


def test_run_workflow_auto_suspends_on_recoverable_guard_and_resumes_after_approval(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent
    from materials_quality.agent.file_workflow_client import FileWorkflowClient

    workflows_dir = tmp_path / "workflows"
    components_dir = tmp_path / "components"
    components_dir.mkdir()
    client = FileWorkflowClient(workflows_dir, components_dir, catalog_loader=lambda: {})

    run_calls = []

    def fake_run_flow(flow_id, **kwargs):
        run_calls.append((flow_id, kwargs))
        return {"outputs": [{"outputs": [{"results": {"report": {"data": {"ok": True}}}}]}]}

    client.run_flow = fake_run_flow

    agent = StudyUIAgent(tmp_path / "studyui.db", langflow=client)
    project_id = agent.store.create_project("GUARD->HUMAN 测试")
    agent.permissions.set_preset(project_id, "project_collaboration")
    session_id = agent.new_session("自动门禁会话", project_id=project_id)
    workdir = agent.working_directory(session_id)
    workdir.mkdir(parents=True, exist_ok=True)

    # Create a battery dataset with mixed C-rate (triggers recoverable BATTERY_MIXED_CRATE_UNGROUPED).
    bat_csv = workdir / "mixed_crate.csv"
    pd.DataFrame(
        {
            "cycle": [1, 2, 3, 4],
            "discharge_mAh": [160.0, 158.0, 130.0, 128.0],
            "c_rate": ["0.5C", "0.5C", "2C", "2C"],
        }
    ).to_csv(bat_csv, index=False)

    flow = client.create_flow("Battery Mixed C-Rate Flow", project_id=project_id)
    flow["studyui_protocol"] = {
        "id": "materials.battery",
        "version": 1,
        "parameters": {
            "task": "battery",
            "path": str(bat_csv),
            "x": "cycle",
            "y": "discharge_mAh",
            "x_unit": "cycle",
            "y_unit": "mAh",
            "c_rate_col": "c_rate",
            "requested_metric": "retention",
        },
    }
    client.store.save(flow)

    # 1. First run_workflow triggers HumanGateController.request_gate and suspends cleanly.
    suspended = agent._dispatch(session_id, "run_workflow", {"flow_id": flow["id"]}, "请运行电池分析工作流")
    assert suspended["status"] == "pending_approval"
    assert suspended["task_status"] == "interrupted_resumable"
    assert suspended["gate_kind"] == "confirm_guard_override"
    assert suspended["proposed_parameters"]["group_by_c_rate"] is True
    assert run_calls == []

    pending_list = agent.store.pending_approvals(session_id)
    assert len(pending_list) == 1
    assert pending_list[0]["id"] == suspended["approval_id"]
    assert pending_list[0]["action"] == "workflow.human_gate"

    ledger_summary = agent.ledger.summarize_run(suspended["run_id"])
    assert ledger_summary["status"] == "interrupted_resumable"
    assert len(ledger_summary["pending_human_gates"]) == 1
    assert agent.ledger.resume_plan(suspended["run_id"])["resumable"] is False

    # 2. Approving workflow.human_gate resolves the gate in both store and WorkflowLedger.
    decided = agent.decide_approval(suspended["approval_id"], "approved")
    assert decided["status"] == "completed"
    assert decided["result"]["can_resume"] is True
    assert agent.ledger.resume_plan(suspended["run_id"])["resumable"] is True
    assert agent.store.pending_approvals(session_id) == []

    # 3. Re-running run_workflow with the same session & flow_digest succeeds without looping.
    resumed = agent._dispatch(session_id, "run_workflow", {"flow_id": flow["id"]}, "请运行电池分析工作流")
    assert resumed["status"] == "completed"
    assert len(run_calls) == 1

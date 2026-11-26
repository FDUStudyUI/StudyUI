"""Sprint 3 tests: declarative knowledge evolution closed loops and solver plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

from materials_quality.agent.store import SessionStore
from materials_quality.agent.workflow_ledger import WorkflowLedger
from materials_quality.assets import build_default_asset_graph
from materials_quality.evolution import (
    EvolutionController,
    KnowledgePatch,
    collect_evidence,
    critique_evidence,
    evaluate_patch,
    propose_declarative_patches,
    validate_declarative_patch,
)
from materials_quality.science.plugins import (
    XRD_LIMITATION_NOTICE,
    compute_theoretical_xrd_from_cif,
    match_measured_xrd_peaks,
    pybamm_available,
    pymatgen_available,
    simulate_single_cell_discharge,
)


def _sample_flow() -> dict:
    return {
        "id": "flow_sprint3_demo",
        "name": "XRD Screening Flow",
        "data": {
            "nodes": [{"id": "n1", "type": "xrd_peak_finder"}],
            "edges": [],
        },
    }


def test_evolution_closed_loop_guard_to_approval_and_rollback(tmp_path: Path) -> None:
    """Closed Loop 1: GUARD block + noise -> filter -> patch -> gate -> manual approval -> rollback."""
    graph = build_default_asset_graph()
    store = SessionStore(tmp_path / "agent.sqlite3")
    ledger = WorkflowLedger(tmp_path / "ledger")

    session_id = store.create_session(title="XRD Evolution Test")

    ledger.start_run("run_xrd_01", _sample_flow(), session_id=session_id)
    # Non-transient domain GUARD block
    ledger.append_event(
        "run_xrd_01",
        "guard_blocked",
        {
            "domain": "xrd",
            "code": "XRD_WAVELENGTH_MISSING",
            "message": "XRD Scherrer calculation blocked: missing target wavelength metadata.",
            "recommended_action": "执行 Scherrer 晶粒尺寸估算前必须显式核验靶材波长（如 Cu K-alpha 1.5406 A）。",
        },
    )
    # Transient network noise that must be filtered out
    ledger.append_event(
        "run_xrd_01",
        "node_failed",
        {
            "node_id": "n1",
            "error": "ReadTimeout: 503 Service Temporarily Unavailable",
        },
    )

    bundle = collect_evidence(store=store, ledger=ledger, session_ids=[session_id], run_ids=["run_xrd_01"])
    assert len(bundle.items) == 2
    assert len(bundle.non_transient_items()) == 1

    findings = critique_evidence(bundle, graph, min_occurrences=1)
    assert len(findings) == 1
    assert findings[0].target_asset_type in {"K", "S"}
    assert findings[0].domain == "xrd"

    patches = propose_declarative_patches(findings, graph)
    assert len(patches) == 1
    patch = patches[0]
    assert patch.field == "known_limitations"

    target_before = graph.get(patch.target_asset_id)
    assert target_before is not None
    orig_version = target_before.version
    orig_limitations = target_before.known_limitations

    controller = EvolutionController(store=store, storage_dir=tmp_path / "evo", mode="manual")

    def benchmark(candidate_graph):
        return {
            "graph_valid": len(candidate_graph.errors()) == 0,
            "xrd_assets_present": len(candidate_graph.by_domain("xrd")) > 0,
        }

    submission = controller.submit_patch(
        patch,
        graph,
        session_id=session_id,
        benchmark_runner=benchmark,
    )
    assert submission["status"] == "pending_approval"
    assert submission["approval_id"] is not None

    # Cannot apply before manual approval
    with pytest.raises(PermissionError):
        controller.apply_approved_patch(patch.patch_id, graph)

    # Approve and apply
    store.decide_approval(submission["approval_id"], "approved")
    applied = controller.apply_approved_patch(patch.patch_id, graph)
    assert applied["status"] == "applied"
    assert applied["new_version"] != orig_version

    target_after = graph.get(patch.target_asset_id)
    assert target_after is not None
    assert patch.values[0] in target_after.known_limitations
    assert set(orig_limitations).issubset(set(target_after.known_limitations))

    # One-shot approval must be invalidated
    approval_after = store.get_approval(submission["approval_id"])
    assert approval_after is not None
    assert approval_after["status"] != "approved"

    # One-click rollback restores exact prior snapshot
    rolled = controller.rollback_patch(patch.patch_id, graph)
    assert rolled["status"] == "rolled_back"
    assert rolled["restored_version"] == orig_version
    target_restored = graph.get(patch.target_asset_id)
    assert target_restored is not None
    assert target_restored.known_limitations == orig_limitations
    assert target_restored.version == orig_version

    # Re-submitting the same patch after rollback must get a fresh approval_id without SQLite PK collision
    resubmitted = controller.submit_patch(
        patch,
        graph,
        session_id=session_id,
        benchmark_runner=benchmark,
    )
    assert resubmitted["status"] == "pending_approval"
    assert resubmitted["approval_id"] != submission["approval_id"]


def test_collector_aligns_with_sprint2_events_and_store_events(tmp_path: Path) -> None:
    """Verify collector reads recommendation, graph_gate rejections, human_gate reviewer_note, and distinct store events."""
    from materials_quality.agent.human_gates import HumanGateController

    store = SessionStore(tmp_path / "agent.sqlite3")
    ledger = WorkflowLedger(tmp_path / "ledger")
    session_id = store.create_session(title="Collector Alignment")
    ledger.start_run("run_align", _sample_flow(), session_id=session_id)

    ledger.append_event(
        "run_align",
        "guard_blocked",
        {
            "domain": "spectra",
            "code": "SPECTRA_LIKELY_TRANSMITTANCE_VALLEY",
            "message": "透射率谱不可直接正峰提取",
            "recommendation": "请先转换为吸光度 A = -log10(T)",
        },
    )
    ledger.append_event(
        "run_align",
        "graph_update_rejected",
        {
            "rationale": "xrd graph patch",
            "rejections": [{"code": "DAG_CYCLE_DETECTED", "message": "工作流存在环路"}],
        },
    )
    gates = HumanGateController(store, ledger)
    req = gates.request_gate(
        session_id=session_id,
        run_id="run_align",
        node_id="n1",
        gate_kind="select_fit_range",
        prompt="确认拟合区间",
    )
    gates.resolve_gate(req["approval_id"], "rejected", reviewer_note="区间包含屈服拐点，须收窄至 0.0005-0.002")

    store.append_event(session_id, "tool_error", {"error": "mechanics fit failed"})
    store.append_event(session_id, "tool_error", {"error": "mechanics fit failed"})

    bundle = collect_evidence(store=store, ledger=ledger, session_ids=[session_id], run_ids=["run_align"])
    by_kind = {item.kind: item for item in bundle.items if item.source == "ledger"}
    assert by_kind["guard_blocked"].correction == "请先转换为吸光度 A = -log10(T)"
    assert "DAG_CYCLE_DETECTED" in by_kind["graph_update_rejected"].failure_signal
    assert by_kind["human_gate_rejected"].failure_signal == "select_fit_range"
    assert "屈服拐点" in by_kind["human_gate_rejected"].correction

    store_items = [item for item in bundle.items if item.source == "session_store"]
    assert len(store_items) == 2
    assert store_items[0].id != store_items[1].id


def test_evolution_closed_loop_rejects_regression_weakening_code_and_eval_lock(tmp_path: Path) -> None:
    """Closed Loop 2: reject B+\\B- regression, boundary weakening, .py target, and mode='off'."""
    graph = build_default_asset_graph()
    store = SessionStore(tmp_path / "agent.sqlite3")
    session_id = store.create_session(title="Evolution Gate Negative Tests")

    # 1. User correction flow with regression benchmark failing B+ \ B- != empty
    bundle = collect_evidence(
        user_corrections=[
            {
                "domain": "battery",
                "summary": "高倍率下扣式半电池极化严重",
                "correction": "超过 2C 放电的扣式半电池不适用默认常温单电芯基线评估，超出适用范围。",
            }
        ]
    )
    findings = critique_evidence(bundle, graph)
    assert len(findings) == 1
    patches = propose_declarative_patches(findings, graph)
    assert len(patches) == 1
    patch = patches[0]
    assert patch.field == "out_of_scope_cases"

    controller = EvolutionController(store=store, storage_dir=tmp_path / "evo", mode="manual")

    def regressing_benchmark(candidate_graph):
        node = candidate_graph.get(patch.target_asset_id)
        # Simulate a regression when the candidate patch is present
        has_new = node is not None and patch.values[0] in node.out_of_scope_cases
        return {"case_baseline_pass": not has_new, "case_always_pass": True}

    rejected = controller.submit_patch(
        patch,
        graph,
        session_id=session_id,
        benchmark_runner=regressing_benchmark,
    )
    assert rejected["status"] == "rejected_by_gate"
    assert rejected["report"]["regressions"] == ["case_baseline_pass"]

    # 2. Boundary weakening text must be rejected
    weak_patch = KnowledgePatch(
        patch_id="patch_weak_01",
        target_asset_id=patch.target_asset_id,
        target_asset_type=patch.target_asset_type,
        field="known_limitations",
        operation="append_unique",
        values=("该方法无限制，可直接替代 Rietveld 精修。",),
        rationale="adversarial test",
        evidence_ids=("ev_test",),
    )
    weak_report = evaluate_patch(weak_patch, graph)
    assert not weak_report.passed
    assert weak_report.boundary_violations

    # 3. Attempting to patch Python source code must be rejected
    code_patch = KnowledgePatch(
        patch_id="patch_code_01",
        target_asset_id="materials_quality/science/xrd.py",
        target_asset_type="K",
        field="known_limitations",
        operation="append_unique",
        values=("should never touch python code",),
        rationale="adversarial code edit",
        evidence_ids=("ev_code",),
    )
    code_errors = validate_declarative_patch(code_patch, graph)
    assert any("file/code path" in err for err in code_errors)

    # 4. Evaluation lock (mode='off') must block all submissions
    locked_controller = EvolutionController(store=store, storage_dir=tmp_path / "evo_off", mode="off")
    disabled_res = locked_controller.submit_patch(patch, graph, session_id=session_id)
    assert disabled_res["status"] == "disabled"
    with pytest.raises(RuntimeError):
        locked_controller.apply_approved_patch(patch.patch_id, graph)


def test_pymatgen_xrd_plugin_graceful_degradation_and_contract() -> None:
    """Verify pymatgen XRD plugin degrades gracefully when absent and matches peaks accurately."""
    dummy_cif = "data_Si\n_cell_length_a 5.431\n"

    if not pymatgen_available():
        degraded = compute_theoretical_xrd_from_cif(dummy_cif)
        assert degraded["status"] == "unavailable"
        assert degraded["missing_dependency"] == "pymatgen"
        assert "langflow-materials-quality[compute]" in degraded["install_hint"]
        assert XRD_LIMITATION_NOTICE in degraded["known_limitations"]

    # Deterministic contract verification via injected calculator
    def mock_cif_calc(*, cif_text: str, wavelength: str, two_theta_range: tuple[float, float]):
        assert wavelength == "CuKa"
        return [
            {"two_theta_deg": 28.44, "intensity_rel": 100.0, "d_spacing_angstrom": 3.1355, "hkls": ["(1, 1, 1)"]},
            {"two_theta_deg": 47.30, "intensity_rel": 55.0, "d_spacing_angstrom": 1.9201, "hkls": ["(2, 2, 0)"]},
            {"two_theta_deg": 56.12, "intensity_rel": 30.0, "d_spacing_angstrom": 1.6375, "hkls": ["(3, 1, 1)"]},
        ]

    computed = compute_theoretical_xrd_from_cif(dummy_cif, calculator=mock_cif_calc)
    assert computed["status"] == "ok"
    assert computed["peak_count"] == 3
    assert XRD_LIMITATION_NOTICE in computed["known_limitations"]

    measured = [
        {"two_theta_deg": 28.49, "intensity_rel": 98.0},
        {"two_theta_deg": 47.25, "intensity_rel": 52.0},
        {"two_theta_deg": 72.10, "intensity_rel": 12.0},  # impurity / unmatched
    ]
    match = match_measured_xrd_peaks(measured, computed["peaks"], tol_deg=0.35)
    assert match["status"] == "ok"
    assert match["matched_count"] == 2
    assert len(match["unmatched_measured"]) == 1
    assert len(match["unmatched_theoretical"]) == 1
    assert match["mean_abs_delta_deg"] == pytest.approx(0.05, abs=1e-4)
    assert 0.5 < match["candidate_score"] < 1.0
    assert match["caveat"] == XRD_LIMITATION_NOTICE


def test_pybamm_battery_plugin_graceful_degradation_and_contract() -> None:
    """Verify PyBaMM plugin degrades gracefully when absent and reports provenance & boundaries."""
    if not pybamm_available():
        degraded = simulate_single_cell_discharge(
            model_name="SPM",
            parameter_set="Chen2020",
            c_rate=3.0,
            ambient_temp_C=-5.0,
        )
        assert degraded["status"] == "unavailable"
        assert degraded["missing_dependency"] == "pybamm"
        assert "langflow-materials-quality[compute]" in degraded["install_hint"]
        # High C-rate on SPM + sub-10C ambient temperature should emit 2 boundary warnings
        assert len(degraded["boundary_warnings"]) == 2
        assert degraded["provenance"]["parameter_set"] == "Chen2020"

    # Deterministic contract verification via injected backend (1A constant discharge for 3600s -> 1.0 Ah)
    def mock_pybamm_backend(**kwargs):
        assert kwargs["model_name"] == "SPMe"
        return {
            "time_s": [0.0, 1800.0, 3600.0],
            "voltage_V": [4.2, 3.7, 3.2],
            "current_A": [1.0, 1.0, 1.0],
        }

    sim = simulate_single_cell_discharge(
        model_name="SPMe",
        parameter_set="Chen2020",
        c_rate=1.0,
        ambient_temp_C=25.0,
        backend=mock_pybamm_backend,
    )
    assert sim["status"] == "ok"
    assert sim["boundary_warnings"] == []
    assert sim["summary"]["discharge_capacity_Ah"] == pytest.approx(1.0, abs=1e-4)
    assert sim["summary"]["discharge_energy_Wh"] == pytest.approx(3.7, abs=1e-4)
    assert sim["provenance"]["model_name"] == "SPMe"
    assert sim["known_limitations"]

    with pytest.raises(ValueError, match="non-decreasing"):
        simulate_single_cell_discharge(
            model_name="SPM",
            backend=lambda **_kw: {
                "time_s": [0.0, 100.0, 50.0],
                "voltage_V": [4.2, 3.8, 3.5],
                "current_A": [1.0, 1.0, 1.0],
            },
        )


def test_harness_evolution_approval_and_persistence(tmp_path: Path) -> None:
    """Verify StudyUIAgent.decide_approval applies evolution patches and persists across restarts."""
    from materials_quality.agent.file_workflow_client import FileWorkflowClient
    from materials_quality.agent.harness import StudyUIAgent

    wf_dir = tmp_path / "workflows"
    comp_dir = tmp_path / "components"
    comp_dir.mkdir()
    client = FileWorkflowClient(wf_dir, comp_dir, catalog_loader=lambda: {})
    agent = StudyUIAgent(tmp_path / "studyui.db", langflow=client)
    sid = agent.new_session("知识演进集成")

    bundle = collect_evidence(
        user_corrections=[
            {
                "domain": "xrd",
                "summary": "Mo靶波长前提未换算",
                "correction": "使用 Mo Kα 靶材时必须显式指定波长 0.71073 Å 的前提条件，不可沿用 Cu Kα 默认值。",
            }
        ]
    )
    findings = critique_evidence(bundle, agent.asset_graph)
    patches = propose_declarative_patches(findings, agent.asset_graph)
    assert len(patches) == 1
    patch = patches[0]

    sub = agent.evolution.submit_patch(patch, agent.asset_graph, session_id=sid)
    assert sub["status"] == "pending_approval"

    res = agent.decide_approval(sub["approval_id"], "approved")
    assert res["status"] == "completed"
    assert res["result"]["status"] == "applied"
    assert patch.values[0] in agent.asset_graph.get(patch.target_asset_id).known_limitations

    # Fresh agent instance loads persisted applied patches onto its AssetGraph.
    agent2 = StudyUIAgent(tmp_path / "studyui.db", langflow=client)
    reloaded = agent2.asset_graph.get(patch.target_asset_id)
    assert reloaded is not None
    assert patch.values[0] in reloaded.known_limitations


def test_pymatgen_xrd_boundary_and_one_to_one_matching() -> None:
    """Verify [0, 180] inclusive bounds and 1-to-1 greedy peak matching."""
    computed = compute_theoretical_xrd_from_cif(
        "data_Si\n",
        two_theta_range=(0.0, 180.0),
        calculator=lambda **_kw: [{"two_theta_deg": 30.0, "intensity_rel": 100.0}],
    )
    assert computed["status"] == "ok"
    # Two measured peaks near 30.0 should only match the single theoretical peak once.
    matched = match_measured_xrd_peaks(
        [{"two_theta_deg": 30.05, "intensity_rel": 90.0}, {"two_theta_deg": 30.2, "intensity_rel": 20.0}],
        computed["peaks"],
        tol_deg=0.35,
    )
    assert matched["matched_count"] == 1
    assert len(matched["unmatched_measured"]) == 1


def test_native_canvas_components_for_pymatgen_xrd_and_pybamm_battery() -> None:
    """Verify native canvas registration, frontend schema, graceful fallback, and execution."""
    from lfx.schema import DataFrame

    from materials_quality.science.catalog import component_class, get

    assert callable(get("materials.xrd_cif_screening")["callable"])
    assert callable(get("materials.pybamm_battery_sim")["callable"])

    xrd_cls = component_class("materials.xrd_cif_screening")
    bat_cls = component_class("materials.pybamm_battery_sim")
    assert xrd_cls.name == "PymatgenXrdScreening"
    assert bat_cls.name == "PybammBatterySim"

    xrd_frontend = xrd_cls().to_frontend_node()["data"]["node"]
    assert {"table", "report", "summary"} == {p["name"] for p in xrd_frontend["outputs"]}
    assert "cif_text" in xrd_frontend["template"]
    assert "wavelength" in xrd_frontend["template"]

    bat_frontend = bat_cls().to_frontend_node()["data"]["node"]
    assert {"table", "report", "summary"} == {p["name"] for p in bat_frontend["outputs"]}
    assert "model_name" in bat_frontend["template"]
    assert "c_rate" in bat_frontend["template"]

    if not pymatgen_available():
        degraded_xrd = xrd_cls().set(cif_text="data_Si\n_cell_length_a 5.43\n")
        xrd_report = degraded_xrd.build_report().data
        assert xrd_report["execution_status"] == "unavailable"
        assert xrd_report["data"]["missing_dependency"] == "pymatgen"
        assert "langflow-materials-quality[compute]" in degraded_xrd.build_summary().text
        assert degraded_xrd.build_table().empty

    if not pybamm_available():
        degraded_bat = bat_cls().set(model_name="SPM", c_rate=3.0, ambient_temp_C=0.0)
        bat_report = degraded_bat.build_report().data
        assert bat_report["execution_status"] == "unavailable"
        assert bat_report["data"]["missing_dependency"] == "pybamm"
        assert "langflow-materials-quality[compute]" in degraded_bat.build_summary().text
        assert degraded_bat.build_table().empty

    # Deterministic execution via injected calculator / backend
    xrd_node = xrd_cls().set(
        cif_text="data_Si\n_cell_length_a 5.43\n",
        measured_peaks_table=DataFrame(
            [{"two_theta_deg": 28.45, "intensity_rel": 95.0}]
        ),
    )
    xrd_node._calculator = lambda **_kw: [
        {"two_theta_deg": 28.44, "intensity_rel": 100.0, "d_spacing_angstrom": 3.135, "hkls": ["(1, 1, 1)"]}
    ]
    xrd_table = xrd_node.build_table()
    assert len(xrd_table) == 1
    xrd_rep = xrd_node.build_report().data
    assert xrd_rep["execution_status"] == "completed"
    assert xrd_rep["data"]["match_result"]["matched_count"] == 1
    assert "候选得分" in xrd_node.build_summary().text

    bat_node = bat_cls().set(model_name="SPMe", parameter_set="Chen2020", c_rate=1.0)
    bat_node._backend = lambda **_kw: {
        "time_s": [0.0, 1800.0, 3600.0],
        "voltage_V": [4.2, 3.7, 3.2],
        "current_A": [1.0, 1.0, 1.0],
    }
    bat_table = bat_node.build_table()
    assert len(bat_table) == 3
    bat_rep = bat_node.build_report().data
    assert bat_rep["execution_status"] == "completed"
    assert bat_rep["data"]["summary"]["discharge_capacity_Ah"] == pytest.approx(1.0, abs=1e-4)
    assert "PyBaMM" in bat_node.build_summary().text

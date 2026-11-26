"""Unit tests for the StudyUI Scientific Asset Graph and scope/limitations doc."""

from __future__ import annotations

from pathlib import Path

from materials_quality.assets import (
    AssetEdge,
    AssetGraph,
    AssetNode,
    build_default_asset_graph,
    extended_task_catalog,
    render_scope_and_limitations_markdown,
)
from materials_quality.science import material_tasks


def test_default_asset_graph_validates_cleanly():
    graph = build_default_asset_graph()
    assert graph.errors() == []
    assert [issue for issue in graph.validate() if issue.severity == "warning"] == []

    summary = graph.summary()
    assert summary["by_type"] == {
        "D": 9,
        "K": 41,
        "T": 72,
        "S": 14,
        "R": 4,
        "W": 5,
    }
    assert summary["total_assets"] == 145
    assert summary["total_edges"] > 300
    for wf in graph.by_type("W"):
        assert graph.edges_from(wf.id, kinds=("CALL",)), f"{wf.id} missing CALL edge"

    # Ensure PR #12's original 18-card task_catalog() remains untouched while
    # extended_task_catalog() adds battery cycling and TG/DSC thermal analysis.
    base_tasks = material_tasks.task_catalog()
    assert len(base_tasks) == 3
    assert sum(len(task["cards"]) for task in base_tasks) == 18

    extended = extended_task_catalog()
    assert {task["id"] for task in extended} == {"mechanics", "spectra", "xrd", "battery", "thermal"}
    assert sum(len(task["cards"]) for task in extended) == 30


def test_every_knowledge_skill_workflow_asset_declares_boundaries():
    graph = build_default_asset_graph()
    for asset_type in ("K", "S", "W"):
        for node in graph.by_type(asset_type):
            assert node.applicability_scope, f"{node.id} missing applicability_scope"
            assert node.known_limitations, f"{node.id} missing known_limitations"
            if asset_type == "W":
                assert node.out_of_scope_cases, f"{node.id} missing out_of_scope_cases"
                assert node.standards_refs, f"{node.id} missing standards_refs"


def test_role_subgraphs_mount_expected_assets_and_dependencies():
    graph = build_default_asset_graph()
    char_sub = graph.subgraph_for_role("R:characterization_analyst")
    lit_sub = graph.subgraph_for_role("R:literature_reviewer")
    qual_sub = graph.subgraph_for_role("R:data_quality_auditor")
    plan_sub = graph.subgraph_for_role("R:workflow_planner")

    for sub in (char_sub, lit_sub, qual_sub, plan_sub):
        assert sub.errors() == []

    # Characterization analyst mounts all 5 typical material task protocols.
    char_workflows = {node.id for node in char_sub.by_type("W")}
    assert char_workflows == {
        "W:protocol.mechanics",
        "W:protocol.spectra",
        "W:protocol.xrd",
        "W:protocol.battery",
        "W:protocol.thermal",
    }

    # Workflow planner mounts all 72 tools; data quality auditor mounts quality/io; literature
    # reviewer includes lit.result_evidence.
    assert plan_sub.summary()["by_type"]["T"] == 72
    assert plan_sub.summary()["by_type"]["T"] > lit_sub.summary()["by_type"]["T"]
    assert "T:lit.result_evidence" in lit_sub
    assert "T:MaterialUnitCheck" in qual_sub
    assert "T:io.table_import" in qual_sub
    assert "T:materials.battery_cycles" in char_sub
    assert "T:materials.xrd_cif_screening" in char_sub
    assert "T:materials.pybamm_battery_sim" in char_sub
    assert qual_sub.summary()["by_type"]["T"] >= 20


def test_optional_compute_plugins_indexed_with_skill_workflow_and_knowledge_edges():
    graph = build_default_asset_graph()
    xrd_tool = graph.get("T:materials.xrd_cif_screening")
    bat_tool = graph.get("T:materials.pybamm_battery_sim")
    assert xrd_tool is not None and xrd_tool.domain == "xrd"
    assert xrd_tool.metadata["category"] == "materials"
    assert bat_tool is not None and bat_tool.domain == "battery"
    assert bat_tool.metadata["category"] == "materials"

    assert any(e.source == "S:studyui-powder-xrd" and e.kind == "MOUNT" for e in graph.edges_to(xrd_tool.id))
    assert any(e.source == "W:protocol.xrd" and e.kind == "CALL" for e in graph.edges_to(xrd_tool.id))
    assert any(
        e.source == "K:task.xrd.references" and e.kind == "VERIFY" for e in graph.edges_to(xrd_tool.id)
    )

    assert any(
        e.source == "S:studyui-battery-cycling" and e.kind == "MOUNT" for e in graph.edges_to(bat_tool.id)
    )
    assert any(e.source == "W:protocol.battery" and e.kind == "CALL" for e in graph.edges_to(bat_tool.id))
    assert any(
        e.source == "K:task.battery.conditions" and e.kind == "VERIFY" for e in graph.edges_to(bat_tool.id)
    )


def test_graph_validation_catches_dangling_edges_and_missing_boundaries():
    graph = AssetGraph()
    graph.add_asset(
        AssetNode(
            id="K:incomplete_card",
            type="K",
            title="Incomplete Card",
            version="1.0.0",
            scope="user",
            description="Missing mandatory boundary declarations.",
        )
    )
    graph.add_edge(
        AssetEdge(
            source="K:incomplete_card",
            target="T:nonexistent_component",
            kind="DEP",
        )
    )

    codes = {issue.code for issue in graph.errors()}
    assert "MISSING_APPLICABILITY_SCOPE" in codes
    assert "MISSING_KNOWN_LIMITATIONS" in codes
    assert "DANGLING_EDGE_TARGET" in codes


def test_scope_and_limitations_doc_matches_asset_graph():
    graph = build_default_asset_graph()
    rendered = render_scope_and_limitations_markdown(graph)
    assert "W:protocol.mechanics" in rendered
    assert "W:protocol.spectra" in rendered
    assert "W:protocol.xrd" in rendered
    assert "W:protocol.battery" in rendered
    assert "W:protocol.thermal" in rendered
    assert "明确不支持" in rendered

    repo_root = Path(__file__).resolve().parents[2]
    doc_path = repo_root / "docs" / "scope-and-limitations.md"
    assert doc_path.is_file(), f"Missing generated doc at {doc_path}"
    assert doc_path.read_text(encoding="utf-8") == rendered

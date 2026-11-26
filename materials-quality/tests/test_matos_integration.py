"""MatOS integration: catalog completeness, schema checks, CLI adapter and APIs."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from materials_quality.agent import mcp_server
from materials_quality.agent.matos_api import create_matos_router
from materials_quality.assets import build_default_asset_graph
from materials_quality.matos import (
    MatOSInputError,
    MatOSToolNotFound,
    catalog,
    catalog_source,
    catalog_summary,
    describe_matos_tool,
    list_matos_tools,
    run_matos_tool,
    runner,
    validate_tool_input,
)

EXTERNAL_IDS = {
    "atomistic-toolchain-catalog",
    "battery-electrochem-catalog",
    "conda-environment-catalog",
    "conda-environment-manager",
    "deep-research-search",
    "document-parse",
    "gemini-vision-analyze",
    "literature-access",
    "local-toolchain-preflight",
    "materials-runtime-inventory",
    "mlip-model-catalog",
    "mp-query",
    "scip-toolchain-catalog",
    "web-read",
}
BUILTIN_IDS = {"agent-orchestration", "files-core", "shell-core", "web-research"}


@pytest.fixture
def no_cli(monkeypatch):
    monkeypatch.setattr(runner, "find_matos_cli", lambda: None)


@pytest.fixture
def fake_cli(monkeypatch):
    monkeypatch.setattr(runner, "find_matos_cli", lambda: "/opt/fake/matos")


def test_catalog_matches_matOS_benchmark_inventory():
    summary = catalog_summary()
    assert summary["tool_count"] == 18
    assert summary["external_tool_count"] == 14
    assert summary["builtin_pack_count"] == 4
    assert set(summary["external_tool_ids"]) == EXTERNAL_IDS
    assert set(summary["builtin_pack_ids"]) == BUILTIN_IDS

    source = catalog_source()
    assert source["repository"] == "https://github.com/DingyangLyu/MatOS"
    assert source["license"] == "PolyForm Noncommercial License 1.0.0"
    assert source["required_notice"].startswith("Required Notice: Copyright 2026 The MatOS Authors")
    assert source["commit"]

    for tool in catalog.all_tools():
        assert tool["id"]
        assert tool["ref"] == f"tool:{tool['id']}"
        assert tool["name"] and tool["description"]
        assert tool["call_method"]
        assert tool["provenance"]["asset_path"].endswith("/asset.json")
        assert tool["input_schema"]["type"] == "object"
        if tool["kind"] == "external-tool":
            assert tool["id"] in EXTERNAL_IDS
            assert tool["call_method"] == "matos assets run-tool"
            assert tool["mcp_name"] and tool["timeout_ms"] > 0
            assert tool["entrypoint"] == "./tool.py"
        else:
            assert tool["id"] in BUILTIN_IDS
            assert tool["builtin_tools"]
            assert tool["availability"] == "matos_runtime_only"


def test_catalog_records_required_binaries_and_env():
    by_id = {tool["id"]: tool for tool in catalog.all_tools()}
    assert by_id["conda-environment-manager"]["required_binaries"] == ["conda", "pip"]
    assert "xtb" in by_id["atomistic-toolchain-catalog"]["probed_binaries"]
    assert by_id["mp-query"]["required_env"] == ["MP_API_KEY"]
    assert by_id["gemini-vision-analyze"]["required_env"] == ["GEMINI_API_KEY"]
    assert by_id["mp-query"]["network_required"] is True
    assert by_id["document-parse"]["network_required"] is False


def test_tool_resolution_accepts_ids_refs_and_mcp_bindings():
    for alias in (
        "mp-query",
        "tool:mp-query",
        "tool:mp-query@1.0.0",
        "MP_QUERY",
        "mcp__matos_asset__mp_query",
    ):
        assert catalog.resolve_tool(alias)["id"] == "mp-query"
    with pytest.raises(MatOSToolNotFound):
        catalog.resolve_tool("does-not-exist")


def test_schema_validation_accepts_valid_and_rejects_invalid_inputs():
    mp_query = catalog.resolve_tool("mp-query")
    assert validate_tool_input(mp_query, {"formula": "SiO2"}) == {"formula": "SiO2"}
    assert validate_tool_input(mp_query, {"material_id": "mp-149"})["material_id"] == "mp-149"

    with pytest.raises(MatOSInputError):
        validate_tool_input(mp_query, {})
    with pytest.raises(MatOSInputError):
        validate_tool_input(mp_query, {"formula": "Si", "unexpected": 1})
    with pytest.raises(MatOSInputError):
        validate_tool_input(mp_query, {"formula": "Si", "limit": "many"})
    with pytest.raises(MatOSInputError):
        validate_tool_input(mp_query, ["Si"])

    manager = catalog.resolve_tool("conda-environment-manager")
    with pytest.raises(MatOSInputError):
        validate_tool_input(manager, {"action": "delete_everything", "envName": "x"})
    validate_tool_input(manager, {"action": "probe", "envName": "defects"})


def test_unavailable_behavior_is_explicit_and_never_fake_success(no_cli):
    status = runner.runtime_status()
    assert status["available"] is False
    assert "STUDYUI_MATOS_CLI" in status["install_hint"]

    result = run_matos_tool("mp-query", {"formula": "Si"})
    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert result["error"]
    assert result["install_hint"] == status["install_hint"]
    assert "result" not in result

    listed = list_matos_tools(available_only=True)
    assert listed["count"] == 0
    described = describe_matos_tool("web-read")
    assert described["availability"]["status"] == "unavailable"


def test_builtin_pack_is_runtime_only_even_when_cli_exists(fake_cli):
    result = run_matos_tool("agent-orchestration", {})
    assert result["ok"] is False
    assert result["status"] == "matos_runtime_only"
    assert "matos_asset" in result["error"]
    assert "matos_asset" in result["install_hint"]

    listed = list_matos_tools(available_only=True)
    assert listed["count"] == 14  # only executable external tools
    assert {item["kind"] for item in listed["tools"]} == {"external-tool"}


def test_execution_uses_run_tool_cli_and_returns_structured_result(fake_cli, monkeypatch):
    captured = {}

    def fake_execute(command, *, input_text, timeout, cwd):
        captured.update(command=command, input_text=input_text, timeout=timeout, cwd=cwd)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "tool": "tool:mp-query",
                    "mcpName": "mp_query",
                    "exitCode": 0,
                    "timedOut": False,
                    "result": {"count": 1, "entries": [{"material_id": "mp-149"}]},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(runner, "_execute", fake_execute)
    result = run_matos_tool("mp-query", {"formula": "Si"}, timeout_seconds=12)

    assert captured["command"] == [
        "/opt/fake/matos",
        "assets",
        "run-tool",
        "tool:mp-query",
        "--input-file",
        "-",
        "--json",
    ]
    assert json.loads(captured["input_text"]) == {"formula": "Si"}
    assert captured["timeout"] == 12
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["result"]["entries"][0]["material_id"] == "mp-149"
    assert "stderr" in result


def test_execution_reports_tool_failure_and_timeout(fake_cli, monkeypatch):
    def failing_execute(command, *, input_text, timeout, cwd):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {
                    "ok": False,
                    "tool": "tool:mp-query",
                    "timedOut": False,
                    "result": {"error": "MP_API_KEY is not configured"},
                }
            ),
            stderr="MP_API_KEY is not configured",
        )

    monkeypatch.setattr(runner, "_execute", failing_execute)
    failure = run_matos_tool("mp-query", {"formula": "Si"})
    assert failure["ok"] is False
    assert failure["status"] == "failed"
    assert failure["exit_code"] == 1
    assert "MP_API_KEY" in failure["error"]

    def timeout_execute(command, *, input_text, timeout, cwd):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(runner, "_execute", timeout_execute)
    timed_out = run_matos_tool("mp-query", {"formula": "Si"})
    assert timed_out["ok"] is False
    assert timed_out["status"] == "timeout"
    assert "timed out" in timed_out["error"]


def test_invalid_input_short_circuits_before_process_execution(fake_cli, monkeypatch):
    calls = []

    def fake_execute(*args, **kwargs):
        calls.append(args)
        raise AssertionError("execution must not start for invalid input")

    monkeypatch.setattr(runner, "_execute", fake_execute)
    with pytest.raises(MatOSInputError):
        run_matos_tool("mp-query", {})
    assert calls == []


def test_mcp_handlers_expose_catalog_and_safe_unavailable_path(no_cli):
    names = [tool.name for tool in mcp_server.TOOLS]
    assert {"list_matos_tools", "describe_matos_tool", "run_matos_tool"} <= set(names)
    assert len(names) <= 20

    listed = mcp_server._list_matos_tools({})
    assert listed["count"] == 18
    assert listed["runtime"]["status"] == "unavailable"

    described = mcp_server._describe_matos_tool({"tool": "mp-query"})
    assert described["id"] == "mp-query"
    assert described["input_schema"]["properties"]["formula"]
    assert described["availability"]["available"] is False

    missing = mcp_server._describe_matos_tool({"tool": "nope"})
    assert missing["status"] == "not_found"

    run = mcp_server._run_matos_tool({"tool": "mp-query", "input": {"formula": "Si"}})
    assert run["ok"] is False
    assert run["status"] == "unavailable"

    invalid = mcp_server._run_matos_tool({"tool": "mp-query", "input": {}})
    assert invalid["ok"] is False
    assert invalid["status"] == "invalid_input"


def test_rest_router_lists_describes_runs_and_rejects_bad_input(no_cli):
    app = FastAPI()
    app.include_router(create_matos_router())
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        status = client.get("/api/matos/status")
        assert status.status_code == 200
        assert status.json()["available"] is False

        tools = client.get("/api/matos/tools", params={"kind": "external-tool"})
        assert tools.status_code == 200
        assert tools.json()["count"] == 14

        detail = client.get("/api/matos/tools/tool:mp-query")
        assert detail.status_code == 200
        assert detail.json()["id"] == "mp-query"

        assert client.get("/api/matos/tools/unknown").status_code == 404

        run = client.post("/api/matos/tools/mp-query/run", json={"formula": "Si"})
        assert run.status_code == 200
        assert run.json()["ok"] is False
        assert run.json()["status"] == "unavailable"

        invalid = client.post("/api/matos/tools/mp-query/run", json={})
        assert invalid.status_code == 422

        not_object = client.post("/api/matos/tools/mp-query/run", json=["Si"])
        assert not_object.status_code == 422


def test_asset_graph_registers_matOS_tools_with_provenance_and_availability():
    graph = build_default_asset_graph()
    matos_nodes = [node for node in graph.by_type("T") if node.id.startswith("T:matos.")]
    assert len(matos_nodes) == 18
    assert graph.errors() == []

    node = graph.get("T:matos.mp-query")
    assert node is not None
    assert node.metadata["provider"] == "MatOS"
    assert node.metadata["provider_license"] == "PolyForm Noncommercial License 1.0.0"
    assert node.metadata["provider_notice"].startswith("Required Notice: Copyright 2026 The MatOS Authors")
    assert node.metadata["source_ref"] == "tool:mp-query"
    assert node.metadata["source_asset_path"] == "matos-core/tools/mp-query/asset.json"
    assert node.metadata["category"] == "matos"
    assert node.metadata["availability"] == "requires_matos_cli"
    assert node.metadata["required_env"] == ["MP_API_KEY"]

    builtin = graph.get("T:matos.agent-orchestration")
    assert builtin is not None
    assert builtin.metadata["availability"] == "matos_runtime_only"
    assert builtin.metadata["executable"] is False

    planner_mounts = {edge.target for edge in graph.edges_from("R:workflow_planner", kinds=("MOUNT",))}
    assert {node.id for node in matos_nodes} <= planner_mounts


def test_governance_scope_payload_exposes_matOS_tools_and_markdown_section():
    from materials_quality.agent.server import _governance_scope_payload

    graph = build_default_asset_graph()
    payload = _governance_scope_payload(SimpleNamespace(asset_graph=graph))
    assert len(payload["matos_tools"]) == 18
    assert payload["summary"]["by_type"]["T"] == 90
    mp_query = next(item for item in payload["matos_tools"] if item["id"] == "T:matos.mp-query")
    assert mp_query["source_ref"] == "tool:mp-query"
    assert mp_query["availability"] == "requires_matos_cli"
    assert "## 四、MatOS 外部工具接入（可选）" in payload["markdown"]
    assert "`T:matos.agent-orchestration`" in payload["markdown"]
    assert "matos_runtime_only" in payload["markdown"]

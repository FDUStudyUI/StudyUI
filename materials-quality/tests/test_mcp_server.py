import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from materials_quality.agent import mcp_server


def test_tool_surface_is_compact_and_named():
    names = [tool.name for tool in mcp_server.TOOLS]
    assert len(names) <= 20
    assert len(names) == len(set(names))
    assert "run_science_operation" in names
    assert "run_workflow" in names
    assert "workflow_task_status" in names
    assert "inspect_table" in names


def test_science_catalog_surface():
    result = mcp_server._list_science_operations({})
    assert result["count"] == 48
    described = mcp_server._describe_science_operation({"operation": "stats.distribution"})
    assert described["definition"]["title"] == "分布检查"
    assert described["definition"]["form_fields"]


def test_run_science_operation_with_inline_table():
    result = mcp_server._run_science_operation(
        {
            "operation": "stats.distribution",
            "config": {"column": "value", "bins": 4, "profile": "preview"},
            "table_csv": "value\n1\n2\n3\n4\n5\n6\n7\n8\n",
        }
    )
    assert result["operation"] == "stats.distribution"
    assert result["result"]


def test_inspect_table_reports_shape_and_head():
    result = mcp_server._inspect_table({"table_csv": "a,b\n1,2\n3,4\n"})
    assert result["columns"] == ["a", "b"]
    assert result["row_count"] == 2
    assert len(result["head"]["rows"]) == 2


def test_material_tasks_are_listed():
    result = mcp_server._list_material_tasks({})
    assert result["count"] == 3
    assert {task["id"] for task in result["tasks"]} == {"mechanics", "spectra", "xrd"}


def test_task_status_summarizes_large_results_without_mutating_full_result(monkeypatch):
    from types import SimpleNamespace

    job = {
        "id": "job",
        "status": "completed",
        "result": {
            "run_id": "run1",
            "guard_report": {"status": "pass"},
            "outputs": [{"node_id": "n1", "outputs": {"table": {"rows": list(range(10000))}}}],
        },
    }
    monkeypatch.setattr(mcp_server, "_workflow_queue", lambda: SimpleNamespace(get=lambda _: job))
    brief = mcp_server._task_status({"task_id": "job"})
    full = mcp_server._task_status({"task_id": "job", "include_full_result": True})
    assert brief["result_summarized"]
    assert brief["result"]["run_id"] == "run1"
    assert brief["result"]["guard_report"] == {"status": "pass"}
    assert len(json.dumps(brief)) < 8000
    assert len(full["result"]["outputs"][0]["outputs"]["table"]["rows"]) == 10000


def test_get_workflow_defaults_to_existing_summary_and_can_return_definition(monkeypatch):
    from types import SimpleNamespace

    flow = {
        "id": "demo",
        "name": "Demo",
        "data": {
            "nodes": [
                {
                    "id": "n1",
                    "data": {
                        "type": "Demo",
                        "node": {
                            "template": {"code": {"value": "x" * 100_000}, "column": {"value": "strain"}},
                            "outputs": [],
                        },
                    },
                }
            ],
            "edges": [],
        },
    }
    monkeypatch.setattr(mcp_server, "_workflow_store", lambda: SimpleNamespace(read=lambda _: (flow, "rev")))
    brief = mcp_server._get_workflow({"flow_id": "demo"})
    full = mcp_server._get_workflow({"flow_id": "demo", "include_definition": True})
    assert brief["revision"] == full["revision"] == "rev"
    assert brief["workflow"]["nodes"][0]["config"]["column"] == "strain"
    assert not brief["definition_included"]
    assert len(json.dumps(brief)) < 2000
    assert full["workflow"] == flow and full["definition_included"]


def test_demo_datasets_are_listed():
    result = mcp_server._list_demo_datasets({})
    assert result["count"] == 5
    assert {item["id"] for item in result["datasets"]} == {
        "ti64_tensile",
        "raman_spectra",
        "material_contrast",
        "zirconia_xrd",
        "battery_cycle",
    }


def test_load_demo_dataset_copies_into_workspace(tmp_path):
    result = mcp_server._load_demo_dataset({"dataset_id": "ti64_tensile", "directory": str(tmp_path)})
    path = Path(result["path"])
    assert path.is_file()
    assert path.parent == tmp_path
    assert path.read_bytes()


def _read_json_line(lines: queue.Queue, msg_id: int, timeout: float = 60) -> tuple[dict, list[str]]:
    seen = []
    while True:
        line = lines.get(timeout=timeout)
        seen.append(line)
        if not line.strip():
            continue
        message = json.loads(line)
        if message.get("id") == msg_id:
            return message, seen


def test_copy_workflow_creates_an_independent_flow(tmp_path, monkeypatch):
    from materials_quality.agent.workflow_files import WorkflowFileStore

    monkeypatch.setenv("STUDYUI_WORKFLOWS_DIR", str(tmp_path))
    store = WorkflowFileStore(tmp_path)
    template = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "模板",
        "data": {"nodes": [], "edges": []},
        "is_component": False,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    store.save(template, create_only=True)

    result = mcp_server._copy_workflow({"template_id": template["id"], "name": "副本"})

    assert result["flow_id"] != template["id"]
    assert result["name"] == "副本"
    copied, _ = store.read(result["flow_id"])
    assert copied["data"] == template["data"]


def test_stdio_transport_keeps_stdout_as_json(tmp_path):
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "STUDYUI_WORKFLOWS_DIR": str(tmp_path / "workflows"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "materials_quality.agent.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    lines: queue.Queue = queue.Queue()

    def reader() -> None:
        for line in process.stdout:
            lines.put(line.rstrip("\n"))

    threading.Thread(target=reader, daemon=True).start()

    def send(message: dict) -> None:
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    all_lines: list[str] = []
    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            }
        )
        _, seen = _read_json_line(lines, 1)
        all_lines.extend(seen)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools, seen = _read_json_line(lines, 2)
        all_lines.extend(seen)
        assert len(tools["result"]["tools"]) == len(mcp_server.TOOLS)
        send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "studyui_info", "arguments": {}},
            }
        )
        info, seen = _read_json_line(lines, 3)
        all_lines.extend(seen)
        payload = json.loads(info["result"]["content"][0]["text"])
        assert payload["ok"] is True
        assert payload["server"] == "studyui"
    finally:
        process.kill()
        process.wait(timeout=10)

    for line in all_lines:
        if line.strip():
            json.loads(line)


def test_mcp_workflow_reuses_cooperative_queue(monkeypatch):
    from materials_quality.agent.tasks import checkpoint

    started, release = threading.Event(), threading.Event()
    later_steps = []

    def run(arguments):
        started.set()
        assert release.wait(5)
        checkpoint()
        later_steps.append("must not run")

    monkeypatch.setattr(mcp_server, "_WORKFLOW_QUEUE", None)
    monkeypatch.setattr(mcp_server, "_run_workflow_sync", run)
    task = mcp_server._run_workflow({"flow_id": "test-flow"})
    assert started.wait(5)
    assert mcp_server._cancel_task(task)["status"] == "cancelled"
    release.set()
    mcp_server._workflow_queue()._queue.join()
    assert later_steps == []
    assert mcp_server._task_status(task)["result"] is None


def test_mcp_workflow_respects_project_read_only(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from materials_quality.agent.permissions import PermissionStore

    settings = tmp_path / "studyui-settings.json"
    settings.write_text(json.dumps({"default_preset": "read_only"}), encoding="utf-8")
    assert PermissionStore(settings).get_preset("project") == "read_only"
    monkeypatch.setenv("STUDYUI_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setattr(
        mcp_server,
        "_workflow_client",
        lambda *a: SimpleNamespace(
            get_flow=lambda fid: {"folder_id": "project"},
            run_flow=lambda *a, **kw: pytest.fail("read-only flow must not execute"),
        ),
    )
    with pytest.raises(mcp_server.StudyUIToolError, match="只读"):
        mcp_server._run_workflow_sync({"flow_id": "read-only-flow"})

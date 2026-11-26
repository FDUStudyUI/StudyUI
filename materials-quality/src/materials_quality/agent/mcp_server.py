"""StudyUI's stdio MCP server for the DSH Web surface.

Exposes a compact tool surface over StudyUI's deterministic science catalog and
saved workflow files. Business output never reaches stdout: file descriptor 1
is redirected to stderr at startup and the JSON-RPC transport keeps a duplicate.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import lru_cache
from io import TextIOWrapper
from pathlib import Path
from typing import Any

import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Importing C extensions from inside the running MCP event loop deadlocks on
# Windows; preload them at startup and never import them per request.
os.environ.setdefault("MPLBACKEND", "Agg")

SERVER_NAME = "studyui"
MAX_RESULT_CHARS = 1_500_000
REPO_ROOT = Path(__file__).resolve().parents[4]

_WORKFLOW_QUEUE = None
_QUEUE_LOCK = threading.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="studyui-mcp")


class StudyUIToolError(RuntimeError):
    """A tool request the server can explain to the model."""


def runtime_root() -> Path | None:
    value = os.environ.get("STUDYUI_RUNTIME_ROOT", "").strip()
    return Path(value).expanduser().resolve() if value else None


def workflows_dir() -> Path:
    value = os.environ.get("STUDYUI_WORKFLOWS_DIR", "").strip()
    return Path(value).expanduser().resolve() if value else REPO_ROOT / "workflows"


def components_dir() -> Path:
    value = os.environ.get("STUDYUI_COMPONENTS_DIR", "").strip()
    if value:
        return Path(value).expanduser().resolve()
    return REPO_ROOT / "materials-quality" / "components"


def _bounded_text(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return json.dumps(
        {
            "ok": payload.get("ok", True) if isinstance(payload, dict) else True,
            "truncated": True,
            "chars": len(text),
            "note": "结果超过 1.5 MB；请缩小请求范围，或把输出写入工作区文件后读取。",
        },
        ensure_ascii=False,
    )


def _result(payload: Any, *, ok: bool = True) -> list[TextContent]:
    data = {"ok": ok, **payload} if isinstance(payload, dict) else {"ok": ok, "result": payload}
    return [TextContent(type="text", text=_bounded_text(data))]


def _read_table(arguments: dict) -> Any:
    path = str(arguments.get("table_path") or "").strip()
    inline = arguments.get("table_csv")
    if path:
        from materials_quality.science_tools import _load_table

        return _load_table(path)
    if inline:
        import pandas as pd

        return pd.read_csv(io.StringIO(str(inline)))
    return None


def _list_science_operations(arguments: dict) -> dict:
    from materials_quality.science import catalog
    from materials_quality.science.categories import category_label

    wanted = str(arguments.get("category") or "").strip()
    items = []
    for item in catalog.entries():
        if wanted and item.get("category") != wanted:
            continue
        items.append(
            {
                "key": item["key"],
                "title": item.get("title", ""),
                "category": item.get("category", ""),
                "category_label": item.get("category_label") or category_label(item.get("category", "")),
                "requirement": item.get("requirement", ""),
            }
        )
    return {"count": len(items), "operations": items}


def _describe_science_operation(arguments: dict) -> dict:
    from materials_quality.science import catalog

    operation = str(arguments.get("operation") or "").strip()
    if not operation:
        raise StudyUIToolError("operation is required")
    item = catalog.get(operation)
    return {"operation": operation, "definition": {k: v for k, v in item.items() if k != "callable"}}


def _run_science_operation(arguments: dict) -> dict:
    from materials_quality.science import catalog
    from materials_quality.science_tools import _jsonable

    operation = str(arguments.get("operation") or "").strip()
    if not operation:
        raise StudyUIToolError("operation is required")
    item = catalog.get(operation)
    config = arguments.get("config") or {}
    if not isinstance(config, dict):
        raise StudyUIToolError("config must be a JSON object")
    data = arguments.get("data")
    table = _read_table(arguments)
    try:
        value = item["callable"](table, config=config, data=data)
    except TypeError:
        value = item["callable"](table, config=config)
    return {
        "operation": operation,
        "title": item.get("title", ""),
        "result": _jsonable(value),
    }


def _workflow_store():
    from materials_quality.agent.workflow_files import WorkflowFileStore

    return WorkflowFileStore(workflows_dir())


def _list_workflows(_arguments: dict) -> dict:
    flows = _workflow_store().list()
    summaries = [
        {key: flow.get(key) for key in ("id", "name", "description", "folder_id", "updated_at")}
        for flow in flows
    ]
    return {"count": len(summaries), "workflows": summaries}


def _get_workflow(arguments: dict) -> dict:
    from .workflow import flow_summary

    flow_id = str(arguments.get("flow_id") or "").strip()
    if not flow_id:
        raise StudyUIToolError("flow_id is required")
    flow, revision = _workflow_store().read(flow_id)
    full = bool(arguments.get("include_definition", False))
    return {
        "flow_id": flow_id,
        "revision": revision,
        "definition_included": full,
        "workflow": flow if full else flow_summary(flow),
    }


def _copy_workflow(arguments: dict) -> dict:
    import copy
    import uuid
    from datetime import datetime, timezone

    template_id = str(arguments.get("template_id") or "").strip()
    if not template_id:
        raise StudyUIToolError("template_id is required")
    store = _workflow_store()
    flow, _revision = store.read(template_id)
    duplicate = copy.deepcopy(flow)
    duplicate["id"] = str(uuid.uuid4())
    duplicate["name"] = str(arguments.get("name") or (flow.get("name") or "工作流") + " 副本")[:160]
    now = datetime.now(timezone.utc).isoformat()
    duplicate["created_at"] = now
    duplicate["updated_at"] = now
    duplicate.pop("version_token", None)
    duplicate.pop("user_id", None)
    revision = store.save(duplicate, create_only=True)
    return {
        "flow_id": duplicate["id"],
        "name": duplicate["name"],
        "revision": revision,
        "template_id": template_id,
    }


@lru_cache(maxsize=4)
def _workflow_client(root: Path, components: Path):
    from materials_quality.agent.file_workflow_client import FileWorkflowClient

    return FileWorkflowClient(root, components)


def _run_workflow_sync(arguments: dict) -> dict:
    from materials_quality.agent.permissions import PermissionStore
    from materials_quality.agent.workflow import flow_digest

    flow_id = str(arguments.get("flow_id") or "").strip()
    if not flow_id:
        raise StudyUIToolError("flow_id is required")
    client = _workflow_client(workflows_dir(), components_dir())
    # Validate exactly as the executor does, then pin the run to that snapshot.
    flow = client.get_flow(flow_id)
    settings_root = runtime_root() or REPO_ROOT / ".demo-runtime"
    if (
        PermissionStore(settings_root / "studyui-settings.json").get_preset(flow.get("folder_id"))
        == "read_only"
    ):
        raise StudyUIToolError("当前项目为只读，无法运行工作流。")
    return client.run_flow(
        flow_id,
        tweaks=arguments.get("tweaks") or None,
        input_value=str(arguments.get("input_value") or ""),
        include_all_nodes=bool(arguments.get("include_all_nodes") or False),
        external_data_approved=bool(arguments.get("external_data_approved") or False),
        expected_digest=flow_digest(flow),
        expected_project_id=flow.get("folder_id"),
    )


def _workflow_queue():
    global _WORKFLOW_QUEUE
    from .workflow_jobs import WorkflowJobQueue

    # Tool handlers may arrive concurrently; creation uses the existing module lock.
    with _QUEUE_LOCK:
        if _WORKFLOW_QUEUE is None:
            _WORKFLOW_QUEUE = WorkflowJobQueue(
                lambda flow_id, **options: _run_workflow_sync({"flow_id": flow_id, **options})
            )
        return _WORKFLOW_QUEUE


def _run_workflow(arguments: dict) -> dict:
    options = dict(arguments)
    flow_id = str(options.pop("flow_id", "")).strip()
    if not flow_id:
        raise StudyUIToolError("flow_id is required")
    approved = bool(options.pop("external_data_approved", False))
    job = _workflow_queue().submit(flow_id, external_data_approved=approved, run_options=options)
    return {
        "task_id": job["id"],
        "kind": "workflow",
        "status": job["status"],
        "poll_with": "workflow_task_status",
    }


def _task_status(arguments: dict) -> dict:
    job = _workflow_queue().get(str(arguments.get("task_id") or ""))
    if job is None:
        raise StudyUIToolError("unknown task")
    result = job.get("result")
    if isinstance(result, dict) and not arguments.get("include_full_result", False):
        from .harness import MAX_TOOL_RESULT_CHARS, _bounded_run_workflow_result

        if len(json.dumps(result, ensure_ascii=False, default=str)) > MAX_TOOL_RESULT_CHARS:
            summary = _bounded_run_workflow_result({"result": result})["result"]
            job = {**job, "result": {**result, **summary}, "result_summarized": True}
    return {**job, "task_id": job["id"], "kind": "workflow"}


def _cancel_task(arguments: dict) -> dict:
    job = _workflow_queue().cancel(str(arguments.get("task_id") or ""))
    if job is None:
        raise StudyUIToolError("unknown task")
    return {"task_id": job["id"], "status": job["status"]}


def _list_material_tasks(_arguments: dict) -> dict:
    from materials_quality.science.material_tasks import task_catalog

    tasks = task_catalog()
    return {"count": len(tasks), "tasks": tasks}


def _get_material_task(arguments: dict) -> dict:
    from materials_quality.science.material_tasks import task_catalog

    task_id = str(arguments.get("task_id") or "").strip()
    for task in task_catalog():
        if task["id"] == task_id:
            return {"task": task}
    raise StudyUIToolError(f"unknown material task: {task_id}")


def _list_demo_datasets(_arguments: dict) -> dict:
    from materials_quality.demos.catalog import list_datasets

    datasets = [
        {
            key: item.get(key)
            for key in ("id", "title", "filename", "desc", "format", "row_count", "columns", "units")
        }
        for item in list_datasets()
    ]
    return {"count": len(datasets), "datasets": datasets}


def _load_demo_dataset(arguments: dict) -> dict:
    from materials_quality.demos.catalog import get_dataset, read_demo_bytes

    dataset_id = str(arguments.get("dataset_id") or "").strip()
    if not dataset_id:
        raise StudyUIToolError("dataset_id is required")
    item = get_dataset(dataset_id)
    directory = Path(str(arguments.get("directory") or "demo_datasets")).expanduser()
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    directory.mkdir(parents=True, exist_ok=True)
    target = (directory / item["filename"]).resolve()
    target.write_bytes(read_demo_bytes(dataset_id))
    prompt = str(item.get("prompt") or "").replace("{path}", str(target))
    return {
        "dataset_id": dataset_id,
        "title": item.get("title", ""),
        "filename": item.get("filename", ""),
        "path": str(target),
        "prompt": prompt,
        "columns": item.get("columns"),
        "units": item.get("units"),
        "limitations": item.get("limitations"),
    }


def _inspect_table(arguments: dict) -> dict:
    table = _read_table(arguments)
    if table is None:
        raise StudyUIToolError("table_path or table_csv is required")
    from materials_quality.science_tools import _jsonable

    return {
        "columns": [str(column) for column in table.columns],
        "dtypes": {str(column): str(dtype) for column, dtype in table.dtypes.items()},
        "row_count": int(len(table)),
        "head": _jsonable(table.head(10)),
    }


def _studyui_info(_arguments: dict) -> dict:
    from materials_quality.science import catalog

    return {
        "server": SERVER_NAME,
        "runtime_root": str(runtime_root()) if runtime_root() else "",
        "workflows_dir": str(workflows_dir()),
        "components_dir": str(components_dir()),
        "operation_count": len(catalog.entries()),
        "workflow_count": len(_workflow_store().list()),
    }


def _tool(
    name: str,
    description: str,
    properties: dict | None = None,
    required: list[str] | None = None,
) -> Tool:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        schema["required"] = required
    return Tool(name=name, description=description, inputSchema=schema)


_OBJECT = {"type": "object", "additionalProperties": True}
_STRING = {"type": "string"}
_BOOL = {"type": "boolean"}

TOOLS = [
    _tool(
        "list_science_operations",
        "列出 StudyUI 的 48 个确定性科学操作（可按 category 过滤）。",
        {"category": _STRING},
    ),
    _tool(
        "describe_science_operation",
        "返回一个科学操作的完整定义：输入表/数据需求与 form_fields 配置 schema。",
        {"operation": _STRING},
        ["operation"],
    ),
    _tool(
        "run_science_operation",
        "执行一个确定性科学操作。表格可通过 table_path（工作区文件）或 table_csv（内联 CSV）提供。",
        {
            "operation": _STRING,
            "config": _OBJECT,
            "data": _OBJECT,
            "table_path": _STRING,
            "table_csv": _STRING,
        },
        ["operation"],
    ),
    _tool("list_workflows", "列出已保存的 StudyUI 画布工作流。"),
    _tool(
        "get_workflow",
        "读取工作流结构、参数与版本。仅需原始节点定义时设置 include_definition=true。",
        {"flow_id": _STRING, "include_definition": {"type": "boolean", "default": False}},
        ["flow_id"],
    ),
    _tool(
        "copy_workflow",
        "从已保存工作流复制一个新工作流（作为模板修改）；返回新 flow_id。",
        {"template_id": _STRING, "name": _STRING},
        ["template_id"],
    ),
    _tool(
        "run_workflow",
        "在后台运行一个已保存工作流，立即返回 task_id；用 workflow_task_status 轮询。",
        {
            "flow_id": _STRING,
            "tweaks": _OBJECT,
            "input_value": _STRING,
            "include_all_nodes": _BOOL,
            "external_data_approved": _BOOL,
        },
        ["flow_id"],
    ),
    _tool(
        "workflow_task_status",
        "查询运行状态与结果摘要。需要完整曲线等数据时设置 include_full_result=true。",
        {"task_id": _STRING, "include_full_result": {"type": "boolean", "default": False}},
        ["task_id"],
    ),
    _tool(
        "cancel_workflow_task",
        "请求取消一个 run_workflow 后台任务（尽力而为）。",
        {"task_id": _STRING},
        ["task_id"],
    ),
    _tool("list_material_tasks", "列出 StudyUI 的材料任务卡（力学、光谱、XRD）。"),
    _tool(
        "get_material_task",
        "返回一个材料任务卡的完整条件、操作与来源。",
        {"task_id": _STRING},
        ["task_id"],
    ),
    _tool(
        "list_demo_datasets",
        "列出 StudyUI 的五个材料演示数据集（钛合金拉伸、光谱、组间对照、XRD、电池循环）。",
    ),
    _tool(
        "load_demo_dataset",
        "把演示数据集复制到工作区（默认 demo_datasets/）并返回文件路径与分析提示词。",
        {"dataset_id": _STRING, "directory": _STRING},
        ["dataset_id"],
    ),
    _tool(
        "inspect_table",
        "读取表格的列名、类型、行数与前 10 行，用于在运行操作前确认数据结构。",
        {"table_path": _STRING, "table_csv": _STRING},
    ),
    _tool("studyui_info", "返回 StudyUI MCP 服务的运行时路径与目录统计。"),
]

_HANDLERS = {
    "list_science_operations": _list_science_operations,
    "describe_science_operation": _describe_science_operation,
    "run_science_operation": _run_science_operation,
    "list_workflows": _list_workflows,
    "get_workflow": _get_workflow,
    "copy_workflow": _copy_workflow,
    "run_workflow": _run_workflow,
    "workflow_task_status": _task_status,
    "cancel_workflow_task": _cancel_task,
    "list_material_tasks": _list_material_tasks,
    "get_material_task": _get_material_task,
    "list_demo_datasets": _list_demo_datasets,
    "load_demo_dataset": _load_demo_dataset,
    "inspect_table": _inspect_table,
    "studyui_info": _studyui_info,
}

server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


async def _run_handler(handler, arguments: dict):
    """Run a blocking handler off the event loop without anyio's thread limiter.

    ``anyio.to_thread.run_sync`` deadlocks in this server once fd 1 has been
    redirected to stderr, so use an owned pool and poll the future instead.
    """
    future = _EXECUTOR.submit(handler, arguments)
    while not future.done():
        await anyio.sleep(0.05)
    return future.result()


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return _result({"error": f"unknown tool: {name}"}, ok=False)
    try:
        payload = await _run_handler(handler, arguments or {})
        return _result(payload)
    except Exception as exc:  # reported to the model, never crashes the server
        return _result({"error": f"{type(exc).__name__}: {exc}"}, ok=False)


@asynccontextmanager
async def clean_stdio():
    """Keep the JSON-RPC transport on a private fd; send business output to stderr."""
    transport_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    real = TextIOWrapper(
        os.fdopen(transport_fd, "wb", buffering=0),
        encoding="utf-8",
        write_through=True,
    )
    async with stdio_server(stdout=anyio.wrap_file(real)) as streams:
        yield streams


async def serve() -> None:
    async with clean_stdio() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def selftest() -> int:
    report = {
        "server": SERVER_NAME,
        "tool_count": len(TOOLS),
        "tools": [tool.name for tool in TOOLS],
    }
    report["operation_count"] = _list_science_operations({})["count"]
    report["workflow_count"] = _list_workflows({})["count"]
    report["material_task_count"] = _list_material_tasks({})["count"]
    report["demo_dataset_count"] = _list_demo_datasets({})["count"]
    run = _run_science_operation(
        {
            "operation": "stats.distribution",
            "config": {"column": "value", "bins": 4, "profile": "preview"},
            "table_csv": "value\n1\n2\n3\n4\n5\n6\n7\n8\n",
        }
    )
    report["selftest_operation"] = run["operation"]
    report["selftest_ok"] = bool(run.get("result"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["selftest_ok"] else 1


def _preload() -> list[str]:
    """Import the science and workflow stacks before the event loop starts."""
    import importlib

    failures: list[str] = []
    targets = ["numpy", "pandas", "materials_quality.agent.workflow_files"]
    try:
        from materials_quality.science import catalog

        targets.extend(sorted({item["function"].split(":")[0] for item in catalog.entries()}))
    except Exception as exc:
        failures.append(f"catalog: {type(exc).__name__}: {exc}")
    targets.append("materials_quality.agent.file_workflow_client")
    for name in dict.fromkeys(targets):
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studyui-mcp", description="StudyUI stdio MCP server")
    parser.add_argument("--selftest", action="store_true", help="exercise the tool surface and exit")
    args = parser.parse_args(argv)
    for failure in _preload():
        print(f"studyui-mcp preload skipped: {failure}", file=sys.stderr, flush=True)
    if args.selftest:
        return selftest()
    anyio.run(serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

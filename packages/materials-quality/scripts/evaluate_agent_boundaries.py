"""Evaluate deterministic StudyUI agent boundaries without a network or model account.

Run from the package directory with PYTHONPATH=src, or from an installed
environment. The JSON report goes to stdout. Exit status is 1 on a mismatch.
"""

import io
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

from materials_quality import __version__
from materials_quality.agent.data_inspection import authorized_file, inspect_file
from materials_quality.agent.model import ChatModel
from materials_quality.agent.tasks import TaskManager, checkpoint
from materials_quality.agent.workflow import apply_actions


def standards_without_measurements(root):
    file = root / "battery_cycle.csv"
    file.write_text("voltage,cycle\n", encoding="utf-8")
    audit = inspect_file(file)["standards_and_compliance"]
    return {
        "compliance": audit["compliance_status"],
        "compliance_passed": audit["compliance_passed"],
        "voltage_window": next(
            check["status"] for check in audit["checks"] if check["id"] == "voltage_window"
        ),
    }


def descending_axis(root):
    file = root / "xrd.csv"
    file.write_text("2theta,intensity\n40,80\n30,90\n20,100\n", encoding="utf-8")
    audit = inspect_file(file)["standards_and_compliance"]
    order = next(check for check in audit["checks"] if check["id"] == "first_column_increasing")
    return {
        "status": order["status"],
        "strictly_decreasing": order["evidence"]["strictly_decreasing"],
        "checked_rows": order["evidence"]["checked_rows"],
        "scope": order["scope"],
    }


def same_basename(root):
    public = root / "public" / "sample.csv"
    private = root / "private" / "sample.csv"
    for path in (public, private):
        path.parent.mkdir()
        path.write_text("x,y\n1,2\n", encoding="utf-8")
    text = f'请分析 "{public}"'
    approved = authorized_file(str(public), text) == public
    try:
        authorized_file(str(private), text)
    except PermissionError:
        return {"named_file_approved": approved, "other_file_approved": False}
    return {"named_file_approved": approved, "other_file_approved": True}


def missing_port(_root):
    source = {"id": "src", "data": {"node": {"outputs": [{"name": "table", "types": ["DataFrame"]}]}}}
    target = {"id": "dst", "data": {"node": {"template": {"input_table": {"input_types": ["DataFrame"]}}}}}
    flow = {"data": {"nodes": [source, target], "edges": []}}
    action = {"op": "connect", "source": "src", "target": "dst", "output": "features", "input": "input_table"}
    try:
        candidate, _ = apply_actions(flow, [action], {})
    except ValueError:
        return {"accepted": False, "edge_count": len(flow["data"]["edges"])}
    return {"accepted": True, "edge_count": len(candidate["data"]["edges"])}


def truncated_stream(_root):
    # A complete-looking tool delta without the stream's finish event.
    event = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "run_workflow", "arguments": '{"flow_id":"demo"}'},
                        }
                    ]
                },
            }
        ],
    }
    tool_delta = b"data: " + json.dumps(event).encode() + b"\n\n"
    finish = b'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\ndata: [DONE]\n\n'
    model = ChatModel(base_url="http://127.0.0.1:1", model="offline-fixture", api_key="")

    def complete(body):
        response = io.BytesIO(body)
        response.headers = {"Content-Type": "text/event-stream"}
        opener = Mock()
        opener.open.return_value = response
        with patch("materials_quality.agent.model.build_opener", return_value=opener):
            return model.complete([{"role": "user", "content": "run demo"}], [], on_chunk=lambda *_: None)

    control = complete(tool_delta + finish)
    actual = {"complete_tool_calls": len(control.get("tool_calls", []))}
    try:
        message = complete(tool_delta)
    except ValueError:
        return {**actual, "accepted": False, "tool_calls_returned": 0}
    return {**actual, "accepted": True, "tool_calls_returned": len(message.get("tool_calls", []))}


def cancel_between_operations(root):
    manager = TaskManager(root / "tasks.sqlite3")
    entered, release = threading.Event(), threading.Event()
    operations = []

    def run(_progress):
        operations.append("first")
        entered.set()
        if not release.wait(5):
            raise TimeoutError("fixture could not release first operation")
        checkpoint()
        operations.append("second")
        return {}

    task = manager.submit("offline-session", "fixture", run)
    try:
        if not entered.wait(5):
            raise TimeoutError("fixture did not enter first operation")
        while_blocked = manager.cancel(task["id"])["status"]
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = manager.get(task["id"])
        if task["terminal"]:
            return {"while_blocked": while_blocked, "final": task["status"], "operations": operations}
        time.sleep(0.01)
    raise TimeoutError("fixture did not reach terminal status")


# Expectations are frozen from the behavior contract, independently of the
# values computed by the code under evaluation.
CASES = (
    (
        "standards-no-voltage",
        "Battery-labeled CSV with headers and zero measurements",
        {"compliance": "not_verified", "compliance_passed": None, "voltage_window": "not_verified"},
        standards_without_measurements,
    ),
    (
        "descending-first-column",
        "Three 2theta values in order 40, 30, 20",
        {
            "status": "failed",
            "strictly_decreasing": True,
            "checked_rows": 3,
            "scope": {"start_row": 2, "end_row": 4, "column": 1},
        },
        descending_axis,
    ),
    (
        "file-identity",
        "User names public/sample.csv; inspect it and private/sample.csv",
        {"named_file_approved": True, "other_file_approved": False},
        same_basename,
    ),
    (
        "unknown-port",
        "Connect features when the source exposes only table",
        {"accepted": False, "edge_count": 0},
        missing_port,
    ),
    (
        "sse-without-finish",
        "In-memory stream ends after tool delta; no finish event",
        {"accepted": False, "tool_calls_returned": 0, "complete_tool_calls": 1},
        truncated_stream,
    ),
    (
        "cancel-at-boundary",
        "Cancel while first operation is blocked; then release it",
        {"while_blocked": "cancelling", "final": "cancelled", "operations": ["first"]},
        cancel_between_operations,
    ),
)


def main():
    results = []
    with tempfile.TemporaryDirectory(prefix="studyui-eval-") as temp:
        for case_id, description, expected, run in CASES:
            root = Path(temp).resolve() / case_id
            root.mkdir()
            try:
                actual = run(root)
            except Exception as exc:
                actual = {"error": type(exc).__name__, "detail": str(exc)}
            results.append(
                {
                    "id": case_id,
                    "input": description,
                    "expect": expected,
                    "actual": actual,
                    "pass": expected == actual,
                }
            )

    passed = sum(case["pass"] for case in results)
    print(
        json.dumps(
            {
                "evaluation_version": "1.0.0",
                "studyui_version": __version__,
                "scope": "Offline deterministic fixtures only (online LLM capability excluded).",
                "passed": passed,
                "total": len(results),
                "cases": results,
            },
            indent=2,
        )
    )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

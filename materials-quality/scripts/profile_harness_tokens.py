"""Profile StudyUI's first-request input composition (no model calls)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import tiktoken

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "materials-quality/src"))

from materials_quality.agent.file_workflow_client import FileWorkflowClient  # noqa: E402
from materials_quality.agent.harness import StudyUIAgent  # noqa: E402
from materials_quality.agent.store import SessionStore  # noqa: E402

ENC = tiktoken.get_encoding("cl100k_base")
FIXTURES = REPO / "materials-quality/testfixtures/harness_bench/fixtures"
PROMPT = (
    "You are analyzing a uniaxial tensile test. The CSV file is {file} with columns "
    "strain_fraction (engineering strain as a fraction) and stress_MPa (engineering stress in MPa). "
    "Compute Young's modulus in GPa by a linear fit over the elastic window 0.0005 <= "
    "strain_fraction <= 0.0015, and report the maximum stress in the file as the ultimate tensile "
    "strength in MPa. Use 1 GPa = 1000 MPa. Report modulus_GPa and uts_MPa to 3 significant figures. "
    "End your final response with one JSON object: {\"modulus_GPa\": <number>, \"uts_MPa\": <number>}. "
    "Do not use null."
)


def tokens(text: str) -> int:
    return len(ENC.encode(text))


class RecordingModel:
    model = "recording"
    max_output_tokens = 16384

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def complete(self, messages, tools, *, max_tokens=None, on_chunk=None):
        self.requests.append(
            {
                "messages": [
                    {"role": message.get("role"), "content": message.get("content", "")}
                    for message in messages
                ],
                "tools": tools,
            }
        )
        return {
            "content": '{"modulus_GPa": 200.0, "uts_MPa": 500.0}',
            "tool_calls": [],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 10,
                "total_tokens": 10,
            },
            "reasoning_content": "",
        }


def classify(message: dict) -> str:
    content = str(message.get("content") or "")
    if message.get("role") != "system":
        return f"history:{message.get('role')}"
    if content.startswith(("【Harness 科研 Skill 预检已完成", "【Skill 预检】")):
        return "skill_context"
    if content.startswith(("【本项目本地文件夹授权】", "【授权目录】")):
        return "folder_authorization"
    if content.startswith("【当前会话数据结构检查记录"):
        return "dataset_schema_board"
    if content.startswith("【当前科研角色子图"):
        return "role_note"
    if content.startswith("以下是本会话较早"):
        return "earlier_context"
    return "system_prompt"


def skill_breakdown(text: str) -> list[dict]:
    rows = []
    current = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current is not None:
                body = "\n".join(buffer)
                rows.append({"heading": current, "chars": len(body), "tokens": tokens(body)})
            current = line[4:]
            buffer = [line]
        elif current is not None:
            buffer.append(line)
    if current is not None:
        body = "\n".join(buffer)
        rows.append({"heading": current, "chars": len(body), "tokens": tokens(body)})
    return rows


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="studyui-profile-"))
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "workflows").mkdir()
    for source in (FIXTURES / "mechanics").iterdir():
        (workspace / source.name).write_bytes(source.read_bytes())
    runtime = root / "runtime"
    runtime.mkdir()
    catalog = {
        "projects": [
            {
                "id": "bench",
                "name": "Bench",
                "workspace_id": "ws",
                "local_directories": [str(workspace)],
            }
        ],
        "workspaces": [{"id": "ws", "name": "bench", "path": str(workspace)}],
        "variables": [],
    }
    (runtime / "workspace.json").write_text(json.dumps(catalog), encoding="utf-8")
    store = SessionStore(
        runtime / "agent.sqlite3",
        workspace_file=runtime / "workspace.json",
        workflow_root=workspace / "workflows",
    )
    components = REPO / "materials-quality/components"
    model = RecordingModel()
    agent = StudyUIAgent(
        store,
        canvas=FileWorkflowClient(workspace / "workflows", components),
        model=model,
    )
    agent.permissions.set_preset("bench", "project_collaboration")
    session_id = agent.new_session("profile", project_id="bench")
    prompt = PROMPT.replace("{file}", str(workspace / "tensile.csv"))
    agent.run_turn(session_id, prompt)

    request = model.requests[0]
    components_map: dict[str, dict] = {}
    for message in request["messages"]:
        kind = classify(message)
        content = str(message.get("content") or "")
        row = components_map.setdefault(kind, {"messages": 0, "chars": 0, "tokens": 0})
        row["messages"] += 1
        row["chars"] += len(content)
        row["tokens"] += tokens(content)
    tools_json = json.dumps(request["tools"], ensure_ascii=False)
    tool_rows = []
    for tool in request["tools"]:
        text = json.dumps(tool, ensure_ascii=False)
        tool_rows.append(
            {"name": tool.get("function", {}).get("name"), "chars": len(text), "tokens": tokens(text)}
        )
    skill_text = next(
        (m["content"] for m in request["messages"] if classify(m) == "skill_context"), ""
    )
    result = {
        "first_request": {
            "messages_chars": sum(len(str(m.get("content") or "")) for m in request["messages"]),
            "messages_tokens": sum(tokens(str(m.get("content") or "")) for m in request["messages"]),
            "tools_chars": len(tools_json),
            "tools_tokens": tokens(tools_json),
            "total_chars": sum(
                len(str(m.get("content") or "")) for m in request["messages"]
            )
            + len(tools_json),
            "total_tokens_estimate": sum(tokens(str(m.get("content") or "")) for m in request["messages"])
            + tokens(tools_json),
        },
        "components": components_map,
        "tool_schemas": sorted(tool_rows, key=lambda row: -row["tokens"]),
        "skills": skill_breakdown(skill_text),
        "final_run_mean_input_tokens": 36090,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    (REPO / "materials-quality/artifacts/harness-bench/token-profile.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()

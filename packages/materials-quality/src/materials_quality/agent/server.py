"""StudyUI's local research-agent application and embedded research canvas."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import mimetypes
import os
import uuid
from email.message import Message
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

if __package__ is None or __package__ == "":
    import sys

    _pkg_dir = Path(__file__).resolve().parent
    _src_dir = _pkg_dir.parents[1]
    if str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))
    __package__ = "materials_quality.agent"

from materials_quality.demos.catalog import get_dataset, list_datasets, read_demo_bytes

from .demo_reference import create_reference_workflow
from .file_workflow_client import FileWorkflowClient
from .harness import StudyUIAgent
from .task_api import task_router
from .tasks import SessionBusy
from .uploads import save_code_draft, save_upload

# Kept as a compatibility export; the packaged catalog is the single source of truth.
DEMO_DATASETS = list_datasets()

PAGE = (Path(__file__).parent / "ui" / "index.html").read_text(encoding="utf-8")


def make_handler(harness, canvas_path, task_manager):
    class Handler(BaseHTTPRequestHandler):
        server_version = "StudyUI/0.1"

        def log_message(self, fmt, *args):
            print("[agent] " + fmt % args, flush=True)

        def _send(self, status, value, content_type="application/json; charset=utf-8"):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _local_host(self):
            host = self.headers.get("Host", "")
            parsed = urlsplit("http://" + host)
            return parsed.hostname in {"localhost", "127.0.0.1", "::1"}

        def _same_origin_or_non_browser(self):
            origin = self.headers.get("Origin")
            if not origin:
                return True
            parsed_origin = urlsplit(origin)
            host = urlsplit("http://" + self.headers.get("Host", ""))
            return (
                parsed_origin.scheme == "http"
                and parsed_origin.hostname == host.hostname
                and parsed_origin.port == host.port
            )

        def _body(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 64_000:
                raise ValueError("Request body must be between 1 and 64000 bytes")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object")
            return data

        def _error(self, exc, status=400):
            self._send(status, {"error": str(exc)[:1000]})

        def do_GET(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            path = urlsplit(self.path).path
            if path == "/":
                page = PAGE.replace("__CANVAS_BASE_PATH__", html.escape(canvas_path.rstrip("/"), quote=True))
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/health":
                profile = harness.model_profiles.active()
                m_name = (
                    getattr(harness.model, "model", None)
                    if getattr(harness, "_custom_model", False)
                    else (
                        profile.get("name")
                        or profile.get("model")
                        or getattr(harness.model, "model", "")
                        or "AI 模型"
                    )
                )
                if not m_name or m_name == "deepseek-flash":
                    m_name = profile.get("name") or profile.get("model") or "AI 模型"
                return self._send(
                    200,
                    {
                        "status": "ok",
                        "service": "StudyUI",
                        "model_configured": bool(profile.get("configured")),
                        "model_name": m_name,
                        "canvas_url": canvas_path,
                        "workflow_storage": "json"
                        if isinstance(harness.langflow, FileWorkflowClient)
                        else "database",
                    },
                )
            if path == "/api/settings/model":
                return self._send(200, harness.model_profiles.public())
            if path == "/api/permissions":
                project_id = parse_qs(urlsplit(self.path).query).get("project_id", [None])[0]
                preset = harness.permissions.get_preset(project_id)
                from .permissions import PRESETS

                return self._send(200, {"project_id": project_id, "preset": preset, "presets": PRESETS})
            if path == "/api/skills":
                return self._send(200, {"skills": harness.skills.list()})
            if path == "/api/demo-datasets":
                return self._send(200, {"datasets": DEMO_DATASETS})
            if path == "/api/sessions":
                return self._send(200, harness.store.list_sessions())
            if path == "/api/projects":
                return self._send(200, harness.store.list_projects())
            if path.startswith("/api/sessions/"):
                parts = path.strip("/").split("/")
                if len(parts) == 5 and parts[3] == "artifacts":
                    session_id, artifact_id = unquote(parts[2]), unquote(parts[4])
                    artifact = harness.store.get_artifact(artifact_id, session_id)
                    if artifact is None:
                        return self._error("Artifact not found", 404)
                    artifact_root = harness.artifact_root.resolve()
                    stored_path = Path(artifact["path"])
                    if stored_path.is_symlink():
                        return self._error("Artifact path is invalid", 404)
                    file_path = stored_path.resolve()
                    if not file_path.is_relative_to(artifact_root) or not file_path.is_file():
                        return self._error("Artifact path is invalid", 404)
                    if (
                        file_path.stat().st_size != artifact["size"]
                        or file_path.stat().st_size > 20 * 1024 * 1024
                    ):
                        return self._error("Artifact changed after it was registered", 409)
                    raw = file_path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
                        return self._error("Artifact checksum mismatch", 409)
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        mimetypes.guess_type(artifact["name"])[0] or "application/octet-stream",
                    )
                    self.send_header(
                        "Content-Disposition",
                        "attachment; filename=studyui-output; filename*=UTF-8''" + quote(artifact["name"]),
                    )
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if len(parts) != 3:
                    return self._error("Not found", 404)
                session_id = unquote(parts[2])
                if not harness.store.has_session(session_id):
                    return self._error("Conversation does not exist", 404)
                return self._send(
                    200,
                    {
                        "messages": [
                            {
                                "role": message.get("role"),
                                "content": message.get("content"),
                                "reasoning_content": message.get("reasoning_content"),
                                "tool_steps": message.get("tool_steps"),
                                "model": message.get("model"),
                            }
                            for message in harness.store.messages(session_id, limit=200)
                            if message.get("role") in {"user", "assistant"} and not message.get("tool_calls")
                        ],
                        "pending_proposals": harness.store.pending_proposals(session_id),
                        "pending_approvals": harness.store.pending_approvals(session_id),
                        "artifacts": harness.store.latest_artifacts(session_id),
                        "skill_selections": [
                            event
                            for event in harness.store.events(session_id, limit=500)
                            if event.get("kind") == "skill_selection"
                        ],
                    },
                )
            return self._error("Not found", 404)

        def do_POST(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            if not self._same_origin_or_non_browser():
                return self._error("Cross-origin requests are not accepted", 403)
            path = urlsplit(self.path).path
            try:
                if path == "/api/skills/import":
                    return self._error(
                        "Direct Skill installation is disabled; submit a reviewed package for approval", 403
                    )
                if path == "/api/skills/preview":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2_000_000:
                        return self._error("Skill upload must be between 1 byte and 2 MB", 413)
                    raw = self.rfile.read(length)
                    filename = unquote(self.headers.get("X-Filename", "skill.zip"))
                    session_id = unquote(self.headers.get("X-StudyUI-Session", ""))
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before requesting Skill installation")
                    item = harness.skills.stage_zip(filename, raw)
                    action = item["action"]
                    is_update = action == "skill.update"
                    summary = {
                        "title": f"{'更新' if is_update else '安装'} Skill：{item['title']}",
                        "impact": f"导入版本 SHA-256 {item['sha256']}；Skill 默认停用。"
                        + (f"将替换当前版本 {item['current_sha256']}，并保留历史版本。" if is_update else ""),
                        "scripts": item["scripts"],
                        "reason": "用户上传的 Skill 包已完成路径、大小与清单校验，等待一次性审批。",
                    }
                    try:
                        result = harness.request_approval(
                            session_id,
                            action,
                            summary["reason"],
                            {
                                "kind": "skill.import",
                                "stage_id": item["stage_id"],
                                "filename": filename,
                                "name": item["name"],
                                "sha256": item["sha256"],
                                "replace": is_update,
                                "current_sha256": item["current_sha256"],
                                "summary": summary,
                            },
                            project_id=harness.store.session_context(session_id).get("project_id"),
                        )
                    except Exception:
                        harness.skills.discard_staged(item["stage_id"])
                        raise
                    return self._send(202, {**result, **summary})
                if path == "/api/upload":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 50_000_000:
                        return self._error("上传文件大小必须在 1 字节至 50MB 之间", 413)
                    raw = self.rfile.read(length)
                    raw_filename = unquote(self.headers.get("X-Filename", "uploaded_file.csv"))
                    filename = Path(raw_filename).name or "uploaded_file.csv"
                    session_id = unquote(self.headers.get("X-StudyUI-Session", "")).strip()
                    try:
                        uploaded = save_upload(harness, session_id, filename, raw)
                    except PermissionError as exc:
                        return self._error(exc, 403)
                    saved_path = uploaded["path"]
                    prompt = (
                        f'请检查并分析已上传的材料数据文件 "{saved_path}"，'
                        f"识别其数据结构、关键特征与异常值，并给出适用的数据处理工作流。"
                    )
                    return self._send(
                        200,
                        {
                            "status": "ok",
                            "filename": filename,
                            "path": saved_path,
                            "size": len(raw),
                            "sha256": uploaded["sha256"],
                            "prompt": prompt,
                        },
                    )
                data = self._body()
                if path in {"/api/demo-datasets/load", "/api/demo-datasets/reference"}:
                    if set(data) != {"id", "session_id"}:
                        return self._error("只接受演示数据 ID 与研究会话 ID。")
                    dataset_id, session_id = data["id"], data["session_id"]
                    if not isinstance(dataset_id, str) or not isinstance(session_id, str):
                        return self._error("演示数据与研究会话标识无效。")
                    try:
                        item = get_dataset(dataset_id)
                    except ValueError:
                        return self._error("未找到指定的演示数据集", 404)
                    try:
                        if str(uuid.UUID(session_id)) != session_id:
                            raise ValueError
                    except ValueError:
                        return self._error("请先打开有效的研究会话。")
                    if not harness.store.has_session(session_id):
                        return self._error("研究会话不存在。", 404)
                    try:
                        if path.endswith("/reference"):
                            result = task_manager.run_legacy(
                                session_id, create_reference_workflow, harness, dataset_id, session_id
                            )
                            return self._send(201, result)
                        uploaded = task_manager.run_legacy(
                            session_id,
                            save_upload,
                            harness,
                            session_id,
                            item["filename"],
                            read_demo_bytes(dataset_id),
                        )
                    except SessionBusy as exc:
                        return self._error(exc, 409)
                    except PermissionError as exc:
                        return self._error(exc, 403)
                    except LookupError as exc:
                        return self._error(exc, 404)
                    saved_path = uploaded["path"]
                    return self._send(
                        200,
                        {
                            "status": "ok",
                            "id": item["id"],
                            "title": item["title"],
                            "filename": item["filename"],
                            "path": saved_path,
                            "sha256": uploaded["sha256"],
                            "prompt": item["prompt"].format(path=f'"{saved_path}"'),
                        },
                    )
                if path == "/api/canvas/insert-node":
                    code = data.get("code")
                    name = data.get("name", "CustomNode").strip() or "CustomNode"
                    session_id = data.get("session_id", "").strip()
                    if not isinstance(code, str) or not code.strip():
                        return self._error("代码内容不能为空")
                    try:
                        draft = save_code_draft(harness, session_id, name, code)
                    except PermissionError as exc:
                        return self._error(exc, 403)
                    return self._send(202, draft)
                if path == "/api/projects":
                    project_id = harness.store.create_project(
                        data.get("title", ""), data.get("description", "")
                    )
                    return self._send(201, {"id": project_id})
                if path == "/api/sessions":
                    session_id = harness.new_session(data.get("title", "科研任务"), data.get("project_id"))
                    return self._send(201, {"id": session_id})
                if path.startswith("/api/sessions/") and path.endswith("/messages"):
                    session_id = unquote(path.split("/")[-2])
                    try:
                        result = task_manager.run_legacy(
                            session_id, harness.run_turn, session_id, data.get("message")
                        )
                    except SessionBusy as exc:
                        return self._error(exc, 409)
                    return self._send(200, result)
                if path.startswith("/api/proposals/"):
                    parts = path.strip("/").split("/")
                    if len(parts) != 4 or parts[1] != "proposals" or parts[3] not in {"approve", "reject"}:
                        return self._error("Not found", 404)
                    proposal_id, decision = unquote(parts[2]), parts[3]
                    result = (
                        harness.approve_proposal(proposal_id)
                        if decision == "approve"
                        else harness.reject_proposal(proposal_id)
                    )
                    return self._send(200, result)
                if path == "/api/settings/model":
                    result = harness.model_profiles.save(
                        name=data.get("name", "DeepSeek"),
                        base_url=data.get("base_url", "https://api.deepseek.com"),
                        model=data.get("model", "deepseek-flash"),
                        api_key=data.get("api_key"),
                        profile_id=data.get("profile_id"),
                        create_new=bool(data.get("create_new")),
                        reasoning_effort=data.get("reasoning_effort"),
                    )
                    harness._refresh_model()
                    return self._send(
                        200,
                        {
                            key: value
                            for key, value in result.items()
                            if key not in {"credential_ref", "api_key"}
                        },
                    )
                if path == "/api/settings/model/activate":
                    result = harness.model_profiles.activate(data.get("profile_id", ""))
                    harness._refresh_model()
                    return self._send(200, result)
                if path == "/api/settings/model/test":
                    harness._refresh_model()
                    response = harness.model.complete(
                        [
                            {"role": "system", "content": "Return exactly the word READY."},
                            {"role": "user", "content": "Connection test. Reply READY."},
                        ],
                        [],
                        max_tokens=16,
                    )
                    return self._send(
                        200, {"ok": True, "model": harness.model.model, "response_received": bool(response)}
                    )
                if path == "/api/permissions":
                    project_id, preset = data.get("project_id"), data.get("preset", "")
                    from .permissions import PRESETS

                    if preset not in PRESETS:
                        return self._error("Unknown permission preset")
                    old = harness.permissions.get_preset(project_id)
                    capability = {
                        "read_only": {"read"},
                        "per_action": {"read", "ask"},
                        "project_collaboration": {"read", "ask", "project_write"},
                        "skill_sandbox": {"read", "ask", "project_write", "skill_script"},
                    }
                    session_id = data.get("session_id", "")
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before changing project permissions")
                    context = harness.store.session_context(session_id) or {}
                    if project_id and context.get("project_id") != project_id:
                        return self._error(
                            "Permission change session must belong to the selected project", 403
                        )
                    if not capability[preset].issubset(capability[old]):
                        summary = {
                            "title": "提升项目 Agent 权限",
                            "impact": (
                                f"权限档位将从「{PRESETS[old]['label']}」改为「{PRESETS[preset]['label']}」。"
                            ),
                            "reason": PRESETS[preset]["description"],
                        }
                        queued = harness.request_approval(
                            session_id,
                            "permission.change",
                            summary["reason"],
                            {"kind": "permission.change", "preset": preset, "summary": summary},
                            project_id=project_id,
                        )
                        return self._send(202, {**queued, **summary})
                    result = harness.permissions.set_preset(project_id, preset)
                    harness.store.append_event(
                        session_id, "permission_changed", {"project_id": project_id, "preset": preset}
                    )
                    return self._send(200, result)
                if path.startswith("/api/skills/") and path.endswith("/trust"):
                    name = unquote(path.strip("/").split("/")[-2])
                    session_id = data.get("session_id", "")
                    item = harness.skills.get(name)
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before reviewing a Skill")
                    if item["sha256"] != data.get("sha256", ""):
                        return self._error("Skill changed since it was displayed; reload settings")
                    summary = {
                        "title": f"审核 Skill 版本：{name}",
                        "impact": f"信任 SHA-256 {item['sha256']}；此版本随后可在离线沙箱中调用。",
                        "scripts": item["scripts"],
                        "reason": "确认审核此确切版本及其所有脚本。",
                    }
                    queued = harness.request_approval(
                        session_id,
                        "skill.trust",
                        summary["reason"],
                        {"kind": "skill.trust", "name": name, "sha256": item["sha256"], "summary": summary},
                        project_id=harness.store.session_context(session_id).get("project_id"),
                    )
                    return self._send(202, {**queued, **summary})
                if path.startswith("/api/skills/") and path.endswith("/remove"):
                    name = unquote(path.strip("/").split("/")[-2])
                    session_id = data.get("session_id", "")
                    item = harness.skills.get(name)
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before requesting Skill removal")
                    summary = {
                        "title": f"移除 Skill：{name}",
                        "impact": f"从活动注册表中移除当前版本 {item['sha256']}。",
                        "reason": "Skill 移除需要一次性审批。",
                    }
                    queued = harness.request_approval(
                        session_id,
                        "skill.remove",
                        summary["reason"],
                        {"kind": "skill.remove", "name": name, "sha256": item["sha256"], "summary": summary},
                        project_id=harness.store.session_context(session_id).get("project_id"),
                    )
                    return self._send(202, {**queued, **summary})
                if path.startswith("/api/approvals/"):
                    parts = path.strip("/").split("/")
                    if len(parts) != 4 or parts[3] not in {"approve", "reject", "cancel"}:
                        return self._error("Not found", 404)
                    decision = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[parts[3]]
                    approval_id = unquote(parts[2])
                    approval = harness.store.get_approval(approval_id) if decision == "approved" else None
                    if approval and approval["status"] == "pending":
                        try:
                            result = task_manager.run_legacy(
                                approval["session_id"], harness.decide_approval, approval_id, decision
                            )
                        except SessionBusy as exc:
                            return self._error(exc, 409)
                    else:
                        result = harness.decide_approval(approval_id, decision)
                    return self._send(200, result)
                return self._error("Not found", 404)
            except Exception as exc:
                self.log_message("request failed: %s", type(exc).__name__)
                return self._error(exc)

        def do_PATCH(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            if not self._same_origin_or_non_browser():
                return self._error("Cross-origin requests are not accepted", 403)
            path = urlsplit(self.path).path
            try:
                data = self._body()
                if path.startswith("/api/skills/"):
                    name = unquote(path.rsplit("/", 1)[-1])
                    result = harness.skills.set_enabled(name, data.get("enabled"))
                    session_id = data.get("session_id", "")
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before changing Skill state")
                    harness.store.append_event(
                        session_id, "skill_enabled", {"name": result["name"], "enabled": result["enabled"]}
                    )
                    return self._send(200, result)
                if path.startswith("/api/projects/"):
                    project_id = unquote(path.rsplit("/", 1)[-1])
                    harness.store.update_project(project_id, data.get("title", ""))
                    return self._send(200, {"status": "updated"})
                if path.startswith("/api/sessions/"):
                    session_id = unquote(path.rsplit("/", 1)[-1])
                    update = {
                        "title": data.get("title"),
                        "project_id": data.get("project_id") if "project_id" in data else ...,
                    }
                    if "project_id" in data:
                        try:
                            task_manager.run_legacy(
                                session_id, harness.store.update_session, session_id, **update
                            )
                        except SessionBusy as exc:
                            return self._error(exc, 409)
                    else:
                        harness.store.update_session(session_id, **update)
                    return self._send(200, {"status": "updated"})
                return self._error("Not found", 404)
            except Exception as exc:
                self.log_message("request failed: %s", type(exc).__name__)
                return self._error(exc)

        def do_DELETE(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            if not self._same_origin_or_non_browser():
                return self._error("Cross-origin requests are not accepted", 403)
            path = urlsplit(self.path).path
            if path.startswith("/api/sessions/"):
                try:
                    session_id = unquote(path.rsplit("/", 1)[-1])
                    try:
                        success = task_manager.run_legacy(
                            session_id, harness.store.delete_session, session_id
                        )
                    except SessionBusy as exc:
                        return self._error(exc, 409)
                    if not success:
                        return self._error("Session not found", 404)
                    return self._send(200, {"status": "deleted", "id": session_id})
                except Exception as exc:
                    return self._error(exc)
            if path.startswith("/api/projects/"):
                try:
                    project_id = unquote(path.rsplit("/", 1)[-1])
                    data = self._body()
                    session_id = data.get("session_id", "")
                    context = (
                        harness.store.session_context(session_id)
                        if harness.store.has_session(session_id)
                        else None
                    )
                    if not context or context.get("project_id") != project_id:
                        return self._error(
                            "Project deletion approval must come from a session in that project", 403
                        )
                    summary = {
                        "title": f"删除项目：{project_id}",
                        "impact": "研究会话将保留并移至未归类；项目工作流将移入恢复目录。",
                        "reason": "项目删除是不可逆的项目管理操作，需一次性审批。",
                    }
                    result = harness.request_approval(
                        session_id,
                        "project.delete",
                        summary["reason"],
                        {"kind": "project.delete", "project_id": project_id, "summary": summary},
                        project_id=project_id,
                    )
                    return self._send(202, {**result, **summary})
                except Exception as exc:
                    return self._error(exc)
            if path == "/api/settings/model":
                try:
                    data = self._body()
                    result = harness.model_profiles.remove(str(data.get("profile_id", "")))
                    harness._refresh_model()
                    return self._send(200, result)
                except Exception as exc:
                    return self._error(exc)
            if path.startswith("/api/skills/"):
                return self._error("Skill removal requires a one-shot approval", 403)
            return self._error("Not found", 404)

    return Handler


def _dispatch_studyui_handler(handler_type, method, path, headers, body):
    """Run the existing StudyUI route handler behind the shared ASGI listener."""
    handler = object.__new__(handler_type)
    handler.command = method
    handler.path = path
    handler.headers = Message()
    for name, value in headers.items():
        handler.headers.add_header(name, value)
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    response = {"status": 500, "headers": {}}

    def send_response(status, message=None):
        response["status"] = int(status)

    def send_header(name, value):
        response["headers"][name] = value

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = lambda: None
    handler.log_message = lambda *args: None
    route = getattr(handler, "do_" + method, None)
    if route is None:
        handler._send(405, {"error": "Method not allowed"})
    else:
        route()
    return response["status"], response["headers"], handler.wfile.getvalue()


def create_app(database, workflows, components, frontend):
    """Serve the StudyUI agent and its workflow canvas through one local listener."""
    from starlette.concurrency import run_in_threadpool

    from .workbench import create_app as create_workbench_app

    project_root = Path(__file__).resolve().parents[5]
    if isinstance(database, (str, Path)):
        db_path = Path(database)
        if not db_path.is_absolute() and not db_path.exists():
            candidate = project_root / db_path
            if candidate.parent.exists() or candidate.exists():
                database = str(candidate)
    workflow_client = FileWorkflowClient(
        workflows or project_root / "workflows",
        components or project_root / ".demo-runtime" / "components",
    )
    harness = StudyUIAgent(database, langflow=workflow_client)

    router, manager = task_router(harness)

    def run_canvas_workflow(flow_id, payload):
        session_id = payload.get("studyui_session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("运行会话标识无效。")
        try:
            if session_id:
                result = manager.run_legacy(
                    session_id, harness.run_canvas_workflow, flow_id, session_id=session_id
                )
            else:
                result = harness.run_canvas_workflow(flow_id)
        except SessionBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        native_result = result.get("workflow_result")
        if not isinstance(native_result, dict):
            native_result = {"flow_id": flow_id, "outputs": []}
        native_result["studyui_run"] = {
            "session_id": result["session_id"],
            "flow_id": flow_id,
            "status": "completed" if result.get("workflow_result") is not None else "agent_report",
            "message": result.get("message", ""),
            "artifacts": result.get("artifacts", []),
            "pending_approvals": result.get("pending_approvals", []),
        }
        return native_result

    handler_type = make_handler(harness, "/canvas", manager)
    app = FastAPI(title="StudyUI")
    from fastapi.staticfiles import StaticFiles

    assets = Path(__file__).parent / "ui" / "assets"
    if assets.is_dir():
        app.mount("/ui-assets", StaticFiles(directory=assets), name="studyui-assets")
    app.state.harness = harness
    app.state.tasks = manager
    app.include_router(router)
    app.mount(
        "/canvas",
        create_workbench_app(
            Path(workflows or project_root / "workflows"),
            Path(components or project_root / ".demo-runtime" / "components"),
            Path(frontend or project_root / ".demo-runtime" / "workbench-ui"),
            workflow_run_handler=run_canvas_workflow,
        ),
    )

    @app.post("/api/sessions/{session_id}/messages")
    async def post_session_message_route(session_id: str, request: Request):
        from urllib.parse import unquote

        host = urlsplit("http://" + request.headers.get("host", ""))
        origin = request.headers.get("origin")
        source = urlsplit(origin) if origin else None
        if host.hostname not in {"localhost", "127.0.0.1", "::1"} or (
            source
            and (source.scheme != "http" or source.hostname != host.hostname or source.port != host.port)
        ):
            return Response(status_code=403, content="Cross-origin requests are not accepted")
        clean_id = unquote(session_id)
        if not harness.store.has_session(clean_id):
            return Response(
                content=json.dumps({"error": "Conversation does not exist"}, ensure_ascii=False).encode(),
                status_code=404,
                media_type="application/json",
            )
        try:
            data = await request.json()
        except Exception:
            return Response(
                content=json.dumps({"error": "Malformed JSON"}, ensure_ascii=False).encode(),
                status_code=400,
                media_type="application/json",
            )

        user_msg = data.get("message")
        accept = request.headers.get("accept", "")
        stream_requested = "text/event-stream" in accept or request.query_params.get("stream") == "true"

        if not stream_requested:
            try:
                res = await run_in_threadpool(
                    manager.run_legacy, clean_id, harness.run_turn, clean_id, user_msg
                )
                return Response(
                    content=json.dumps(res, ensure_ascii=False).encode(),
                    status_code=200,
                    media_type="application/json",
                )
            except Exception as exc:
                return Response(
                    content=json.dumps({"error": str(exc)}, ensure_ascii=False).encode(),
                    status_code=409 if isinstance(exc, SessionBusy) else 400,
                    media_type="application/json",
                )

        from starlette.responses import StreamingResponse

        async def event_generator():
            import asyncio

            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def progress_cb(evt):
                loop.call_soon_threadsafe(queue.put_nowait, evt)

            async def runner():
                try:
                    res = await run_in_threadpool(
                        manager.run_legacy,
                        clean_id,
                        harness.run_turn,
                        clean_id,
                        user_msg,
                        on_progress=progress_cb,
                    )
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "done", "result": res})
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(exc)})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            asyncio.create_task(runner())
            start = json.dumps({"session_id": clean_id}, ensure_ascii=False)
            yield f"event: start\ndata: {start}\n\n".encode("utf-8")

            while True:
                item = await queue.get()
                if item is None:
                    break
                evt_type = item.get("type", "message")
                payload = json.dumps(item, ensure_ascii=False)
                yield f"event: {evt_type}\ndata: {payload}\n\n".encode("utf-8")

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS", "PUT"])
    async def studyui_routes(request: Request, path: str = ""):
        request_path = request.url.path
        if request.url.query:
            request_path += "?" + request.url.query
        status, response_headers, content = await run_in_threadpool(
            _dispatch_studyui_handler,
            handler_type,
            request.method,
            request_path,
            dict(request.headers.items()),
            await request.body(),
        )
        headers = {
            name: value
            for name, value in response_headers.items()
            if name.lower() not in {"content-length", "transfer-encoding"}
        }
        return Response(content=content, status_code=status, headers=headers)

    return app


def serve(
    host="127.0.0.1",
    port=7880,
    database=".demo-runtime/agent.sqlite3",
    workflows=None,
    components=None,
    frontend=None,
):
    import uvicorn

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("StudyUI must bind to loopback")
    app = create_app(database, workflows, components, frontend)
    print(f"StudyUI ready: http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, access_log=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("STUDYUI_PORT", "7880")))
    parser.add_argument(
        "--database", default=os.environ.get("STUDYUI_DATABASE", ".demo-runtime/agent.sqlite3")
    )
    parser.add_argument("--workflows", default=os.environ.get("STUDYUI_WORKFLOWS_DIR"))
    parser.add_argument("--components", default=os.environ.get("STUDYUI_COMPONENTS_DIR"))
    parser.add_argument("--frontend", default=os.environ.get("STUDYUI_FRONTEND_DIR"))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    serve(args.host, args.port, args.database, args.workflows, args.components, args.frontend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

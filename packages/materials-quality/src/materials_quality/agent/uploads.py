"""Session-owned immutable inputs and non-executable code review drafts."""

import hashlib
import re
import uuid
from pathlib import Path


def session_directory(harness, session_id, kind="uploads", *, base=None):
    try:
        canonical = str(uuid.UUID(session_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("请先打开有效的研究会话。") from exc
    if canonical != session_id or not harness.store.has_session(session_id):
        raise ValueError("研究会话不存在。")
    context = harness.store.session_context(session_id)
    if harness.permissions.get_preset(context.get("project_id")) in {"read_only", "per_action"}:
        raise PermissionError("当前权限不允许保存文件；请在设置中选择项目协作。")
    base_root = Path(base or harness.working_directory(session_id)).resolve()
    requested_root = base_root / kind
    root = requested_root.resolve()
    if requested_root.is_symlink() or not root.is_relative_to(base_root):
        raise PermissionError("文件目录越界。")
    directory = root / session_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise PermissionError("文件目录越界。")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_upload(harness, session_id, filename, raw):
    if not 0 < len(raw) <= 50_000_000:
        raise ValueError("上传文件必须在 1 字节至 50 MB 之间。")
    name = Path(str(filename).replace("\\", "/")).name
    if name in {"", ".", ".."} or len(name) > 180 or re.search(r'[\x00-\x1f<>:"|?*]', name):
        raise ValueError("文件名无效。")
    directory = session_directory(harness, session_id)
    file_id = str(uuid.uuid4())
    target = directory / (file_id + "_" + name)
    with target.open("xb") as stream:
        stream.write(raw)
    digest = hashlib.sha256(raw).hexdigest()
    result = {
        "id": file_id,
        "filename": name,
        "path": str(target.resolve()),
        "size": len(raw),
        "sha256": digest,
    }
    harness.store.append_event(session_id, "file_uploaded", result)
    return result


def save_code_draft(harness, session_id, name, code):
    if not isinstance(code, str) or not code.strip() or len(code.encode("utf-8")) > 50_000:
        raise ValueError("代码草稿必须在 1 字节至 50 KB 之间。")
    artifact_kind = harness.artifact_root.resolve().relative_to(harness.project_root.resolve())
    directory = session_directory(harness, session_id, artifact_kind, base=harness.project_root)
    draft_id = str(uuid.uuid4())
    target = directory / (draft_id + ".py.txt")
    raw = code.encode("utf-8")
    with target.open("xb") as stream:
        stream.write(raw)
    name = str(name)[:80]
    digest = hashlib.sha256(raw).hexdigest()
    artifact = harness.store.register_artifact(
        draft_id,
        session_id,
        harness.store.session_context(session_id).get("project_id"),
        name + ".py.txt",
        str(target),
        digest,
        len(raw),
    )
    harness.store.append_event(session_id, "code_draft_saved", {"id": draft_id, "sha256": digest})
    artifact = {key: value for key, value in artifact.items() if key != "path"}
    return {
        "status": "draft",
        "executable": False,
        "component_name": name,
        "file": target.name,
        "artifact": artifact,
        "sha256": digest,
        "message": "已保存为待审核代码草稿，未注册或执行。可下载审核，脚本执行使用已审核 Skill 沙箱。",
    }

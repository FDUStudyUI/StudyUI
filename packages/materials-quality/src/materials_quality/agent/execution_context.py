"""Execution-scoped approvals shared between the Harness and LFX node runtime."""

from contextvars import ContextVar

_external_data_approved = ContextVar("studyui_external_data_approved", default=False)
_subagent_audit = ContextVar("studyui_subagent_audit", default=None)
_upstream_images = ContextVar("studyui_upstream_images", default=None)
_subagent_model = ContextVar("studyui_subagent_model", default=None)


def subagent_model_scope(model):
    return _subagent_model.set(model)


def reset_subagent_model_scope(token):
    _subagent_model.reset(token)


def current_subagent_model():
    return _subagent_model.get()


def begin_upstream_image_scope():
    return _upstream_images.set(set())


def reset_upstream_image_scope(token):
    _upstream_images.reset(token)


def register_upstream_image(path):
    images = _upstream_images.get()
    if images is not None:
        from pathlib import Path

        images.add(str(Path(path).resolve(strict=True)))


def is_authorized_upstream_image(path):
    images = _upstream_images.get()
    if images is None:
        return False
    from pathlib import Path

    try:
        resolved = str(Path(path).resolve(strict=True))
    except OSError:
        return False
    return resolved in images


def external_data_approval(approved):
    return _external_data_approved.set(bool(approved))


def reset_external_data_approval(token):
    _external_data_approved.reset(token)


def require_external_data_approval():
    if not _external_data_approved.get():
        raise PermissionError(
            "此 AI 分析需要将明确连接的上游数据发送给已配置模型；请从 StudyUI Agent 或画布运行入口启动。"
        )


def subagent_audit_context(callback):
    return _subagent_audit.set(callback)


def reset_subagent_audit_context(token):
    _subagent_audit.reset(token)


def record_subagent_event(event, details):
    callback = _subagent_audit.get()
    if callback is not None:
        callback(str(event), dict(details))

"""Execution-scoped approvals shared between the Harness and LFX node runtime."""

from contextvars import ContextVar

_external_data_approved = ContextVar("studyui_external_data_approved", default=False)


def external_data_approval(approved):
    return _external_data_approved.set(bool(approved))


def reset_external_data_approval(token):
    _external_data_approved.reset(token)


def require_external_data_approval():
    if not _external_data_approved.get():
        raise PermissionError(
            "此 AI 分析会将上游数据发送给已配置模型；请在 StudyUI 中申请并批准本次数据传输。"
        )

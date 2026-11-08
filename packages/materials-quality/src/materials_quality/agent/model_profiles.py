"""Model settings with secrets held by the operating-system credential store."""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit

from .permissions import PermissionStore

KEYRING_SERVICE = "StudyUI"
DEEPSEEK_FLASH_CONTEXT = 1_048_576


def _known_context_window(base_url, model):
    host = urlsplit(base_url).hostname
    if host in {"api.deepseek.com", "api.deepseek.cn"} and str(model).casefold() == "deepseek-flash":
        return DEEPSEEK_FLASH_CONTEXT
    return None


class ModelProfiles:
    def __init__(self, settings_path):
        self.settings = PermissionStore(settings_path)

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError:
            raise RuntimeError("模型密钥库不可用；请安装项目依赖后重启 StudyUI。") from None
        return keyring

    def active(self):
        value = self.settings.snapshot()
        profiles = value.get("models", {})
        profile_id = value.get("active_model_id")
        profile = profiles.get(profile_id, {}) if profile_id else {}
        if not profile:
            env = {
                "name": "环境变量模型",
                "provider": "openai-compatible",
                "base_url": os.environ.get("STUDYUI_MODEL_BASE_URL", ""),
                "model": os.environ.get("STUDYUI_MODEL", ""),
                "reasoning_effort": "default",
                "credential_ref": "environment",
                "context_window": _known_context_window(
                    os.environ.get("STUDYUI_MODEL_BASE_URL", ""), os.environ.get("STUDYUI_MODEL", "")
                ),
            }
            has_key = bool(os.environ.get("STUDYUI_MODEL_API_KEY"))
            local = urlsplit(env["base_url"]).hostname in {"localhost", "127.0.0.1", "::1"}
            return {
                **env,
                "configured": bool(env["base_url"] and env["model"] and (has_key or local)),
                "has_api_key": has_key,
            }
        ref = profile.get("credential_ref", "")
        try:
            api_key = self._keyring().get_password(KEYRING_SERVICE, ref) if ref else None
        except Exception:
            api_key = None
        if not api_key:
            api_key = os.environ.get("STUDYUI_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or None
        has_key = bool(api_key)
        local = urlsplit(profile.get("base_url", "")).hostname in {"localhost", "127.0.0.1", "::1"}
        return {
            **profile,
            "reasoning_effort": profile.get("reasoning_effort", "default"),
            "context_window": profile.get("context_window")
            or _known_context_window(profile.get("base_url", ""), profile.get("model", "")),
            "configured": bool(profile.get("base_url") and profile.get("model") and (has_key or local)),
            "has_api_key": has_key,
        }

    def api_key(self):
        profile = self.active()
        if profile.get("credential_ref") == "environment":
            return os.environ.get("STUDYUI_MODEL_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
        ref = profile.get("credential_ref")
        key = ""
        if ref:
            try:
                key = self._keyring().get_password(KEYRING_SERVICE, ref) or ""
            except Exception:
                key = ""
        if not key:
            key = os.environ.get("STUDYUI_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        return key

    def save(
        self,
        *,
        name,
        base_url,
        model,
        api_key=None,
        profile_id=None,
        create_new=False,
        reasoning_effort=None,
        context_window=None,
    ):
        name, base_url, model = (
            str(name).strip()[:80],
            str(base_url).strip().rstrip("/"),
            str(model).strip()[:160],
        )
        parsed = urlsplit(base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not name or not model or not parsed.hostname:
            raise ValueError("请填写模型名称、API 地址和模型名。")
        if (
            (parsed.scheme != "https" and not (parsed.scheme == "http" and local))
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("远程模型必须使用 HTTPS；HTTP 仅允许本机服务。")
        current = self.settings.snapshot()
        profile_id = str(
            uuid.uuid4() if create_new else (profile_id or current.get("active_model_id") or uuid.uuid4())
        )
        old = current.get("models", {}).get(profile_id, {})
        reasoning_effort = (
            old.get("reasoning_effort", "default") if reasoning_effort is None else reasoning_effort
        )
        if reasoning_effort not in {"default", "none", "low", "high", "max"}:
            raise ValueError("思考等级无效。")
        if context_window in (None, ""):
            context_window = _known_context_window(base_url, model)
        else:
            try:
                context_window = int(context_window)
            except (TypeError, ValueError):
                raise ValueError("上下文窗口必须为正整数；留空时只自动识别已知模型。") from None
            if not 2_048 <= context_window <= 100_000_000:
                raise ValueError("上下文窗口必须在 2,048 至 100,000,000 token 之间。")
        credential_ref = old.get("credential_ref") or "studyui-model-" + profile_id
        if api_key:
            self._keyring().set_password(KEYRING_SERVICE, credential_ref, str(api_key))
        profile = {
            "id": profile_id,
            "name": name,
            "provider": "openai-compatible",
            "base_url": base_url,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "context_window": context_window,
            "credential_ref": credential_ref,
        }
        with self.settings.lock:
            value = self.settings._read()
            value.setdefault("models", {})[profile_id] = profile
            value["active_model_id"] = profile_id
            self.settings._write(value)
        return {
            **profile,
            "configured": self.active().get("configured", False),
            "has_api_key": bool(api_key or self.active().get("has_api_key")),
        }

    def list_profiles(self):
        snapshot = self.settings.snapshot()
        active_id = snapshot.get("active_model_id")
        output = []
        for profile_id, profile in snapshot.get("models", {}).items():
            ref = profile.get("credential_ref")
            try:
                has_key = bool(self._keyring().get_password(KEYRING_SERVICE, ref)) if ref else False
            except Exception:
                has_key = False
            base_url = profile.get("base_url", "")
            local = urlsplit(base_url).hostname in {"localhost", "127.0.0.1", "::1"}
            output.append(
                {
                    "id": profile_id,
                    "name": profile.get("name", "模型"),
                    "base_url": base_url,
                    "model": profile.get("model", ""),
                    "reasoning_effort": profile.get("reasoning_effort", "default"),
                    "context_window": profile.get("context_window")
                    or _known_context_window(base_url, profile.get("model", "")),
                    "active": profile_id == active_id,
                    "configured": bool(base_url and profile.get("model") and (has_key or local)),
                    "credential_saved": has_key,
                }
            )
        if not output and (os.environ.get("STUDYUI_MODEL") or os.environ.get("STUDYUI_MODEL_BASE_URL")):
            active = self.active()
            output.append(
                {
                    "id": "environment",
                    "name": active["name"],
                    "base_url": active["base_url"],
                    "model": active["model"],
                    "context_window": active.get("context_window"),
                    "active": True,
                    "configured": active["configured"],
                    "credential_saved": active["has_api_key"],
                }
            )
        return output

    def activate(self, profile_id):
        snapshot = self.settings.snapshot()
        if profile_id not in snapshot.get("models", {}):
            raise ValueError("模型配置不存在")
        with self.settings.lock:
            value = self.settings._read()
            value["active_model_id"] = profile_id
            self.settings._write(value)
        return self.public()

    def remove(self, profile_id):
        with self.settings.lock:
            value = self.settings._read()
            profile = value.get("models", {}).get(profile_id)
            if not profile:
                raise ValueError("模型配置不存在")
            if len(value["models"]) <= 1:
                raise ValueError("至少保留一个模型配置")
            del value["models"][profile_id]
            if value.get("active_model_id") == profile_id:
                value["active_model_id"] = next(iter(value["models"]))
            self.settings._write(value)
        ref = profile.get("credential_ref")
        if ref:
            try:
                self._keyring().delete_password(KEYRING_SERVICE, ref)
            except Exception:
                pass
        return {"removed": profile_id}

    def public(self):
        profile = self.active()
        return {key: value for key, value in profile.items() if key != "credential_ref"} | {
            "credential_saved": bool(profile.get("has_api_key")),
            "api_key": "",
            "profiles": self.list_profiles(),
        }

"""Provision the DSH Web surface and its launch environment for StudyUI.

StudyUI's browser surface is the shipped DSH Web app composed into a private
profile. This module owns only the profile files and the child-process
environment; the installed DSH package and its frontend dist stay untouched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from . import dsh_engine
from .model_profiles import KEYRING_SERVICE

WEB_PROFILE = "studyui-web"
WEB_BUNDLES = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app")
OFFICIAL_HOSTS = frozenset({"api.deepseek.com", "api.deepseek.cn"})
OFFICIAL_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7880
DEFAULT_BACKEND_PORT = 7881

_PROFILE_PACKAGE = {
    "name": "dsh-profile-studyui-web",
    "private": True,
    "dependencies": {},
    "dsh": {"profile": {"bundles": list(WEB_BUNDLES)}},
}

# Same content the shipped `web` profile template writes, so the profile can be
# created without booting DSH first.
_CORDIS_YML = """# dsh profile root — an empty entry list. The tree is composed as patches:
# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml, then any
# --patch overlays. Edit cordis.patch.yml, not this file.
[]
"""

_PNPM_WORKSPACE = """packages:
  - .

nodeLinker: hoisted
autoInstallPeers: false
"""

_PATCH_TEMPLATE = """# StudyUI DSH Web profile patch layer. Created once by scripts/setup_dsh.py;
# later edits (including values saved by the DSH Models page) are preserved.
- id: agent-default-model
  config:
    provider: deepseek-official
    model: {model}
"""


class DshWebError(RuntimeError):
    """Raised when the DSH Web surface cannot be provisioned."""


def web_profile_dir(settings_path: Path) -> Path:
    """Directory of StudyUI's DSH Web profile under the configured DSH home."""
    return dsh_engine.resolve_dsh_home(settings_path) / "profiles" / WEB_PROFILE


def default_workspace_root(settings_path: Path) -> Path:
    """Agent workspace root, kept separate from the DSH home directory."""
    return Path(settings_path).parent / "workspace"


def settings_data(settings_path: Path) -> dict:
    try:
        data = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def select_model(settings_path: Path, profile_id: str | None = None) -> dict:
    """Return the StudyUI model profile DSH Web should use."""
    data = settings_data(settings_path)
    models = data.get("models") or {}
    selected = profile_id or os.environ.get("STUDYUI_WEB_MODEL_PROFILE") or data.get("active_model_id") or ""
    profile = models.get(selected) if isinstance(models, dict) else None
    if not isinstance(profile, dict) or not profile:
        raise DshWebError("StudyUI 尚未配置模型。请先在 StudyUI 中配置 DeepSeek 官方模型，再启动 DSH Web。")
    return profile


def model_host(profile: dict) -> str:
    return (urlsplit(str(profile.get("base_url") or "")).hostname or "").lower()


def is_official_model(profile: dict) -> bool:
    return model_host(profile) in OFFICIAL_HOSTS


def official_profiles(settings_path: Path) -> list[tuple[str, dict]]:
    models = settings_data(settings_path).get("models") or {}
    if not isinstance(models, dict):
        return []
    available = []
    for profile_id, profile in models.items():
        if isinstance(profile, dict) and is_official_model(profile):
            available.append((str(profile_id), profile))
    return available


def official_models(settings_path: Path) -> list[str]:
    available = []
    for profile_id, profile in official_profiles(settings_path):
        label = str(profile.get("name") or profile.get("model") or "DeepSeek")
        available.append(f"{label} [{profile_id}]")
    return available


def resolve_model(
    settings_path: Path,
    profile_id: str | None = None,
    *,
    allow_official_fallback: bool = True,
) -> tuple[dict, str | None]:
    """Select a model for DSH Web, optionally falling back to the only official one.

    Non-DeepSeek OpenAI-compatible gateways are not valid DSH endpoints.
    When the active model is not official and exactly one official profile
    exists, use it and return a notice instead of failing the default launcher.
    """
    data = settings_data(settings_path)
    models = data.get("models") or {}
    models = models if isinstance(models, dict) else {}
    explicit = profile_id or os.environ.get("STUDYUI_WEB_MODEL_PROFILE")
    if explicit:
        profile = models.get(explicit)
        if not isinstance(profile, dict) or not profile:
            raise DshWebError(f"找不到模型配置: {explicit}")
        return profile, None
    active_id = str(data.get("active_model_id") or "")
    active = models.get(active_id)
    if isinstance(active, dict) and is_official_model(active):
        return active, None
    official = official_profiles(settings_path)
    if allow_official_fallback and len(official) == 1:
        fallback_id, fallback = official[0]
        label = str(fallback.get("name") or fallback.get("model") or fallback_id)
        return fallback, f"当前激活模型不是 DeepSeek 官方端点，DSH Web 改用 {label} [{fallback_id}]。"
    if isinstance(active, dict) and active:
        validate_official_model(active, available=official_models(settings_path))
    raise DshWebError("StudyUI 尚未配置模型。请先在 StudyUI 中配置 DeepSeek 官方模型，再启动 DSH Web。")


def validate_official_model(profile: dict, *, available: list[str] | None = None) -> None:
    """Reject non-DeepSeek gateways; DSH Web speaks Messages only."""
    if is_official_model(profile):
        return
    name = str(profile.get("name") or profile.get("model") or "当前模型")
    url = str(profile.get("base_url") or "未配置")
    hint = ""
    if available:
        hint = f" 可用模型: {', '.join(available)}；也可用 STUDYUI_WEB_MODEL_PROFILE=<id> 指定。"
    raise DshWebError(
        "DSH Web 只支持 DeepSeek 官方端点 (api.deepseek.com / api.deepseek.cn)；"
        f"当前模型 {name} 使用 {url}。请在 StudyUI 中切换到 DeepSeek 官方模型后再启动。{hint}"
    )


def resolve_api_key(profile: dict) -> str:
    ref = str(profile.get("credential_ref") or "")
    if ref in {"", "environment"}:
        return os.environ.get("STUDYUI_MODEL_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    try:
        import keyring
    except ImportError:
        return ""
    try:
        return keyring.get_password(KEYRING_SERVICE, ref) or ""
    except Exception:
        return ""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (OSError, ValueError):
        return False


def assert_isolated(dsh_home: Path, workspace_root: Path) -> None:
    """DSH_HOME must not be reachable from (or contain) the agent workspace."""
    if _is_within(dsh_home, workspace_root) or _is_within(workspace_root, dsh_home):
        raise DshWebError(
            "DSH_HOME 与 agent 工作区必须是相互独立的目录；"
            f"当前 DSH_HOME={dsh_home}，workspace={workspace_root}。"
        )


def stale_credentials_warning(dsh_home: Path) -> str | None:
    """Warn when a stored DSH credential would override the launch key."""
    path = Path(dsh_home) / ".credentials.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "DEEPSEEK_API_KEY" in text:
        return f"{path} 中的 DEEPSEEK_API_KEY 会覆盖启动环境注入的密钥；若模型鉴权失败，请更新或删除该条目。"
    return None


def ensure_web_profile(settings_path: Path, *, model: str = DEFAULT_MODEL) -> Path:
    """Create the StudyUI DSH Web profile, preserving anything already there."""
    profile_dir = web_profile_dir(settings_path)
    profile_dir.mkdir(parents=True, exist_ok=True)
    _ensure_package(profile_dir)
    for name, text in (("cordis.yml", _CORDIS_YML), ("pnpm-workspace.yaml", _PNPM_WORKSPACE)):
        path = profile_dir / name
        if not path.exists():
            path.write_text(text, encoding="utf-8")
    patch = profile_dir / "cordis.patch.yml"
    if not patch.exists():
        patch.write_text(_PATCH_TEMPLATE.format(model=model), encoding="utf-8")
    return profile_dir


def _ensure_package(profile_dir: Path) -> None:
    path = profile_dir / "package.json"
    if not path.exists():
        path.write_text(json.dumps(_PROFILE_PACKAGE, indent=2) + "\n", encoding="utf-8")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    dsh = data.setdefault("dsh", {})
    if not isinstance(dsh, dict):
        return
    profile = dsh.setdefault("profile", {})
    if not isinstance(profile, dict):
        return
    bundles = profile.setdefault("bundles", [])
    if not isinstance(bundles, list):
        return
    changed = False
    for bundle in WEB_BUNDLES:
        if bundle not in bundles:
            bundles.append(bundle)
            changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def studyui_plugin_source() -> Path:
    """The StudyUI DSH plugin bundled with this checkout or installation."""
    override = os.environ.get("STUDYUI_DSH_PLUGIN_DIR", "").strip()
    here = Path(__file__).resolve()
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            here.parents[4] / "dsh-plugins" / "studyui-dsh",
            here.parents[3] / "dsh-plugins" / "studyui-dsh",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def _drop_empty_yaml_list(text: str) -> str:
    """Remove the shipped profile's bare `[]` so rows can be appended."""
    meaningful = [
        line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    if meaningful != ["[]"]:
        return text
    kept = [line for line in text.splitlines() if line.strip() != "[]"]
    return "\n".join(kept).rstrip("\n") + "\n"


def install_studyui_plugin(settings_path: Path, *, source: Path | None = None) -> Path:
    """Copy the StudyUI brand plugin into the web profile and enable it once."""
    profile_dir = web_profile_dir(settings_path)
    source = Path(source) if source is not None else studyui_plugin_source()
    if not source.is_dir():
        raise DshWebError(f"StudyUI DSH 插件目录不存在: {source}")
    target = profile_dir / "node_modules" / "studyui-dsh"
    shutil.copytree(
        source,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    patch = profile_dir / "cordis.patch.yml"
    text = patch.read_text(encoding="utf-8") if patch.is_file() else ""
    if "# StudyUI brand plugin" not in text:
        text = _drop_empty_yaml_list(text)
        block = (
            "\n# StudyUI brand plugin (managed by scripts/start_demo.py).\n"
            "- insert:\n"
            "    - id: studyui-brand\n"
            "      name: 'studyui-dsh'\n"
            "- id: ui-brand-official\n"
            "  disabled: true\n"
        )
        text = text.rstrip("\n") + "\n" + block
    if "# StudyUI MCP server" not in text:
        text = _drop_empty_yaml_list(text)
        block = (
            "\n# StudyUI MCP server (managed by scripts/start_demo.py).\n"
            "- insert:\n"
            "    - id: studyui-mcp\n"
            "      name: '@deepseek-ai/dsh-mcp-client'\n"
            "      config:\n"
            "        serverName: studyui\n"
            "        transport: stdio\n"
            "        command: python\n"
            "        args:\n"
            "          - -m\n"
            "          - materials_quality.agent.mcp_server\n"
            "        env:\n"
            "          PYTHONUTF8: '1'\n"
            "          PYTHONIOENCODING: utf-8\n"
            "        startupTimeoutMs: 30000\n"
            "        toolCallTimeoutMs: 120000\n"
        )
        text = text.rstrip("\n") + "\n" + block
    patch.write_text(text, encoding="utf-8")
    return target


def build_web_environment(
    settings_path: Path,
    *,
    profile_id: str | None = None,
    api_key: str | None = None,
    workspace_root: Path | None = None,
) -> dict:
    """Build the child-process environment for `dsh --profile studyui-web`."""
    profile, notice = resolve_model(settings_path, profile_id)
    validate_official_model(profile, available=official_models(settings_path))
    selected_key = api_key if api_key is not None else resolve_api_key(profile)
    if not selected_key:
        raise DshWebError(
            "未找到 DeepSeek API key。请在 StudyUI 模型设置中保存密钥，或设置 DEEPSEEK_API_KEY 环境变量。"
        )
    dsh_home = dsh_engine.resolve_dsh_home(settings_path)
    workspace = Path(workspace_root) if workspace_root is not None else default_workspace_root(settings_path)
    assert_isolated(dsh_home, workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    env = dsh_engine.build_env(
        base_url=str(profile.get("base_url") or ""),
        api_key=selected_key,
        working_directory=workspace,
        dsh_home=dsh_home,
        allow_env_override=False,
    )
    # DSH ignores StudyUI's launcher-side endpoint override; drop it so a stale
    # value cannot confuse debugging.
    env.pop("STUDYUI_DSH_BASE_URL", None)
    if notice:
        env["STUDYUI_WEB_MODEL_NOTICE"] = notice
    env["STUDYUI_WEB_SETTINGS"] = str(Path(settings_path).resolve())
    env["STUDYUI_WEB_WORKSPACE"] = str(workspace.resolve())
    return env


def web_argv(
    command: dsh_engine.DshCommand,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> list[str]:
    """Launcher argv for the StudyUI DSH Web profile."""
    return [
        *command.argv,
        "--profile",
        WEB_PROFILE,
        "--no-open",
        "--host",
        host,
        "--port",
        str(int(port)),
    ]


def parse_ready_url(line: str) -> str | None:
    marker = "dsh web:"
    if not line.startswith(marker):
        return None
    url = line[len(marker) :].strip()
    return url or None


def redact_token(url: str) -> str:
    """Hide the launch token before printing or logging a ready URL."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = []
    for pair in parts.query.split("&"):
        key, sep, _value = pair.partition("=")
        pairs.append("token=***" if key == "token" and sep else pair)
    return parts._replace(query="&".join(pairs)).geturl()


def redact_line(line: str) -> str:
    """Mask any launch token embedded in a whole stdout/log line."""
    return re.sub(r"(token=)[^&\s\"']+", r"\1***", line)

import json
from pathlib import Path

import pytest

from materials_quality.agent import dsh_engine, dsh_web


def _settings(tmp_path, *, base_url="https://api.deepseek.com", credential_ref="studyui-model-test"):
    path = tmp_path / "studyui-settings.json"
    path.write_text(
        json.dumps(
            {
                "active_model_id": "model-1",
                "models": {
                    "model-1": {
                        "id": "model-1",
                        "name": "DeepSeek",
                        "provider": "openai-compatible",
                        "base_url": base_url,
                        "model": "deepseek-flash",
                        "credential_ref": credential_ref,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYUI_DSH_HOME", str(tmp_path / "dsh-home"))


def test_build_web_environment_accepts_official_and_scrubs(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    settings = _settings(tmp_path, base_url="https://api.deepseek.com/v1")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("STUDYUI_DSH_BASE_URL", "https://gateway.example/anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "leak")
    monkeypatch.setenv("MY_SECRET_TOKEN", "leak")

    env = dsh_web.build_web_environment(settings, api_key="sk-test")

    assert env["DEEPSEEK_API_KEY"] == "sk-test"
    assert env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["DSH_HOME"] == str(tmp_path / "dsh-home")
    assert "STUDYUI_DSH_BASE_URL" not in env
    assert "OPENAI_API_KEY" not in env
    assert "MY_SECRET_TOKEN" not in env
    assert not dsh_web._is_within(Path(env["TEMP"]), Path(env["STUDYUI_WEB_WORKSPACE"]))


def test_build_web_environment_falls_back_to_the_only_official_profile(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    settings = _settings(tmp_path, base_url="https://gateway.example/v1")
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["models"]["official"] = {
        "id": "official",
        "name": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "credential_ref": "environment",
    }
    settings.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("STUDYUI_MODEL_API_KEY", "sk-env")

    env = dsh_web.build_web_environment(settings)

    assert env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert "STUDYUI_WEB_MODEL_NOTICE" in env
    assert env["DEEPSEEK_BASE_URL"].startswith("https://api.deepseek.com")


def test_build_web_environment_rejects_non_official_gateway(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    settings = _settings(tmp_path, base_url="https://gateway.example/v1")

    with pytest.raises(dsh_web.DshWebError, match="只支持 DeepSeek 官方端点"):
        dsh_web.build_web_environment(settings, api_key="sk-test")


def test_build_web_environment_requires_api_key(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    settings = _settings(tmp_path, credential_ref="environment")
    monkeypatch.delenv("STUDYUI_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(dsh_web.DshWebError, match="未找到 DeepSeek API key"):
        dsh_web.build_web_environment(settings)


def test_dsh_home_must_be_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("STUDYUI_DSH_HOME", str(workspace / "dsh-home"))
    settings = _settings(tmp_path)

    with pytest.raises(dsh_web.DshWebError, match="必须是相互独立的目录"):
        dsh_web.build_web_environment(settings, api_key="sk-test", workspace_root=workspace)


def test_model_profile_can_be_selected_explicitly(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    settings = _settings(tmp_path)
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["models"]["official-2"] = {
        "id": "official-2",
        "name": "DeepSeek 2",
        "base_url": "https://api.deepseek.cn",
        "model": "deepseek-flash",
        "credential_ref": "environment",
    }
    data["active_model_id"] = "model-1"
    settings.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("STUDYUI_MODEL_API_KEY", "sk-env")

    env = dsh_web.build_web_environment(settings, profile_id="official-2")

    assert env["DEEPSEEK_API_KEY"] == "sk-env"
    assert env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.cn/anthropic"


def test_map_base_url_ignores_launcher_override_for_web(monkeypatch):
    monkeypatch.setenv("STUDYUI_DSH_BASE_URL", "https://gateway.example/anthropic")
    assert (
        dsh_engine.map_base_url("https://api.deepseek.com", allow_env_override=False)
        == "https://api.deepseek.com/anthropic"
    )
    assert (
        dsh_engine.map_base_url("https://api.deepseek.com", allow_env_override=True)
        == "https://gateway.example/anthropic"
    )


def test_redact_token_hides_only_the_launch_token():
    url = "http://127.0.0.1:7880/?token=secret-value&other=1"
    assert dsh_web.redact_token(url) == "http://127.0.0.1:7880/?token=***&other=1"
    assert dsh_web.redact_token("http://127.0.0.1:7880/") == "http://127.0.0.1:7880/"
    assert (
        dsh_web.redact_line("dsh web: http://127.0.0.1:7880/?token=secret-value\n")
        == "dsh web: http://127.0.0.1:7880/?token=***\n"
    )


def test_parse_ready_url():
    assert (
        dsh_web.parse_ready_url("dsh web: http://127.0.0.1:7880/?token=x") == "http://127.0.0.1:7880/?token=x"
    )
    assert dsh_web.parse_ready_url("starting dsh web: nope") is None
    assert dsh_web.parse_ready_url("dsh web:") is None

import json
import sys
from pathlib import Path

from materials_quality.agent import dsh_engine


def test_map_base_url_known_hosts():
    assert dsh_engine.map_base_url("https://api.deepseek.com") == "https://api.deepseek.com/anthropic"
    assert (
        dsh_engine.map_base_url("https://api.deepseek.com/anthropic") == "https://api.deepseek.com/anthropic"
    )
    assert dsh_engine.map_base_url("http://127.0.0.1:1234/v1").endswith("/v1")
    for suffix in ("/v1", "/v1/", "/anthropic/v1", "/anthropic/"):
        assert dsh_engine.map_base_url("https://api.deepseek.com" + suffix) == (
            "https://api.deepseek.com/anthropic"
        )
    assert dsh_engine.map_base_url("https://api.deepseek.cn/v1") == "https://api.deepseek.cn/anthropic"


def test_map_base_url_env_override(monkeypatch):
    monkeypatch.setenv("STUDYUI_DSH_BASE_URL", "https://gateway.example/anthropic")
    assert dsh_engine.map_base_url("https://api.deepseek.com") == "https://gateway.example/anthropic"


def test_permission_flags():
    assert dsh_engine.permission_flags("read_only") == [
        "--permission-mode",
        "read-only",
        "--approval-policy",
        "never",
    ]
    assert dsh_engine.permission_flags("per_action") == [
        "--permission-mode",
        "workspace-write",
        "--approval-policy",
        "ask",
    ]
    assert dsh_engine.permission_flags("project_collaboration") == [
        "--permission-mode",
        "workspace-write",
        "--approval-policy",
        "never",
    ]
    assert dsh_engine.permission_flags("full_access") == [
        "--permission-mode",
        "danger-full-access",
        "--approval-policy",
        "never",
    ]


def test_build_argv_permission_mode_override():
    command = dsh_engine.DshCommand(["node", "bin.js"], Path("/tmp/home"), "studyui")
    argv = dsh_engine.build_argv(
        command,
        message="x",
        permission_preset="project_collaboration",
        permission_mode="danger-full-access",
    )
    assert "danger-full-access" in argv


def test_build_argv_includes_resume_and_flags():
    command = dsh_engine.DshCommand(["node", "bin.js"], Path("/tmp/home"), "studyui")
    argv = dsh_engine.build_argv(
        command,
        message="分析数据",
        permission_preset="read_only",
        session_id="session-123",
        max_turns=12,
    )
    assert argv[:3] == ["node", "bin.js", "--profile"]
    assert "studyui" in argv
    assert "--json" in argv
    assert argv[-1] == "分析数据"
    assert "--session-id" in argv and "session-123" in argv
    assert "--max-turns" in argv and "12" in argv
    assert "--permission-mode" in argv and "read-only" in argv


def test_resolve_command_env_override(monkeypatch, tmp_path):
    fake = tmp_path / "dsh.bat"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("STUDYUI_DSH_BIN", str(fake))
    command = dsh_engine.resolve_command(tmp_path / "agent.sqlite3")
    assert command is not None
    assert command.argv == [str(fake)]


def test_resolve_command_js_entrypoint_uses_node(monkeypatch, tmp_path):
    fake_js = tmp_path / "bin.js"
    fake_js.write_text("", encoding="utf-8")
    fake_node = tmp_path / "node"
    fake_node.write_text("", encoding="utf-8")
    monkeypatch.setenv("STUDYUI_DSH_BIN", str(fake_js))
    monkeypatch.setenv("STUDYUI_NODE_BIN", str(fake_node))
    command = dsh_engine.resolve_command(tmp_path / "agent.sqlite3")
    assert command is not None
    assert command.argv == [str(fake_node), str(fake_js)]


def test_ensure_profile_writes_bundles_and_patch(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYUI_DSH_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STUDYUI_DSH_MODEL", "deepseek-v4.1-flash")
    profile_dir = dsh_engine.ensure_profile(tmp_path / "agent.sqlite3")
    package = json.loads((profile_dir / "package.json").read_text(encoding="utf-8"))
    assert package["dsh"]["profile"]["bundles"] == [
        "@deepseek-ai/dsh-base",
        "@deepseek-ai/dsh-headless",
    ]
    patch = (profile_dir / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "session-log-deepseek" in patch and "disabled: true" in patch
    assert "deepseek-v4.1-flash" in patch
    assert (tmp_path / "home" / "AGENTS.md").is_file()


def test_build_env_maps_endpoint_and_path(monkeypatch, tmp_path):
    env = dsh_engine.build_env(
        base_url="https://api.deepseek.com",
        api_key="sk-test",
        working_directory=tmp_path,
    )
    assert env["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["DEEPSEEK_API_KEY"] == "sk-test"
    assert env["STUDYUI_PROJECT_DIR"] == str(tmp_path)
    assert str(Path(sys.executable).resolve().parent) in env["PATH"]


def test_iter_json_lines_parses_and_skips_garbage(tmp_path):
    import io

    payload = b'{"type":"status","phase":"step_start"}\nnot json\n{"type":"final","text":"OK"}\n'
    events = list(dsh_engine._iter_json_lines(io.BytesIO(payload)))
    assert [e.get("type") for e in events] == ["status", "final"]
    assert events[-1]["text"] == "OK"


def test_agent_temp_dir_is_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    chosen = dsh_engine._agent_temp_dir(workspace)
    assert chosen is not None
    assert chosen != workspace.resolve()
    assert workspace.resolve() not in chosen.parents


def test_build_env_temp_outside_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    env = dsh_engine.build_env(base_url="https://api.deepseek.com", api_key="", working_directory=workspace)
    temp_root = Path(env["TEMP"]).resolve()
    assert workspace.resolve() not in temp_root.parents
    assert temp_root != workspace.resolve()


def test_explicit_model_is_not_replaced_by_available_dsh(tmp_path, monkeypatch):
    from materials_quality.agent import dsh_engine, dsh_sdk_engine
    from materials_quality.agent.harness import StudyUIAgent

    monkeypatch.setattr(dsh_engine, "available", lambda _: True)
    monkeypatch.setattr(dsh_sdk_engine, "available", lambda _: True)
    monkeypatch.setenv("STUDYUI_AGENT_ENGINE", "dsh-sdk")
    agent = StudyUIAgent(tmp_path / "agent.db", canvas=object(), model=object())
    assert agent.agent_engine() == "legacy"

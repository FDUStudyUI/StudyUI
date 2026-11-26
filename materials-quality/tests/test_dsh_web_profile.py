import json

from materials_quality.agent import dsh_web


def _settings(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYUI_DSH_HOME", str(tmp_path / "dsh-home"))
    return tmp_path / "studyui-settings.json"


def test_ensure_web_profile_creates_shipped_layout(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    profile = dsh_web.ensure_web_profile(settings)

    assert profile == tmp_path / "dsh-home" / "profiles" / "studyui-web"
    package = json.loads((profile / "package.json").read_text(encoding="utf-8"))
    assert package["dsh"]["profile"]["bundles"] == [
        "@deepseek-ai/dsh-base",
        "@deepseek-ai/dsh-web-app",
    ]
    assert (profile / "cordis.yml").is_file()
    assert (profile / "pnpm-workspace.yaml").is_file()
    patch = (profile / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "agent-default-model" in patch
    assert "deepseek-flash" in patch


def test_ensure_web_profile_preserves_user_edits(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    profile = dsh_web.ensure_web_profile(settings)

    package_path = profile / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["name"] = "user-renamed"
    package["dependencies"] = {"studyui-dsh": "0.1.0"}
    package["dsh"]["profile"]["bundles"] = ["@deepseek-ai/dsh-base", "studyui-dsh"]
    package_path.write_text(json.dumps(package), encoding="utf-8")
    patch_path = profile / "cordis.patch.yml"
    user_patch = patch_path.read_text(encoding="utf-8") + "- id: user-row\n  disabled: true\n"
    patch_path.write_text(user_patch, encoding="utf-8")

    dsh_web.ensure_web_profile(settings)

    package = json.loads(package_path.read_text(encoding="utf-8"))
    assert package["name"] == "user-renamed"
    assert package["dependencies"] == {"studyui-dsh": "0.1.0"}
    assert package["dsh"]["profile"]["bundles"] == [
        "@deepseek-ai/dsh-base",
        "studyui-dsh",
        "@deepseek-ai/dsh-web-app",
    ]
    assert patch_path.read_text(encoding="utf-8") == user_patch


def test_web_profile_dir_uses_configured_dsh_home(tmp_path, monkeypatch):
    home = tmp_path / "custom-home"
    monkeypatch.setenv("STUDYUI_DSH_HOME", str(home))
    assert dsh_web.web_profile_dir(tmp_path / "settings.json") == home / "profiles" / "studyui-web"

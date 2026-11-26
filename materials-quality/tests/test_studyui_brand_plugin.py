import json

from materials_quality.agent import dsh_web


def _profile(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYUI_DSH_HOME", str(tmp_path / "dsh-home"))
    settings = tmp_path / "studyui-settings.json"
    return dsh_web.ensure_web_profile(settings), settings


def test_install_copies_plugin_and_enables_it(tmp_path, monkeypatch):
    profile, settings = _profile(tmp_path, monkeypatch)

    target = dsh_web.install_studyui_plugin(settings)

    assert target == profile / "node_modules" / "studyui-dsh"
    assert (target / "lib" / "client.js").is_file()
    assert (target / "lib" / "index.js").is_file()
    assert (target / "assets" / "manifest.webmanifest").is_file()
    package = json.loads((target / "package.json").read_text(encoding="utf-8"))
    assert package["dsh"]["client"]["platform"] == "web"
    patch = (profile / "cordis.patch.yml").read_text(encoding="utf-8")
    assert "# StudyUI brand plugin" in patch
    assert "studyui-dsh" in patch
    assert "ui-brand-official" in patch and "disabled: true" in patch
    assert "# StudyUI MCP server" in patch
    assert "dsh-mcp-client" in patch
    assert "materials_quality.agent.mcp_server" in patch


def test_install_is_idempotent(tmp_path, monkeypatch):
    profile, settings = _profile(tmp_path, monkeypatch)
    dsh_web.install_studyui_plugin(settings)
    first = (profile / "cordis.patch.yml").read_text(encoding="utf-8")

    dsh_web.install_studyui_plugin(settings)

    assert (profile / "cordis.patch.yml").read_text(encoding="utf-8") == first


def test_install_removes_the_shipped_empty_yaml_list(tmp_path, monkeypatch):
    profile, settings = _profile(tmp_path, monkeypatch)
    patch = profile / "cordis.patch.yml"
    patch.write_text("# shipped profile\n[]\n", encoding="utf-8")

    dsh_web.install_studyui_plugin(settings)

    text = patch.read_text(encoding="utf-8")
    assert all(line.strip() != "[]" for line in text.splitlines())
    assert "studyui-brand" in text


def test_client_bundle_declares_brand_slots_and_title_guard():
    source = dsh_web.studyui_plugin_source()
    text = (source / "lib" / "client.js").read_text(encoding="utf-8")
    assert "sidebar.brand.mark" in text
    assert "sidebar.brand.name" in text
    assert "StudyUI" in text
    assert "document.title" in text
    assert "__ModuleLoader__.load" in text


def test_host_bundle_rewrites_index_and_serves_assets():
    source = dsh_web.studyui_plugin_source()
    text = (source / "lib" / "index.js").read_text(encoding="utf-8")
    assert "/studyui/manifest.webmanifest" in text
    assert "/studyui/favicon.svg" in text
    assert "tapIndex" in text
    assert "connection.admit" in text


def test_canvas_host_bundle_serves_and_proxies():
    source = dsh_web.studyui_plugin_source()
    text = (source / "lib" / "index.js").read_text(encoding="utf-8")
    for token in (
        "/studyui/canvas",
        "/studyui/canvas/api",
        "/studyui/api/v1",
        "health_check",
        "registerUpgrade",
        "proxyUpgrade",
        "canvasIndex",
        "studyui-canvas-skin",
        "sidebar-wrapper",
        "data-studyui-route",
        "rewriteValue",
        "hideVendorChrome",
        "Error while updating the Component",
        "Flow needs review",
        "Update required",
        "studyui-canvas-bar",
        "studyui-canvas-loading",
        "studyui-canvas-ready",
        "studyui-canvas-theme",
        "#body.dark",
    ):
        assert token in text


def test_canvas_client_bundle_panel_and_run_bridge():
    source = dsh_web.studyui_plugin_source()
    text = (source / "lib" / "client.js").read_text(encoding="utf-8")
    for token in (
        "sidebar.panellist",
        "工作流画布",
        "新建工作流",
        "← 工作流",
        "打开",
        "复制",
        "运行记录",
        "直接运行",
        "交给 Agent",
        "查看详情",
        "材料任务",
        "材料参数表单",
        "适用边界",
        "导出简报",
        "运行记录",
        "MaterialTaskDialog",
        "GovernanceDialog",
        "studyui-material",
        "示例数据 · 五案例",
        "交给 DSH",
        "个任务组",
        "示例数据：",
        "我想做材料任务",
        "请运行我的工作流",
        "studyui-run-workflow",
        "studyui-canvas-theme",
        "data-ds-dark-theme",
        "data-ds-theme-source",
        "sessions",
        "uiSession",
    ):
        assert token in text
    assert "mcp__studyui__" not in text
    assert "run_science_operation" not in text
    assert "load_demo_dataset" not in text
    package = json.loads((source / "package.json").read_text(encoding="utf-8"))
    injected = package["dsh"]["client"]["inject"]
    assert "@deepseek-ai/dsh-client-ui-session" in injected
    assert "@deepseek-ai/dsh-api-session-controller" in injected


def test_canvas_bridge_hands_runs_to_dsh():
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    text = (root / "scripts" / "assets" / "canvas_bridge.html").read_text(encoding="utf-8")
    assert "studyui-run-workflow" in text
    assert "studyui-run-status" in text

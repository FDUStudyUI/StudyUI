from pathlib import Path
from fastapi.testclient import TestClient
from materials_quality.agent.server import create_app
from materials_quality.agent.data_inspection import audit_standards_and_dimensions, inspect_file, authorized_file


def test_ui_phase4_elements_and_rendering(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        page = client.get("/")
        assert page.status_code == 200
        html = page.text

        # Feature 1: Lightbox & Data preview
        assert "lightbox-dialog" in html
        assert "data-preview-dialog" in html
        assert "openLightbox" in html
        assert "previewData" in html

        # Feature 2: Rich Markdown & Math
        assert "rich-table" in html
        assert "math-inline" in html
        assert "renderRichContent" in html

        # Feature 3: Research brief export
        assert "btn-export-brief" in html
        assert "exportResearchBrief" in html

        # Feature 4: Thinking drawer
        assert "thinking-drawer" in html
        assert "thinking-stepper" in html

        # Feature 5: Follow-up chips
        assert "followup-chip" in html

        # Feature 8: Grounding / DOI
        assert "doi-badge" in html
        assert "toggleGrounding" in html

        # Feature 9: Code to canvas node
        assert "code-btn" in html
        assert "insertCanvasNode" in html

        # Feature 10: Hypothesis tree
        assert "hypothesis-tree" in html

        # New UX Fix 1: Sticky footer & dialog click outside
        assert "sticky-dialog-footer" in html
        assert "backdrop-filter:blur(12px)" in html

        # New UX Fix 2: Model URL preview & test banner
        assert "model-url-preview" in html
        assert "model-test-banner" in html
        assert "updateUrlPreview" in html

        # New UX Fix 3: Live progress stepper & typing cursor
        assert "streaming-step-box" in html
        assert "typing-cursor" in html

        # New UX Fix 4: Clickable dropdown action menu (no number prompts)
        assert "action-dropdown-menu" in html
        assert "action-menu-item" in html
        assert "openActionMenu" in html


def test_canvas_insert_node_api(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        code_sample = (
            "def calculate_hardening(strain, stress):\n"
            "    import numpy as np\n"
            "    return float(np.polyfit(np.log(strain), np.log(stress), 1)[0])\n"
        )
        res = client.post(
            "/api/canvas/insert-node",
            json={
                "name": "HardeningExponentCalc",
                "code": code_sample,
                "session_id": "test_session",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["component_name"] == "HardeningExponentCalc"
        assert "hardeningexponentcalc.py" in data["file"]


def test_standards_and_dimensions_watchdog(tmp_path):
    # 1. Tensile test file -> ASTM E8
    tensile_file = tmp_path / "01_Ti64_tensile.csv"
    tensile_file.write_text("Strain,Stress_MPa\n0.001,120\n0.002,240\n0.005,850\n", encoding="utf-8")
    tensile_res = inspect_file(authorized_file(str(tensile_file), f"分析 {tensile_file}"))
    tensile_audit = tensile_res.get("standards_and_compliance")
    assert tensile_audit is not None
    assert "ASTM E8" in tensile_audit["standard"]
    assert tensile_audit["compliance_passed"] is True

    # 2. XRD file -> ASTM E915 / JCPDS
    xrd_file = tmp_path / "04_3YSZ_xrd.txt"
    xrd_file.write_text("2theta,intensity\n20.0,150\n20.02,180\n20.04,220\n", encoding="utf-8")
    xrd_res = inspect_file(authorized_file(str(xrd_file), f"分析 {xrd_file}"))
    xrd_audit = xrd_res.get("standards_and_compliance")
    assert xrd_audit is not None
    assert "ASTM E915" in xrd_audit["standard"] or "JCPDS" in xrd_audit["standard"]

    # 3. Spectra file -> ASTM E1840
    spectra_file = tmp_path / "02_raman_spectra.csv"
    spectra_file.write_text("wavelength_nm,counts\n500,10\n501,25\n502,40\n", encoding="utf-8")
    spectra_res = inspect_file(authorized_file(str(spectra_file), f"分析 {spectra_file}"))
    spectra_audit = spectra_res.get("standards_and_compliance")
    assert spectra_audit is not None
    assert "ASTM E1840" in spectra_audit["standard"]

    # 4. Battery file -> IEC 62660
    battery_file = tmp_path / "05_battery_cycle.csv"
    battery_file.write_text("soc,voltage_v\n0.1,3.2\n0.2,3.4\n0.3,3.6\n", encoding="utf-8")
    battery_res = inspect_file(authorized_file(str(battery_file), f"分析 {battery_file}"))
    battery_audit = battery_res.get("standards_and_compliance")
    assert battery_audit is not None
    assert "IEC 62660" in battery_audit["standard"]


def test_session_delete_and_drop_overlay_hidden(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="drop-overlay"' in page.text
        assert 'style="display:none"' in page.text
        assert '.dropzone-overlay[hidden]{display:none !important}' in page.text

        # Create session
        create_res = client.post("/api/sessions", json={"title": "Test Session to Delete"})
        assert create_res.status_code == 201
        session_id = create_res.json()["id"]

        # Verify session exists
        get_res = client.get(f"/api/sessions/{session_id}")
        assert get_res.status_code == 200

        # Delete session
        del_res = client.delete(f"/api/sessions/{session_id}")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "deleted"

        # Verify session is gone
        get_after = client.get(f"/api/sessions/{session_id}")
        assert get_after.status_code == 404


def test_model_endpoint_auto_completion():
    from materials_quality.agent.model import ChatModel

    # 1. Base URL without /chat/completions -> automatically appends
    m1 = ChatModel(base_url="https://api.deepseek.com", model="deepseek-flash")
    assert m1._endpoint() == "https://api.deepseek.com/chat/completions"

    # 2. Base URL already having /chat/completions -> does not duplicate
    m2 = ChatModel(base_url="https://api.deepseek.com/chat/completions", model="deepseek-flash")
    assert m2._endpoint() == "https://api.deepseek.com/chat/completions"

    # 3. Base URL with /v1
    m3 = ChatModel(base_url="https://api.openai.com/v1", model="gpt-4o")
    assert m3._endpoint() == "https://api.openai.com/v1/chat/completions"

    # 4. Base URL with trailing slash and /chat/completions
    m4 = ChatModel(base_url="https://api.openai.com/v1/chat/completions/", model="gpt-4o")
    assert m4._endpoint() == "https://api.openai.com/v1/chat/completions"


def test_deepseek_reasoning_and_gemini_stepper_ui_elements(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        page = client.get("/")
        assert page.status_code == 200
        html = page.text

        # DeepSeek thinking container
        assert "deepseek-thinking" in html
        assert "thinking-head" in html
        assert "thinking-content" in html
        assert "toggleThinking" in html
        assert "createThinkingBox" in html

        # Gemini / Atria tool audit stepper
        assert "audit-stepper-box" in html
        assert "audit-steps-list" in html
        assert "audit-step-item" in html
        assert "createAuditStepper" in html

        # Model mode badge & SSE connection logic
        assert "model-badge" in html
        assert "text/event-stream" in html


def test_harness_multi_model_thinking_adapter_think_tag(tmp_path):
    from materials_quality.agent.harness import StudyUIAgent

    class MockModel:
        def __init__(self):
            self.calls = []

        def complete(self, messages, tools, *, max_tokens=3000):
            self.calls.append(messages)
            return {
                "content": "<think>\n根据 ASTM E8 规范与胡克弹性区间，提取前 2% 弹性形变段斜率...\n</think>\n钛合金 Ti-6Al-4V 样件的弹性模量经线性回归计算为 114.2 GPa，符合标称范围。",
            }

    model = MockModel()
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=model)
    session_id = agent.new_session(project_id=agent.store.create_project("test"))
    
    res = agent.run_turn(session_id, "请评估钛合金拉伸数据")
    # Verify reasoning was extracted from <think> tag
    assert "ASTM E8 规范与胡克弹性区间" in res["reasoning_content"]
    assert "114.2 GPa" in res["message"]
    assert "<think>" not in res["message"]
    assert "</think>" not in res["message"]

    # Verify tool_steps includes preflight
    assert len(res["tool_steps"]) >= 1
    assert any("Skill" in step["title"] for step in res["tool_steps"])

    # Verify stored in SQLite messages
    msgs = agent.store.messages(session_id)
    last_assistant = msgs[-1]
    assert "ASTM E8 规范" in last_assistant["reasoning_content"]
    assert "tool_steps" in last_assistant


def test_sse_streaming_and_live_progress_endpoint(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    class MockModel:
        def complete(self, messages, tools, *, max_tokens=3000):
            return {
                "content": "分析完毕，拉伸数据无异常。",
                "reasoning_content": "深度思考：校验应变率与加载速率一致性",
            }

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    app.state.harness.model = MockModel()
    app.state.harness._custom_model = True

    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        # Create a session
        create_res = client.post("/api/sessions", json={"title": "SSE Test Session"})
        assert create_res.status_code == 201
        session_id = create_res.json()["id"]

        # Request via SSE stream
        sse_res = client.post(
            f"/api/sessions/{session_id}/messages",
            headers={"Accept": "text/event-stream"},
            json={"message": "执行拉伸数据校验"}
        )
        assert sse_res.status_code == 200
        assert "text/event-stream" in sse_res.headers.get("content-type", "")

        stream_text = sse_res.text
        assert "event: start" in stream_text
        assert "event: step_end" in stream_text
        assert "event: reasoning" in stream_text
        assert "event: done" in stream_text
        assert "深度思考：校验应变率" in stream_text

        # Verify session history GET includes reasoning_content and tool_steps
        get_res = client.get(f"/api/sessions/{session_id}")
        assert get_res.status_code == 200
        data = get_res.json()
        assert len(data["messages"]) == 2  # user + assistant
        assistant_msg = [m for m in data["messages"] if m["role"] == "assistant"][0]
        assert "深度思考：校验应变率" in assistant_msg["reasoning_content"]
        assert len(assistant_msg["tool_steps"]) >= 1


def test_canvas_view_bidirectional_switch_controls(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    with TestClient(app, base_url="http://127.0.0.1:7880") as client:
        page = client.get("/")
        assert page.status_code == 200
        html = page.text
        # Verify canvas view has back button and view switchers
        assert 'id="btn-back-chat"' in html
        assert "← 返回研究对话" in html
        assert "btn-mode-chat" in html
        assert "btn-mode-split" in html
        assert "btn-mode-flow" in html
        # Verify no hardcoded Gemini/Atria in stepper or thinking titles
        assert "Gemini / Atria 引擎" not in html
        assert "DeepSeek + Gemini" not in html


def test_approval_execution_without_intent_or_group_permits_action(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    harness = app.state.harness

    # 1. Test build_workflow approval in ungrouped session
    session_id = harness.new_session("测试审批会话", project_id=None)
    approval_id = harness.request_approval(
        session_id=session_id,
        action="workflow.create",
        reason="用户审批自动建流",
        request={"tool": "build_workflow", "args": {"name": "自动化测试流", "actions": []}}
    )["approval_id"]

    # Approving must succeed and create workflow without PermissionError
    res = harness.decide_approval(approval_id, "approved")
    assert res["status"] == "completed"
    assert res["result"]["status"] == "created"
    assert res["result"]["flow_name"] == "自动化测试流"

    # 2. Test write_research_report approval without prompt text intent
    approval_id2 = harness.request_approval(
        session_id=session_id,
        action="artifact.create",
        reason="用户审批撰写报告",
        request={"tool": "write_research_report", "args": {"title": "钛合金拉伸测试报告", "content": "# 实验分析\n数据真实有效。"}}
    )["approval_id"]

    res2 = harness.decide_approval(approval_id2, "approved")
    assert res2["status"] == "completed"
    assert res2["result"]["status"] == "created"
    assert res2["result"]["title"] == "钛合金拉伸测试报告"


def test_turn_response_includes_dynamic_model_name(tmp_path):
    workflows = tmp_path / "workflows"
    components = tmp_path / "components"
    frontend = tmp_path / "frontend"
    workflows.mkdir()
    components.mkdir()
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><html><body>Canvas</body></html>", encoding="utf-8")

    class NamedMockModel:
        def __init__(self, model_name="qwen2.5:32b"):
            self.model = model_name
        def complete(self, messages, tools, *, max_tokens=3000, on_chunk=None):
            return {"content": "分析完成", "reasoning_content": ""}

    app = create_app(tmp_path / "agent.sqlite3", workflows, components, frontend)
    app.state.harness.model = NamedMockModel("qwen2.5:32b")
    app.state.harness._custom_model = True

    session_id = app.state.harness.new_session("模型名称测试", project_id=None)
    turn_res = app.state.harness.run_turn(session_id, "请问你能做什么？")
    assert turn_res["model"] == "qwen2.5:32b"


def test_natural_single_word_intents_authorization():
    from materials_quality.agent.harness import (
        _explicit_run_intent,
        _explicit_build_intent,
        _explicit_report_intent,
        _explicit_delete_intent,
    )

    # 1. Run intents
    for word in ["运行", "跑", "执行", "启动", "计算", "重跑", "开始", "再跑一次", "运行！", "运行。"]:
        assert _explicit_run_intent(word), f"Failed to match run intent for {word!r}"
    assert not _explicit_run_intent("不要运行")
    assert not _explicit_run_intent("暂不执行")

    # 2. Build intents
    for word in ["建流", "构建", "创建", "搭建", "做流", "新建", "搭个流", "搭建工作流"]:
        assert _explicit_build_intent(word), f"Failed to match build intent for {word!r}"

    # 3. Report intents
    for word in ["报告", "写报告", "出报告", "做报告", "生成报告", "整理报告", "输出报告"]:
        assert _explicit_report_intent(word), f"Failed to match report intent for {word!r}"

    # 4. Delete intents
    for word in ["删除", "删除工作流", "移除工作流", "清空工作流"]:
        assert _explicit_delete_intent(word), f"Failed to match delete intent for {word!r}"


def test_model_streaming_graceful_fallback(monkeypatch):
    from materials_quality.agent.model import ChatModel

    model = ChatModel(base_url="https://api.deepseek.com", model="deepseek-flash", api_key="test-key")

    call_count = {"stream": 0, "non_stream": 0}

    def fake_execute_http(payload, headers, *, is_stream, on_chunk=None):
        if is_stream:
            call_count["stream"] += 1
            raise ValueError("Stream connection failed: 400 Bad Request")
        call_count["non_stream"] += 1
        return {"role": "assistant", "content": "Non-streaming fallback succeeded"}

    monkeypatch.setattr(model, "_execute_http", fake_execute_http)

    chunks = []
    result = model.complete([{"role": "user", "content": "hello"}], [], on_chunk=lambda k, d: chunks.append((k, d)))
    assert call_count["stream"] == 1
    assert call_count["non_stream"] == 1
    assert result["content"] == "Non-streaming fallback succeeded"




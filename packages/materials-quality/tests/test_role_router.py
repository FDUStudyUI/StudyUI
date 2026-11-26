"""Unit and integration tests for deterministic role subgraph routing."""

from __future__ import annotations

import pytest

from materials_quality.agent.harness import TOOLS, StudyUIAgent
from materials_quality.agent.role_router import (
    build_role_context_note,
    route_tools,
    select_role,
)
from materials_quality.assets.roles import SAFETY_ALWAYS_TOOLS


class _RecordingModel:
    """Minimal fake model capturing messages and tool schemas passed by Harness."""

    model = "fake-studyui-test"

    def __init__(self, reply: str = "已完成检查。"):
        self.reply = reply
        self.calls: list[dict] = []

    def complete(self, messages, tools, max_tokens=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tool_names": [t["function"]["name"] for t in tools],
            }
        )
        return {"content": self.reply, "tool_calls": []}


def test_select_role_routes_domains_and_fallbacks():
    assert select_role("请帮我分析这条拉伸应力-应变曲线的杨氏模量")["role_key"] == "characterization_analyst"
    assert select_role("分析这条 XRD 衍射峰和电池循环容量保持率")["role_key"] == "characterization_analyst"
    assert select_role("做一下 TG/DSC 热分析失重台阶")["role_key"] == "characterization_analyst"
    assert select_role("请先检查这份 CSV 的缺失值、重复行和表头结构")["role_key"] == "data_quality_auditor"
    assert select_role("查一下相关文献和 DOI 综述")["role_key"] == "literature_reviewer"

    # Word boundary prevents substring false positives (e.g. "postgres" does not contain "tg" word).
    assert select_role("check postgres connection config")["role_key"] == "workflow_planner"

    # Multi-domain (literature + characterization) falls back to workflow_planner.
    multi = select_role("分析这份 XRD 数据，并帮我查相关文献 DOI")
    assert multi["role_key"] == "workflow_planner"
    assert multi["reason"] == "multi_domain_request"

    # Canvas run always routes to workflow_planner for governance safety.
    canvas = select_role("分析 XRD", canvas_run={"flow_id": "f1"})
    assert canvas["role_key"] == "workflow_planner"

    # Explicit override works with or without "R:" prefix; unknown role fails loudly.
    assert select_role("随便聊聊", explicit_role="R:literature_reviewer")["role_key"] == "literature_reviewer"
    with pytest.raises(ValueError, match="Unknown research role"):
        select_role("hello", explicit_role="unknown_role")


def test_route_tools_passthrough_and_pruning():
    lit_sel = select_role("帮我查一下相关论文 DOI")
    all_names = [t["function"]["name"] for t in TOOLS]

    # Disabled => exact full pass-through.
    unfiltered = route_tools(TOOLS, lit_sel, enabled=False)
    assert [t["function"]["name"] for t in unfiltered] == all_names

    # Enabled => pruned to literature reviewer allowlist + safety tools.
    pruned = route_tools(TOOLS, lit_sel, enabled=True)
    pruned_names = {t["function"]["name"] for t in pruned}
    assert "search_literature" in pruned_names
    assert "delete_workflow" not in pruned_names
    assert "run_workflow" not in pruned_names
    assert set(SAFETY_ALWAYS_TOOLS).issubset(pruned_names)

    note = build_role_context_note(lit_sel)
    assert "学术文献与方法证据角色" in note
    assert "R:literature_reviewer" in note
    assert "明确不支持" in note


def test_harness_role_routing_default_off_and_opt_in(tmp_path):
    db_path = tmp_path / "studyui.db"
    all_tool_names = [t["function"]["name"] for t in TOOLS]

    # 1. Default mode (enable_role_routing=False): 100% backward compatible.
    model_off = _RecordingModel()
    agent_off = StudyUIAgent(db_path, model=model_off)
    sid_off = agent_off.new_session("默认兼容测试")
    res_off = agent_off.run_turn(sid_off, "请帮我查一下相关论文 DOI")
    assert res_off["role_selection"]["role_key"] == "literature_reviewer"
    assert model_off.calls[0]["tool_names"] == all_tool_names
    assert not any(e.get("kind") == "role_selected" for e in agent_off.store.events(sid_off, limit=50))

    # 2. Opt-in mode (enable_role_routing=True): prunes tools & injects role note.
    model_on = _RecordingModel()
    agent_on = StudyUIAgent(tmp_path / "studyui_on.db", model=model_on, enable_role_routing=True)
    sid_on = agent_on.new_session("角色路由开启测试")
    res_on = agent_on.run_turn(sid_on, "请帮我查一下相关论文 DOI")
    assert res_on["role_selection"]["role_key"] == "literature_reviewer"
    passed_tools = set(model_on.calls[0]["tool_names"])
    assert len(passed_tools) < len(all_tool_names)
    assert "search_literature" in passed_tools
    assert "delete_workflow" not in passed_tools
    system_texts = [m["content"] for m in model_on.calls[0]["messages"] if m["role"] == "system"]
    assert any("【当前科研角色子图：" in text for text in system_texts)
    assert any(e.get("kind") == "role_selected" for e in agent_on.store.events(sid_on, limit=50))

    # 3. Explicit per-turn role override activates routing even on default agent.
    model_override = _RecordingModel()
    agent_override = StudyUIAgent(tmp_path / "studyui_override.db", model=model_override)
    sid_ov = agent_override.new_session("显式角色测试")
    res_ov = agent_override.run_turn(sid_ov, "你好", role="data_quality_auditor")
    assert res_ov["role_selection"]["role_key"] == "data_quality_auditor"
    ov_tools = set(model_override.calls[0]["tool_names"])
    assert "inspect_research_file" in ov_tools
    assert "search_literature" not in ov_tools

from materials_quality.agent.harness import TOOLS, StudyUIAgent


def test_method_recommendation_is_registered_read_only_and_never_runs_tools(tmp_path):
    assert "recommend_analysis_methods" in {tool["function"]["name"] for tool in TOOLS}
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=object())
    session = agent.new_session()
    agent.permissions.set_preset(None, "read_only")
    args = {"query": "SNV", "signal_type": "darkfield_intensity", "allow_intensity_loss": False}
    decision = agent._authorize_tool(session, "recommend_analysis_methods", args, "比较绝对强度")
    assert decision["allowed"]
    result = agent._dispatch(session, "recommend_analysis_methods", args, "比较绝对强度")
    assert result["condition_evidence"] == "caller_declarations_not_measurement_verification"
    assert result["automatic_execution"] is False
    assert result["candidates"]
    assert any(row["blocked"] for row in result["candidates"])


def test_prompt_requires_missing_conditions_and_source_transfer_separation(tmp_path):
    agent = StudyUIAgent(tmp_path / "state.sqlite3", langflow=object(), model=object())
    prompt = agent._system_prompt()
    assert "recommend_analysis_methods" in prompt
    assert "不得臆造" in prompt

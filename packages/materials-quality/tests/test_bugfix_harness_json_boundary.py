"""Regression tests: model-facing and HTTP-facing payloads must stay strict JSON."""

import json

from materials_quality.agent.harness import StudyUIAgent, _bounded_tool_content


def _strict(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def test_turn_response_replaces_non_finite_workflow_values(tmp_path):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=object(), model=object())
    session_id = agent.new_session()
    agent._turn_state.value = {
        "canvas_run": {"flow_id": "flow-local", "project_id": "project-1", "consumed": True},
        "workflow_run_result": {
            "flow_id": "flow-local",
            "outputs": [
                {
                    "component_id": "stats-1",
                    "results": {
                        "summary": {
                            "p_value": float("nan"),
                            "effect_size": float("inf"),
                            "rows": 3,
                        }
                    },
                }
            ],
        },
    }

    response = agent._turn_response(session_id, "completed")

    _strict(response)
    summary = response["workflow_result"]["outputs"][0]["results"]["summary"]
    assert summary["p_value"] is None
    assert summary["effect_size"] is None
    assert summary["rows"] == 3


def test_bounded_tool_content_replaces_non_finite_values():
    encoded = _bounded_tool_content(
        "run_workflow",
        {
            "status": "completed",
            "result": {
                "outputs": [
                    {
                        "node_id": "stats-1",
                        "outputs": {"summary": {"p_value": float("nan"), "rows": 2}},
                    }
                ]
            },
        },
    )

    parsed = json.loads(encoded)
    _strict(parsed)
    summary = parsed["result"]["outputs"][0]["outputs"]["summary"]
    assert summary["p_value"] is None
    assert summary["rows"] == 2

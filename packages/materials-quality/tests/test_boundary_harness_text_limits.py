"""Boundary tests: turn message/context limits fail closed on invalid text."""

import pytest

from materials_quality.agent.harness import StudyUIAgent


def _agent(tmp_path):
    return StudyUIAgent(tmp_path / "agent.sqlite3", langflow=object(), model=object())


def test_run_turn_accepts_exactly_12000_characters(tmp_path):
    agent = _agent(tmp_path)
    session = agent.new_session()
    with pytest.raises(Exception) as excinfo:
        agent.run_turn(session, "a" * 12000)
    # Reaches the model/skill pipeline instead of failing the message validator.
    assert "1 to 12000" not in str(excinfo.value)


def test_run_turn_rejects_12001_characters(tmp_path):
    agent = _agent(tmp_path)
    session = agent.new_session()
    with pytest.raises(ValueError, match="1 to 12000"):
        agent.run_turn(session, "a" * 12001)


@pytest.mark.parametrize("message", ["", " ", "\n\t "])
def test_run_turn_rejects_blank_messages(tmp_path, message):
    agent = _agent(tmp_path)
    session = agent.new_session()
    with pytest.raises(ValueError, match="1 to 12000"):
        agent.run_turn(session, message)


@pytest.mark.parametrize("message", ["ok \ud800 text", "\udc00", "混合 \ud800 文本"])
def test_run_turn_rejects_lone_surrogates_cleanly(tmp_path, message):
    agent = _agent(tmp_path)
    session = agent.new_session()
    with pytest.raises(ValueError, match="Unicode|unicode"):
        agent.run_turn(session, message)


def test_internal_context_with_lone_surrogate_fails_cleanly(tmp_path):
    agent = _agent(tmp_path)
    session = agent.new_session()
    payload = {"kind": "approved_action_succeeded", "pad": "ok \ud800 text"}
    with pytest.raises(ValueError, match="Unicode|unicode"):
        agent.run_turn(session, "", internal_context=payload)


def test_internal_context_12000_character_boundary(tmp_path):
    agent = _agent(tmp_path)
    session = agent.new_session()
    payload = {"kind": "approved_action_succeeded", "pad": ""}
    payload["pad"] = "x" * (12000 - len(json_dumps(payload)))
    assert len(json_dumps(payload)) == 12000
    with pytest.raises(Exception) as excinfo:
        agent.run_turn(session, "", internal_context=payload)
    assert "size limit" not in str(excinfo.value)

    payload["pad"] += "x"
    assert len(json_dumps(payload)) == 12001
    with pytest.raises(ValueError, match="size limit"):
        agent.run_turn(session, "", internal_context=payload)


def json_dumps(value):
    import json

    return json.dumps(value, ensure_ascii=False)

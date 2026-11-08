"""Boundary tests: project file listing truncation flag must match the cap."""

from materials_quality.agent.harness import StudyUIAgent


class _NoFlow:
    def get_flow(self, _flow_id):
        raise FileNotFoundError(_flow_id)


def _agent_with_directory(tmp_path):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=_NoFlow(), model=object())
    project = agent.store.create_project("listing")
    session = agent.new_session(project_id=project)
    directory = tmp_path / "data"
    directory.mkdir()
    agent.store.add_project_directory(project, directory)
    return agent, session, directory


def _touch(directory, count):
    for index in range(count):
        (directory / f"f{index:04d}.csv").write_text("x,y\n1,2\n", encoding="utf-8")


def test_exactly_300_entries_are_not_reported_as_truncated(tmp_path):
    agent, session, directory = _agent_with_directory(tmp_path)
    _touch(directory, 300)

    listing = agent._list_project_files(session, str(directory))

    assert listing["truncated"] is False
    assert len(listing["files"]) == 200


def test_301_entries_are_reported_as_truncated(tmp_path):
    agent, session, directory = _agent_with_directory(tmp_path)
    _touch(directory, 301)

    listing = agent._list_project_files(session, str(directory))

    assert listing["truncated"] is True
    assert len(listing["files"]) == 200


def test_cap_across_multiple_roots_is_reported_as_truncated(tmp_path):
    agent, session, first = _agent_with_directory(tmp_path)
    second = tmp_path / "data2"
    second.mkdir()
    agent.store.add_project_directory(agent.store.session_context(session)["project_id"], second)
    _touch(first, 200)
    _touch(second, 150)

    listing = agent._list_project_files(session, None)

    assert listing["truncated"] is True
    assert len(listing["directories"]) + len(listing["files"]) <= 300

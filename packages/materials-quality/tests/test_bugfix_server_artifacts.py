"""Regression test: same-second artifacts are ranked by insertion order."""

import materials_quality.agent.store as store_module
from materials_quality.agent.store import SessionStore


def test_latest_artifact_uses_creation_order_within_one_second(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "agent.sqlite3")
    project = store.create_project("project")
    session = store.create_session("session", project_id=project)
    monkeypatch.setattr(store_module, "_now", lambda: "2026-01-01T00:00:00+00:00")
    first = tmp_path / "first.html"
    second = tmp_path / "second.html"
    first.write_bytes(b"old report")
    second.write_bytes(b"new report")
    # The older artifact id sorts after the newer id, which must not matter.
    store.register_artifact(
        "ffffffff-ffff-4fff-8fff-ffffffffffff",
        session,
        project,
        "report.html",
        first,
        "a" * 64,
        10,
    )
    store.register_artifact(
        "00000000-0000-4000-8000-000000000000",
        session,
        project,
        "report.html",
        second,
        "b" * 64,
        11,
    )

    latest = store.latest_artifacts(session)
    assert [item["sha256"] for item in latest] == ["b" * 64]

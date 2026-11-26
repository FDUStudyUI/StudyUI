"""Regression tests for the workflow file repository: resilient listing and history order."""

import hashlib
import json
import time
import uuid

from materials_quality.agent.workflow_files import WorkflowFileStore


def _raw(flow):
    return (json.dumps(flow, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _revision(flow):
    return hashlib.sha256(_raw(flow)).hexdigest()


def _flow(name="flow", **extra):
    return {"id": str(uuid.uuid4()), "name": name, "data": {"nodes": [], "edges": []}, **extra}


def test_list_ignores_files_that_are_not_workflows(tmp_path):
    store = WorkflowFileStore(tmp_path)
    flow = _flow("kept")
    store.save(flow, create_only=True)
    # A hand-placed backup / manifest and a truncated flow file must not break
    # listing (the canvas project list, migration and delete all rely on it).
    (tmp_path / "manifest.json").write_text(json.dumps({"flows": []}), encoding="utf-8")
    (tmp_path / "backup copy.json").write_text(json.dumps({"id": "not-a-workflow"}), encoding="utf-8")
    (tmp_path / f"{uuid.uuid4()}.json").write_text("{truncated", encoding="utf-8")

    assert store.list() == [flow]
    assert store.read(flow["id"])[0] == flow


def test_history_lists_the_most_recent_saved_version_first(tmp_path):
    store = WorkflowFileStore(tmp_path)
    flow_id = str(uuid.uuid4())
    # Pick version payloads whose revision hashes are NOT in chronological
    # order, so a listing sorted by file name (the old behaviour) is provably
    # different from a listing sorted by saved_at.
    salt = 0
    while True:
        versions = [
            {
                "id": flow_id,
                "name": f"v{index}",
                "data": {"nodes": [], "edges": []},
                "salt": salt * 7 + index,
            }
            for index in range(3)
        ]
        revisions = [_revision(item) for item in versions]
        if sorted(range(3), key=lambda index: revisions[index]) != [0, 1, 2]:
            break
        salt += 1

    store.save(versions[0], create_only=True)
    for version in versions[1:]:
        time.sleep(0.005)
        store.save(version)

    # Each save keeps the replaced content as history, so the history holds
    # v0 and v1 and the most recently replaced version (v1) must come first.
    rows = store.history(flow_id)
    assert [row["name"] for row in rows] == ["v1", "v0"]
    assert [row["saved_at"] for row in rows] == sorted((row["saved_at"] for row in rows), reverse=True)

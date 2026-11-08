"""Boundary tests: run-result compaction must not silently hide executed nodes."""

import json

from materials_quality.agent import harness as H


def _entries(count):
    return [
        {
            "component_id": f"c{index}",
            "component_display_name": f"node {index}",
            "results": {"report": {"text": "t" * 200}},
        }
        for index in range(count)
    ]


def _run(entry_count):
    return {"session_id": "s", "outputs": [{"outputs": _entries(entry_count)}]}


def test_compact_run_result_reports_all_executed_nodes_beyond_cap():
    compact = H._compact_run_result(_run(61))

    assert len(compact["outputs"]) == 60
    assert compact["nodes_total"] == 61
    assert compact["nodes_omitted"] == 1


def test_compact_run_result_cap_boundary_is_exact():
    for count in (59, 60):
        compact = H._compact_run_result(_run(count))
        assert compact["nodes_total"] == count
        assert len(compact["outputs"]) == count
        assert "nodes_omitted" not in compact

    compact = H._compact_run_result(_run(70))
    assert compact["nodes_total"] == 70
    assert compact["nodes_omitted"] == 10


def test_bounded_run_workflow_result_keeps_truncated_node_count():
    result = {
        "status": "completed",
        "flow_name": "flow",
        "result": H._compact_run_result(_run(61)),
        "artifacts": [],
    }
    parsed = json.loads(H._bounded_tool_content("run_workflow", result))

    assert parsed["result"]["nodes_total"] == 61
    assert parsed["result"]["nodes_omitted"] == 21
    assert len(parsed["result"]["outputs"]) == 40


def test_compact_run_result_tolerates_malformed_flow_node_metadata():
    flow = {"data": {"nodes": [{"id": "c0", "data": None}, {"id": "c1"}, "junk", None]}}
    compact = H._compact_run_result(_run(1), flow=flow)

    assert compact["outputs"][0]["node_id"] == "c0"

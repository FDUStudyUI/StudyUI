"""Actual graph connections and structured metadata for four independent lessons."""

import json

import pytest
from lfx.graph import Graph


@pytest.mark.parametrize(
    "case,status",
    [
        ("competing", "completed"),
        ("nested", "completed"),
        ("small_n", "descriptive_only"),
        ("all_failed", "failed"),
    ],
)
def test_reliability_workflow_roundtrip(case, status, tmp_path):
    from scripts.build_reliability_examples import build_examples

    payload = build_examples(tmp_path)[case]
    assert len(payload["data"]["nodes"]) == len(payload["data"]["edges"]) == 3
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    report = graph.get_vertex("ResearchSkillExecutor-" + case).results["report"].data
    assert report["status"] == status
    if case == "competing":
        assert report["tables"]["table"]["preview"][0]["window_candidate_nm"] == 730
    if case == "nested":
        pair = report["data"]["group_inference"]["pairwise"][0]
        assert pair["n_a"] == pair["n_b"] == 3
    if case == "small_n":
        assert report["data"]["pairwise"][0]["p_raw"] is None

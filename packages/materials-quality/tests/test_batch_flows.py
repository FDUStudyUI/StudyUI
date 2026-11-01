"""Execute serialized connections rather than invoking only individual methods."""

import json

import pytest
from lfx.graph import Graph

from scripts.build_batch_examples import build_examples


def test_portable_twenty_specimen_flow_executes_after_json_roundtrip(tmp_path):
    payload = build_examples(tmp_path)["01_twenty_specimens"]
    assert len(payload["data"]["nodes"]) == 6
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    results = graph.get_vertex("MaterialBatchSummary-twenty").results
    summary = results["table"]
    assert len(summary) == 20
    assert summary["quality_findings"].eq(0).all()
    assert summary["elastic_modulus_MPa"].tolist() == pytest.approx(
        [200000 * (1 + i / 10) for i in range(20)]
    )
    assert len(results["artifacts"]) == 1

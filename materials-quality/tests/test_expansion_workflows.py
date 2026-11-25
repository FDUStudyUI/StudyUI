"""Run the serialized lessons through LFX rather than calling individual nodes."""

import json

import pytest
from lfx.graph import Graph


@pytest.mark.parametrize("case", ["specimen", "mechanics", "photoresponse", "battery"])
def test_expansion_workflow_roundtrip(case, tmp_path):
    from scripts.build_expansion_examples import build_examples

    payload = build_examples(tmp_path)[case]
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step

    def frame(suffix, port):
        node = next(n for n in payload["data"]["nodes"] if n["id"].endswith("-" + suffix))
        return graph.get_vertex(node["id"]).results[port]

    if case == "specimen":
        table = frame("specimen-merge", "table")
        assert table["sample_id"].tolist() == ["001", "002", "003", "004", "005", "006"]
        assert table["window_candidate_nm"].tolist() == [700, 705, 710, 730, 735, 740]
        assert table["resistance_ohm"].tolist() == pytest.approx([200, 250, 500, 100, 125, 200])
        assert "batch" in table and len(table) == 6
    elif case == "mechanics":
        table = frame("mechanics-calibration", "table")
        assert table["stress_MPa"].iloc[0] == pytest.approx(0)
        assert table["stress_MPa"].iloc[-1] == pytest.approx((table["bridge_mV"].iloc[-1] - 1) * 2)
        report = frame("mechanics-analysis", "report").data
        assert report["tables"]["table"]["preview"][0]["elastic_modulus_MPa"] == pytest.approx(200000)
    elif case == "photoresponse":
        features = frame("photoresponse-analysis", "features")
        assert features["amplitude_A"].iloc[0] == pytest.approx(8e-6)
        assert features["rise_time_s"].iloc[0] == pytest.approx(3.2)
        assert features["recovery_time_s"].iloc[0] == pytest.approx(3.2)
    else:
        features = frame("battery-analysis", "features")
        assert features["retention_pct"].tolist() == pytest.approx([100, 90, 80, 100, 95, 90])
        assert features["baseline_capacity_ah"].tolist() == pytest.approx([2, 2, 2, 1, 1, 1])

    assert frame(case + "-report", "report").data["artifacts"]

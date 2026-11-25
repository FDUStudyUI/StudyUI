"""Exercise portable feature-port connections after native graph serialization."""

import json

import pytest
from lfx.graph import Graph

from scripts.build_research_examples import build_examples


def test_eight_curve_feature_pipeline_reopens_without_original_fixture_files(tmp_path):
    payload = build_examples(tmp_path)["01_eight_curve_features"]
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    analyzer = graph.get_vertex("BatchSpectrumAnalyzer-eight").results
    report = analyzer["report"].data
    assert report["data"]["counts"] == {"total": 8, "completed": 8, "failed": 0, "skipped": 0}
    assert len(analyzer["features"]) == 16
    assert report["table_shape"][0] == 8 * 501
    candidate = graph.get_vertex("SciencePreprocessFilter-candidates").results["table"]
    assert len(candidate) == 8
    assert candidate["lambda10_nm"].tolist() == pytest.approx([700, 710, 720, 730, 740, 750, 760, 770])
    grouped = graph.get_vertex("ScienceStatsGrouped-means").results["table"]
    assert grouped["group"].tolist() == ["A", "B"]
    assert grouped["count"].tolist() == [4, 4]
    assert grouped["mean"].tolist() == pytest.approx([715, 755])
    assert grouped["unit"].tolist() == ["nm", "nm"]
    html = graph.get_vertex("ScienceExportReport-html").results["report"].data
    assert html["data"]["verified"]

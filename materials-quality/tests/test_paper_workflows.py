"""Execute serialized native lessons and inspect scientific outputs and sources."""

import json
from pathlib import Path

import pytest
from lfx.graph import Graph

from scripts.build_paper_examples import build_examples


@pytest.mark.parametrize(
    "case", ["01_spectrum_evidence", "02_pls_holdout", "03_local_repair", "04_incompatible_method"]
)
@pytest.mark.parametrize("source", ["committed", "generated"])
def test_paper_workflow_native_roundtrip(case, source, tmp_path):
    if source == "committed":
        path = Path(__file__).resolve().parents[1] / "examples/paper_flows" / f"{case}.json"
        payload = json.loads(path.read_text("utf-8"))
    else:
        payload = build_examples(tmp_path)[case]
    for node in payload["data"]["nodes"]:
        template = node["data"]["node"]["template"]
        if "ui_mode" in template:
            assert template["ui_mode"]["value"] == "form"
            assert template["config_json"]["value"] == "{}"
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step

    def output(kind, port="report"):
        node = next(node for node in payload["data"]["nodes"] if node["data"]["type"] == kind)
        result = graph.get_vertex(node["id"]).results[port]
        return result.data if port == "report" else result

    report = output("ScienceExportReport")
    assert report["artifacts"]
    text = Path(report["artifacts"][0]).read_text("utf-8")
    if case == "01_spectrum_evidence":
        features = output("ScienceMaterialsSpectra", "features")
        assert features.peak_position.iloc[0] == pytest.approx(720.0, abs=2.5)
        assert "Evidence-linked claims" in text
        method = output("ScienceLitMethodRecommend")["data"]["candidates"][0]
        assert method["source"]["url"] and method["status"] == "eligible"
        bundle = output("ScienceLitResultEvidence")["data"]["evidence_bundle"]
        assert bundle["upstream_execution"]["operation"] == "materials.spectra"
    elif case == "02_pls_holdout":
        data = output("ScienceMaterialsChemometrics")["data"]
        assert data["metrics"]["test"]["n_samples"] == 10
        assert data["metrics"]["test"]["rmse"] < 0.2
        assert not set(data["train_sample_ids"]) & set(data["test_sample_ids"])
        assert "table_sha256" in text
    elif case == "03_local_repair":
        table = output("ScienceMaterialsAnalysisPlan", "table")
        assert table["count"].tolist() == [4, 4]
        assert table["mean"].iloc[0] < 0 < table["mean"].iloc[1]
        assert output("ScienceMaterialsAnalysisPlan")["execution_status"] == "completed"
    else:
        candidates = output("ScienceLitMethodRecommend")["data"]["candidates"]
        assert candidates and all(row["status"] == "blocked" for row in candidates)
        assert all(row["execution"] is None for row in candidates)

"""Execute the committed demo graphs and independently check supplied data."""

import base64
import hashlib
import json
from pathlib import Path

import pytest

IDS = ["ti64_tensile", "raman_spectra", "material_contrast", "zirconia_xrd", "battery_cycle"]
ROWS = [401, 4008, 24, 3001, 1000]


def test_demo_catalog_preserves_original_bytes_and_truthful_shape():
    from materials_quality.demos.catalog import get_dataset, list_datasets, read_demo_bytes

    records = list_datasets()
    assert [r["id"] for r in records] == IDS
    assert [r["row_count"] for r in records] == ROWS
    root = Path(__file__).resolve().parents[3] / "demo_datasets"
    for record in records:
        assert {"id", "icon", "title", "format", "filename", "desc", "prompt"} <= record.keys()
        raw = read_demo_bytes(record["id"])
        assert raw == (root / record["filename"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]
        assert record["provenance"]["experimental_provenance_verified"] is False
    assert records[0]["specimen_count"] == 1
    assert records[2]["independent_unit_count"] == 8
    assert records[3]["comment_line_count"] == 18
    assert records[4]["cycle_count"] == 1
    records[0]["columns"].clear()
    assert get_dataset(IDS[0])["columns"]
    for bad in ("../ti64_tensile", "missing", "../../server.py", None, []):
        with pytest.raises(ValueError):
            get_dataset(bad)
        with pytest.raises(ValueError):
            read_demo_bytes(bad)


@pytest.mark.parametrize("dataset_id", IDS)
def test_stored_demo_flow_executes_with_raw_source_and_artifacts(dataset_id):
    from lfx.graph import Graph

    from materials_quality.demos.catalog import get_dataset, read_demo_bytes
    from materials_quality.demos.reference import load_reference_flow

    info = get_dataset(dataset_id)
    payload = load_reference_flow(dataset_id)
    vertices = payload["data"]["nodes"]
    source = next(v for v in vertices if v["data"]["type"] == "ScienceFixtureBundle")
    bundle = json.loads(base64.b64decode(source["data"]["node"]["template"]["bundle_base64"]["value"]))
    assert bundle["synthetic"] is True
    assert base64.b64decode(bundle["assets"][info["filename"]]["base64"]) == read_demo_bytes(dataset_id)
    assert any(v["data"]["type"] == "ScienceIoTableImport" for v in vertices)
    graph = Graph.from_payload(payload)
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    imported = graph.get_vertex("ScienceIoTableImport-" + dataset_id + "-import").results
    assert len(imported["table"]) == info["row_count"]
    assert imported["report"].data["data"]["source_sha256"] == info["sha256"]
    final = graph.get_vertex("ScienceExportReport-" + dataset_id + "-report").results["report"].data
    artifacts = final["artifacts"]
    assert any(a.endswith(".html") for a in artifacts)
    figures = [
        a
        for node in vertices
        for value in graph.get_vertex(node["id"]).results.values()
        if hasattr(value, "data") and isinstance(value.data, dict)
        for a in value.data.get("artifacts", [])
        if a.endswith(".png")
    ]
    assert figures
    html = Path(next(a for a in artifacts if a.endswith(".html"))).read_text(encoding="utf-8")
    assert "data:image/png;base64," in html
    assert info["sha256"] in html
    for warning in info["limitations"]:
        assert warning in html
    for item in artifacts:
        assert Path(item).is_file()
    if dataset_id == "ti64_tensile":
        report = (
            graph.get_vertex("ScienceMaterialsMechanics-" + dataset_id + "-analysis").results["report"].data
        )
        assert report["data"]["elastic_modulus_MPa"] == pytest.approx(200000)
    elif dataset_id == "raman_spectra":
        result = graph.get_vertex("BatchSpectrumAnalyzer-" + dataset_id + "-analysis").results
        assert result["features"]["curve_id"].nunique() == 8
    elif dataset_id == "material_contrast":
        result = graph.get_vertex("ContrastStudy-" + dataset_id + "-analysis").results
        assert len(result["units"]) == 8
        assert sorted(result["units"]["value"].tolist()) == pytest.approx(
            [0.1, 1.1, 2.1, 3.1, 4.1, 5.1, 6.1, 7.1]
        )
    elif dataset_id == "zirconia_xrd":
        report = (
            graph.get_vertex("ScienceMaterialsXrd-" + dataset_id + "-analysis").results["report"].data["data"]
        )
        assert len(report["peaks"]) >= 5
        assert not report["matches"]
        assert report["fit"] is None
    else:
        for branch in ("charge", "discharge"):
            result = graph.get_vertex("SciencePreprocessFilter-" + dataset_id + "-" + branch).results
            assert len(result["table"]) == 500
            assert result["table"]["Step"].nunique() == 1


def test_reference_loader_returns_fresh_fixed_id_payload():
    from materials_quality.demos.reference import load_reference_flow

    payload = load_reference_flow(IDS[0])
    payload["data"]["nodes"].clear()
    assert load_reference_flow(IDS[0])["data"]["nodes"]
    for value in ("../ti64_tensile", "ti64_tensile.json", None, []):
        with pytest.raises(ValueError):
            load_reference_flow(value)


def test_source_checksum_rejects_changed_packaged_bytes(tmp_path, monkeypatch):
    from materials_quality.demos import catalog

    (tmp_path / "data").mkdir()
    (tmp_path / "catalog.json").write_bytes((catalog.ROOT / "catalog.json").read_bytes())
    record = catalog.get_dataset(IDS[0])
    (tmp_path / "data" / record["filename"]).write_bytes(b"changed")
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        catalog.read_demo_bytes(IDS[0])


def test_reference_checksum_rejects_changed_stored_graph(tmp_path, monkeypatch):
    import shutil

    from materials_quality.demos import reference

    shutil.copytree(reference.ROOT / "flows", tmp_path / "flows")
    path = tmp_path / "flows" / (IDS[0] + ".json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["description"] = "unexpected edit"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(reference, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        reference.load_reference_flow(IDS[0])

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLOWS = sorted((ROOT / "examples/science_flows").glob("[0-9][0-9]-*.json"))


@pytest.mark.parametrize("path", FLOWS, ids=lambda path: path.stem)
def test_committed_native_flow_wiring_sources_truth_and_artifacts(path):
    from scripts.build_science_examples import verify_flow

    result = verify_flow(path)
    assert result["operations"]
    assert result["edges"] >= len(result["operations"])
    assert result["artifacts_read_back"]


def test_gallery_covers_every_new_node():
    import json

    from materials_quality.science.catalog import entries

    assert len(FLOWS) == 9
    classes = {e["class_name"]: e["key"] for e in entries()}
    found = set()
    for path in [*FLOWS, *(ROOT / "examples/paper_flows").glob("*.json")]:
        data = json.loads(path.read_text(encoding="utf-8"))
        found.update(
            classes[n["data"]["type"]] for n in data["data"]["nodes"] if n["data"]["type"] in classes
        )
    assert found == {e["key"] for e in entries()}

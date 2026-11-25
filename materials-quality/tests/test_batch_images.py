import numpy as np
import pytest
from PIL import Image

from materials_quality.science.image_batch import analyze_images


def test_regions_calibration_and_same_basename_isolation(tmp_path):
    paths = []
    for folder in ["a", "b"]:
        d = tmp_path / folder
        d.mkdir()
        p = d / "same.png"
        x = np.zeros((20, 20), dtype=np.uint8)
        x[3:5, 3:5] = 255
        x[10:13, 10:13] = 255
        Image.fromarray(x).save(p)
        paths.append(str(p))
    r = analyze_images(
        paths,
        {
            "threshold": 128,
            "output_dir": str(tmp_path / "out"),
            "calibrations": [{"path": paths[0], "pixel_size": 2.0, "spatial_unit": "um", "group": "G"}],
        },
    )
    a = r.features[r.features.image_id == r.table.iloc[0].image_id]
    assert a.area.tolist() == [16, 36]
    assert set(r.features.length_unit) == {"um", "px"}
    assert len(set(r.artifacts)) == 4
    assert all(__import__("pathlib").Path(p).exists() for p in r.artifacts)
    assert r.data["group_summary"][0]["particle_count"] == 2


def test_calibration_requires_exact_identity(tmp_path):
    p = tmp_path / "x.png"
    Image.fromarray(np.eye(8, dtype=np.uint8) * 255).save(p)
    with pytest.raises(ValueError, match="exact"):
        analyze_images([str(p)], {"calibrations": [{"path": "x.png", "pixel_size": 1, "spatial_unit": "um"}]})
    with pytest.raises(ValueError, match="calibration"):
        analyze_images([str(p)], {"spatial_unit": "um"})


def test_native_image_component(tmp_path, monkeypatch):
    import asyncio

    from lfx.custom import Component
    from lfx.custom.eval import eval_custom_component_code
    from lfx.graph import Graph
    from lfx.services.deps import get_settings_service

    from components.materials_batch.batch_image_analyzer import BatchImageAnalyzer

    monkeypatch.setattr(get_settings_service().settings, "restrict_local_file_access", False)
    assert BatchImageAnalyzer.__bases__ == (Component,)
    assert next(i for i in BatchImageAnalyzer.inputs if i.name == "image_files").is_list
    path = tmp_path / "i.png"
    Image.fromarray(np.eye(8, dtype=np.uint8) * 255).save(path)
    node = BatchImageAnalyzer().set(image_files=[str(path)])
    results, _ = asyncio.run(node.build_results())
    assert len(results["images"]) == 1
    assert len(results["features"]) == 8
    payload = Graph(start=node, end=node).dump()
    source = payload["data"]["nodes"][0]["data"]["node"]["template"]["code"]["value"]
    assert eval_custom_component_code(source).__name__ == "BatchImageAnalyzer"


def test_all_fail_explicit_status(tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(b"not an image")
    r = analyze_images([str(p)], {"on_error": "continue"})
    assert r.data["execution_status"] == "failed"
    assert r.data["counts"]["completed"] == 0


def test_missing_image_is_an_isolated_failure_in_continue_mode(tmp_path):
    path = tmp_path / "good.png"
    Image.fromarray(np.eye(8, dtype=np.uint8) * 255).save(path)
    result = analyze_images([str(path), str(tmp_path / "missing.png")], {"on_error": "continue"})
    assert result.data["counts"]["completed"] == 1
    assert result.data["counts"]["failed"] == 1
    assert len(result.table) == 2

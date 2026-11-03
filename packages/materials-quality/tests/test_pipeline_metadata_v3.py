"""Scientific output ports and unit metadata remain usable across connections."""

import numpy as np
import pandas as pd
import pytest

from materials_quality.science.catalog import component_class


def test_native_peak_features_can_feed_grouped_statistics():
    x = np.arange(400.0, 801.0)
    node = component_class("materials.spectra")().set(
        ui_mode="form",
        input_table=pd.DataFrame({"x": x, "y": np.exp(-(((x - 600) / 20) ** 2))}),
        cfg_x_unit="nm",
        cfg_intensity_unit="counts",
    )
    assert "features" in {p.name for p in node.outputs}
    peaks = node.build_features()
    assert peaks.loc[0, "peak_position"] == pytest.approx(600)
    assert len(node.build_report().data["features_preview"]["records"]) == 1


def test_grouped_result_report_can_remain_connected_to_filter_and_plot():
    frame = pd.DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 2.0, 3.0, 4.0]})
    frame.attrs["units"] = {"value": "nm"}
    grouped = component_class("stats.grouped")().set(
        input_table=frame, ui_mode="form", cfg_group="group", cfg_columns=["value"]
    )
    table, report = grouped.build_table(), grouped.build_report()
    filtered = component_class("preprocess.filter")().set(
        input_table=table, input_data=report, ui_mode="form", cfg_conditions=[]
    )
    result = filtered.build_table()
    assert list(result["mean"]) == [1.5, 3.5]
    assert result.attrs["units"]["mean"] == "nm"
    assert set(filtered.build_report().data["data"]["units"]) <= set(result)


def test_stale_upstream_units_are_dropped_but_conflicts_on_existing_columns_are_errors():
    from materials_quality.science.preprocessing import table_units

    frame = pd.DataFrame({"mean": [1.0]})
    frame.attrs["units"] = {"mean": "nm"}
    assert table_units(frame, {"units": {"old_value": "nm"}}) == {"mean": "nm"}
    with pytest.raises(ValueError, match="conflicting"):
        table_units(frame, {"units": {"mean": "MPa"}})
    with pytest.raises(ValueError, match="existing columns"):
        table_units(frame, declared={"typo": "nm"})


def test_zarr_directory_metadata_changes_invalidate_real_node_cache(tmp_path):
    import json

    folder = tmp_path / "live.zarr"
    folder.mkdir()
    (folder / ".zgroup").write_text('{"zarr_format":2}')
    metadata = folder / ".zattrs"
    metadata.write_text('{"run":1}')
    node = component_class("io.instrument_import")().set(
        ui_mode="form", cfg_path=str(folder), cfg_format="zarr", cfg_mode="browse"
    )
    before = node.build_report().data
    metadata.write_text(json.dumps({"run": 2}))
    after = node.build_report().data
    assert before["provenance"]["input_sha256"] != after["provenance"]["input_sha256"]
    assert after["provenance"]["source_files"]


def test_zarr_hash_enforces_budgets_before_opening_any_content(tmp_path, monkeypatch):
    from pathlib import Path

    from materials_quality.science.langflow_adapter import _file_hashes

    root = tmp_path / "bounded.zarr"
    root.mkdir()
    (root / ".zgroup").write_text('{"zarr_format":2}')
    for i in range(3):
        (root / str(i)).write_bytes(b"a")
    opened = []
    original = Path.open

    def tracked(path, *args, **kwargs):
        opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked)
    with pytest.raises(ValueError, match="max_store_entries"):
        _file_hashes([str(root)], paths=True, max_store_entries=1)
    assert not opened


def test_zarr_hash_does_not_hide_files_disappearing_mid_read(tmp_path, monkeypatch):
    from pathlib import Path

    from materials_quality.science.langflow_adapter import _file_hashes

    root = tmp_path / "changed.zarr"
    root.mkdir()
    (root / ".zgroup").write_text('{"zarr_format":2}')
    (root / "chunk").write_bytes(b"a")
    original = Path.open

    def fail_chunk(path, *args, **kwargs):
        if path.name == "chunk":
            raise FileNotFoundError("chunk disappeared after manifest")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_chunk)
    with pytest.raises(ValueError, match="changed or could not be read"):
        _file_hashes([str(root)], paths=True)

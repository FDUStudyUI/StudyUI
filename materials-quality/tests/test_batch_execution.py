"""A fixed scientific graph must process whole independent specimens."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from lfx.schema import Data

from materials_quality.context import table_fingerprint
from materials_quality.science.catalog import component_class

ROOT = Path(__file__).resolve().parents[1]


def tensile_batch(count=3, bad_last=False):
    from materials_quality.batch.packet import make_batch, make_item

    source = pd.read_csv(ROOT / "examples/science/materials/fixtures/synthetic_tensile.csv")
    items = []
    for index in range(count):
        frame = source.copy(deep=True)
        frame["stress"] *= 1 + index / 10
        if bad_last and index == count - 1:
            frame.loc[0, "stress"] = np.nan
        items.append(
            make_item(
                f"sample-{index}",
                f"试样{index}",
                {"source_name": f"sample-{index}.csv", "source_sha256": table_fingerprint(frame)},
                table=frame,
            )
        )
    return make_batch(items)


def mechanics(packet):
    return component_class("materials.mechanics")().set(
        ui_mode="form",
        input_data=Data(data=packet),
        cfg_x="strain",
        cfg_y="stress",
        cfg_strain_unit="fraction",
        cfg_stress_unit="MPa",
        cfg_fit_range_min=0,
        cfg_fit_range_max=0.0008,
    )


def test_twenty_specimens_are_independent_and_match_single_item_truth():
    packet = mechanics(tensile_batch(20)).build_report().data
    assert packet["schema_version"] == "materials-batch/1"
    assert packet["counts"]["completed"] == 20
    assert packet["counts"]["failed"] == 0
    assert [item["id"] for item in packet["items"]] == [f"sample-{i}" for i in range(20)]
    for index, item in enumerate(packet["items"]):
        assert item["report"]["data"]["elastic_modulus_MPa"] == pytest.approx(200000 * (1 + index / 10))
        assert item["report"]["data"]["yield_stress_MPa"] == pytest.approx(
            202.01005025125627 * (1 + index / 10)
        )
        assert item["report"]["table_summary"]["rows"] == 401


def test_one_bad_specimen_remains_in_result_and_does_not_stop_others():
    packet = mechanics(tensile_batch(3, bad_last=True)).build_report().data
    assert packet["counts"]["completed"] == 2
    assert packet["counts"]["failed"] == 1
    assert packet["execution_status"] == "partial_failed"
    failed = packet["items"][-1]
    assert failed["id"] == "sample-2" and failed["error"]["stage"] == "materials.mechanics"
    assert failed["table"] is None


def test_error_stop_policy_is_explicit_and_all_failed_never_says_completed():
    packet = tensile_batch(1, bad_last=True)
    assert mechanics(packet).build_report().data["execution_status"] == "failed"
    packet["on_error"] = "stop"
    with pytest.raises(ValueError, match="sample-0|试样0"):
        mechanics(packet).build_report()


def test_batch_uses_full_curves_not_the_report_preview():
    packet = mechanics(tensile_batch(2)).build_report().data
    from materials_quality.batch.packet import unpack_table

    assert all(len(unpack_table(item["table"])) == 401 for item in packet["items"])


def test_batch_table_output_keeps_identity_and_only_successful_measurements():
    node = mechanics(tensile_batch(3, bad_last=True))
    result = node.build_table()
    assert len(result) == 802
    assert set(result["batch_item_id"]) == {"sample-0", "sample-1"}
    assert set(result["batch_label"]) == {"试样0", "试样1"}


def test_batch_plot_files_are_separate_even_when_overwrite_is_enabled(tmp_path):
    packet = mechanics(tensile_batch(2)).build_report()
    node = component_class("viz.mechanics")().set(
        ui_mode="form",
        input_data=packet,
        cfg_x="strain_fraction",
        cfg_y="stress_MPa",
        cfg_sample="batch_item_id",
        cfg_data_kind="synthetic",
        cfg_output_dir=str(tmp_path),
    )
    result = node.build_report().data
    assert result["counts"]["completed"] == 2
    files = [path for item in result["items"] for path in item["report"]["artifacts"]]
    assert len(files) >= 2 and len(files) == len(set(files))
    assert all(Path(path).is_file() for path in files)
    assert all(item["table"] is None for item in result["items"])
    assert node.build_report().data["artifacts"] == result["artifacts"]


def test_single_item_execution_stays_compatible():
    node = component_class("materials.mechanics")().set(
        input_table=pd.read_csv(ROOT / "examples/science/materials/fixtures/synthetic_tensile.csv"),
        ui_mode="form",
        cfg_fit_range_min=0,
        cfg_fit_range_max=0.0008,
    )
    assert node.build_report().data["data"]["elastic_modulus_MPa"] == pytest.approx(200000)

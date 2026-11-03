"""Batch QA preserves measurements and the collector retains failed specimens."""

import pandas as pd

from materials_quality.batch.packet import make_batch, make_item, unpack_table


def test_batch_quality_is_shared_but_bound_to_each_whole_sample():
    from materials_quality.batch.quality import quality_batch

    frames = [pd.DataFrame({"value": [1.0, 2.0]}), pd.DataFrame({"value": [1.0, None]})]
    packet = make_batch([make_item(str(i), str(i), {}, table=f) for i, f in enumerate(frames)])
    output = quality_batch(packet, {"checks": {"missing": {"columns": ["value"]}}})
    assert output["counts"]["completed"] == 2
    assert output["counts"]["needs_review"] == 1
    for before, item in zip(frames, output["items"], strict=True):
        pd.testing.assert_frame_equal(unpack_table(item["table"]), before)
    reports = [item["quality"] for item in output["items"]]
    assert [r["total_findings"] for r in reports] == [0, 1]
    assert reports[0]["provenance"]["dataset_fingerprint"] != reports[1]["provenance"]["dataset_fingerprint"]


def test_quality_skip_is_opt_in_and_original_packet_is_unchanged():
    from materials_quality.batch.quality import quality_batch

    packet = make_batch([make_item("a", "a", {}, table=pd.DataFrame({"x": [None]}))])
    result = quality_batch(packet, {"checks": {"missing": {}}}, skip_on_issues=True)
    assert result["items"][0]["status"] == "skipped"
    assert packet["items"][0]["status"] == "completed"


def test_collector_keeps_failures_metrics_features_history_and_html(tmp_path):
    from materials_quality.batch.summary import summarize_batch

    good = make_item(
        "good",
        "样品甲",
        {},
        table=pd.DataFrame({"x": [1, 2]}),
        report={"operation": "materials.mechanics", "data": {"elastic_modulus_MPa": 200000}},
    )
    bad = make_item("bad", "样品乙", {})
    bad.update(status="failed", error={"stage": "read", "message": "bad input"})
    result = summarize_batch(make_batch([good, bad]), {"output_dir": str(tmp_path)})
    assert list(result.table["batch_item_id"]) == ["good", "bad"]
    assert result.table.iloc[0]["elastic_modulus_MPa"] == 200000
    assert result.table.iloc[1]["error"] == "bad input"
    assert result.data["counts"]["failed"] == 1
    assert result.artifacts and all(__import__("pathlib").Path(p).is_file() for p in result.artifacts)
    assert "样品乙" in __import__("pathlib").Path(result.artifacts[0]).read_text(encoding="utf-8")


def test_native_batch_quality_default_form_and_collector():
    from lfx.schema import Data

    from components.materials_batch.batch_quality import MaterialBatchQuality
    from components.materials_batch.batch_summary import MaterialBatchSummary

    packet = make_batch([make_item("a", "a", {}, table=pd.DataFrame({"x": [1.0, None]}))])
    checked = MaterialBatchQuality().set(input_data=Data(data=packet), enabled_checks=["missing"])
    report = checked.build_batch()
    assert report.data["items"][0]["quality"]["total_findings"] == 1
    summary = MaterialBatchSummary().set(input_data=report)
    assert len(summary.build_table()) == 1


def test_metrics_cannot_overwrite_failed_identity_status_or_error():
    from materials_quality.batch.summary import summarize_batch

    item = make_item(
        "real-id",
        "real label",
        {},
        report={"data": {"status": "completed", "error": "", "batch_item_id": "wrong-id"}},
    )
    item.update(status="failed", error={"stage": "test", "message": "actual failure"})
    row = summarize_batch(make_batch([item])).table.iloc[0]
    assert row["batch_item_id"] == "real-id"
    assert row["status"] == "failed"
    assert row["error"] == "actual failure"


def test_summary_uses_latest_metric_without_overwriting_identity():
    from materials_quality.batch.summary import summarize_batch

    item = make_item("sample", "sample", {}, report={"data": {"modulus": 200}})
    item["history"] = [{"data": {"modulus": 100}}]
    assert summarize_batch(make_batch([item])).table.iloc[0]["modulus"] == 200

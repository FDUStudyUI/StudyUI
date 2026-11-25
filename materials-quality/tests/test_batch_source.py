import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from lfx.custom.eval import eval_custom_component_code
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.packet import unpack_table
from materials_quality.batch.source import files_batch, grouped_batch, source_batch, source_fingerprint


@pytest.fixture
def standalone_file_access(monkeypatch):
    from lfx.services.deps import get_settings_service

    # Scripted nodes have no authenticated graph; exercise the single-tenant SDK mode.
    monkeypatch.setattr(get_settings_service().settings, "restrict_local_file_access", False)


def test_file_source_retains_same_basename_identity_hash_and_raw_bytes(tmp_path):
    paths = [tmp_path / folder / "curve.csv" for folder in ("one", "two")]
    for i, path in enumerate(paths):
        path.parent.mkdir()
        path.write_bytes(f"strain,stress\n0,{i}\n".encode())
    packet = files_batch(paths + [tmp_path / "missing.csv"])
    assert len({item["id"] for item in packet["items"]}) == 3
    assert packet["counts"]["failed"] == 1
    assert packet["execution_status"] == "partial_failed"
    for item, path in zip(packet["items"][:2], paths, strict=True):
        assert item["table"] is None
        assert item["source"]["file_path"] == str(path.resolve())
        assert item["source"]["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_group_source_retains_complete_groups_order_ids_units_and_mapping():
    frame = pd.DataFrame({"id": ["002", "001", "002", "001"], "stress_old": [1, 3, 2, 4]})
    frame.attrs["units"] = {"stress_old": "MPa"}
    packet = grouped_batch(frame, "id", rename_columns={"stress_old": "stress"})
    assert [item["label"] for item in packet["items"]] == ["002", "001"]
    assert [unpack_table(item["table"])["stress"].tolist() for item in packet["items"]] == [[1, 2], [3, 4]]
    assert unpack_table(packet["items"][0]["table"]).attrs["units"] == {"stress": "MPa"}
    assert packet["rename_columns"] == {}
    assert frame.columns.tolist() == ["id", "stress_old"]


@pytest.mark.parametrize("ids", [["001", None], ["001", " "], [1, "1"]])
def test_group_source_rejects_missing_or_ambiguous_ids(ids):
    with pytest.raises(ValueError, match="sample|group|ambiguous|missing"):
        grouped_batch(pd.DataFrame({"id": ids, "x": [1, 2]}), "id")


def test_limits_error_policy_and_mapping_validation(tmp_path):
    path = tmp_path / "small.csv"
    path.write_text("id,x\n001,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_items|limit"):
        files_batch([path, path], max_items=1)
    packet = files_batch([path], max_bytes=1)
    assert packet["counts"]["failed"] == 1
    stopped = files_batch([tmp_path / "absent", path], on_error="stop")
    assert [item["status"] for item in stopped["items"]] == ["failed", "skipped"]
    with pytest.raises(ValueError, match="rename|collision"):
        grouped_batch(pd.DataFrame({"id": ["x"], "x": [1]}), "id", rename_columns={"x": "id"})
    with pytest.raises(ValueError, match="mode"):
        source_batch(source_mode="global")


def test_group_csv_uses_existing_importer_without_dropping_leading_zero_ids(tmp_path):
    path = tmp_path / "grouped.csv"
    path.write_text("id,x\n001,1\n002,3\n001,2\n", encoding="utf-8")
    packet = source_batch(source_mode="grouped", source_files=[str(path)], sample_column="id")
    assert [item["label"] for item in packet["items"]] == ["001", "002"]
    assert unpack_table(packet["items"][0]["table"])["x"].tolist() == [1, 2]


def test_native_source_outputs_share_identity_and_refresh_real_group_columns(
    tmp_path, standalone_file_access
):
    from components.materials_batch.batch_source import MaterialBatchInput

    path = tmp_path / "grouped.csv"
    path.write_text("sample,strain,stress\n001,0,0\n001,1,2\n", encoding="utf-8")
    node = MaterialBatchInput().set(source_mode="grouped", source_files=[str(path)], sample_column="sample")
    batch = node.build_batch()
    assert isinstance(batch, Data)
    assert isinstance(node.build_manifest(), DataFrame)
    assert isinstance(node.build_summary(), Message)
    assert node.build_batch().data["batch_id"] == batch.data["batch_id"]
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["source_files"]["list"] is True
    config = node.update_build_config(template, [str(path)], "source_files")
    assert config["sample_column"]["options"] == ["sample", "strain", "stress"]
    assert config["sample_column"]["combobox"] is True
    code = Path(__file__).resolve().parents[1] / "components/materials_batch/batch_source.py"
    assert eval_custom_component_code(code.read_text(encoding="utf-8"))().build_config is not None
    json.dumps(batch.data, allow_nan=False)


def test_native_uploaded_storage_key_is_resolved_before_reading(
    tmp_path, monkeypatch, standalone_file_access
):
    from components.materials_batch.batch_source import MaterialBatchInput

    path = tmp_path / "uploaded.csv"
    path.write_text("x\n1\n", encoding="utf-8")
    # The storage backend owns upload namespaces; isolate that external lookup.
    monkeypatch.setattr(MaterialBatchInput, "get_full_path", lambda self, value: str(path))
    node = MaterialBatchInput().set(source_files=["a596b31c-7769-4d25-ab28-320d46ee4488/uploaded.csv"])
    packet = node.build_batch().data
    assert packet["items"][0]["status"] == "completed"
    assert packet["items"][0]["source"]["file_path"] == str(path.resolve())


def test_repeated_native_upload_selection_does_not_duplicate_experiments(tmp_path, standalone_file_access):
    from components.materials_batch.batch_source import MaterialBatchInput

    path = tmp_path / "a.csv"
    path.write_text("x\n1\n")
    node = MaterialBatchInput().set(source_files=[str(path), str(path)])
    assert node.build_batch().data["counts"]["total"] == 1


def test_native_cache_invalidates_when_same_source_file_changes(tmp_path, standalone_file_access):
    from components.materials_batch.batch_source import MaterialBatchInput

    path = tmp_path / "source.csv"
    path.write_text("x\n1\n", encoding="utf-8")
    node = MaterialBatchInput().set(source_files=[str(path)])
    before = node.build_batch().data
    path.write_text("x\n2\n", encoding="utf-8")
    after = node.build_batch().data
    assert before["batch_id"] != after["batch_id"]
    assert before["items"][0]["source"]["source_sha256"] != after["items"][0]["source"]["source_sha256"]


def test_native_restricted_mode_rejects_unscoped_server_path(tmp_path, monkeypatch):
    from lfx.services.deps import get_settings_service
    from lfx.utils.file_path_security import LocalFileAccessError

    from components.materials_batch.batch_source import MaterialBatchInput

    monkeypatch.setattr(get_settings_service().settings, "restrict_local_file_access", True)
    path = tmp_path / "outside.csv"
    path.write_text("x\n1\n", encoding="utf-8")
    node = MaterialBatchInput().set(source_files=[str(path)])
    with pytest.raises(LocalFileAccessError):
        node.build_batch()


def test_default_group_limit_accepts_1360_complete_curves():
    frame = pd.DataFrame({"sample": [f"{i:04d}" for i in range(1360)] * 2, "x": [0] * 1360 + [1] * 1360})
    packet = grouped_batch(frame, "sample")
    assert packet["counts"]["completed"] == 1360
    assert unpack_table(packet["items"][-1]["table"])["x"].tolist() == [0, 1]


def test_live_signature_enforces_task_limit_before_reading_files(tmp_path):
    paths = [tmp_path / "one.csv", tmp_path / "two.csv"]
    for path in paths:
        path.write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_items|limit"):
        source_fingerprint({"source_mode": "files", "file_paths": [str(p) for p in paths], "max_items": 1})

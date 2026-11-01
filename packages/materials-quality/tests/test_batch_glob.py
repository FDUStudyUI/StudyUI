import pandas as pd
import pytest

from materials_quality.batch.source import source_batch


def test_glob_files_and_condition_from_parent_folder(tmp_path):
    for group in ("control", "treated"):
        folder = tmp_path / group
        folder.mkdir()
        pd.DataFrame({"x": [1], "y": [2]}).to_csv(folder / "sample SERS map.csv", index=False)
    result = source_batch(file_paths=[str(tmp_path / "*/*SERS map.csv")], group_from="parent")
    assert len(result["items"]) == 2
    assert {i["source"]["group"] for i in result["items"]} == {"control", "treated"}
    assert len({i["id"] for i in result["items"]}) == 2


def test_empty_glob_and_excessive_glob_are_clear_errors(tmp_path):
    with pytest.raises(ValueError, match="glob|匹配"):
        source_batch(file_paths=[str(tmp_path / "*.csv")])
    for i in range(3):
        (tmp_path / f"{i}.csv").write_text("x\n1\n")
    with pytest.raises(ValueError, match="limit|max_items"):
        source_batch(file_paths=[str(tmp_path / "*.csv")], max_items=2)

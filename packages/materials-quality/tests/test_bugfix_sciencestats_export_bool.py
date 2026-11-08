import pandas as pd

from materials_quality.science.visualization import export_table


def test_csv_export_roundtrips_nullable_boolean_columns():
    # pandas "boolean" extension dtype is produced by nullable/joined result tables.
    frame = pd.DataFrame(
        {
            "flag": pd.array([True, None, False], dtype="boolean"),
            "value": [1.0, 2.0, 3.0],
        }
    )
    result = export_table(frame, config={"format": "csv"})
    back = pd.read_csv(result.data["file_path"], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert back["flag"].tolist() == ["True", "", "False"]
    assert result.data["verified"] is True


def test_csv_export_roundtrips_plain_boolean_columns():
    frame = pd.DataFrame({"flag": [True, False, True], "value": [1.0, 2.0, 3.0]})
    result = export_table(frame, config={"format": "csv"})
    back = pd.read_csv(result.data["file_path"], dtype=str, keep_default_na=False, encoding="utf-8-sig")
    assert back["flag"].tolist() == ["True", "False", "True"]

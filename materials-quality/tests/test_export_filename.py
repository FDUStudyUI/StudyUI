from pathlib import Path

import pandas as pd
import pytest

from materials_quality.science.visualization import export_report, export_table


@pytest.mark.parametrize("format,suffix", [("csv", ".csv"), ("excel", ".xlsx")])
def test_export_adds_omitted_extension_and_preserves_values(tmp_path, format, suffix):
    frame = pd.DataFrame({"peak_position": [40.0], "sample_id": ["001"]})
    result = export_table(
        frame, config={"format": format, "filename": "peak_features", "output_dir": str(tmp_path)}
    )
    path = Path(result.data["file_path"])
    assert path.name == "peak_features" + suffix
    assert path.is_file()
    assert result.data["verified"] is True


def test_export_rejects_conflicting_explicit_extension(tmp_path):
    with pytest.raises(ValueError, match=".csv"):
        export_table(
            pd.DataFrame({"x": [1]}),
            config={"format": "csv", "filename": "result.xlsx", "output_dir": str(tmp_path)},
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("format,suffix", [("html", ".html"), ("markdown", ".md")])
def test_report_adds_omitted_extension(tmp_path, format, suffix):
    result = export_report(config={"format": format, "filename": "analysis", "output_dir": str(tmp_path)})
    assert Path(result.data["file_path"]).name == "analysis" + suffix
    assert result.data["verified"] is True

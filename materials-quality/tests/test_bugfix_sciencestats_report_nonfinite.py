from materials_quality.science.visualization import export_report


def test_html_report_tolerates_non_finite_numeric_result_payloads():
    data = {"results": {"metrics": {"r2": float("nan"), "rmse": 0.5}}, "warnings": ["w"]}
    result = export_report(None, config={"format": "html"}, data=data)
    assert result.data["verified"] is True
    content = open(result.data["file_path"], encoding="utf-8").read()
    assert "null" in content


def test_markdown_report_tolerates_non_finite_numeric_result_payloads():
    data = {"results": {"metrics": {"r2": float("-inf")}}, "parameters": {"alpha": float("nan")}}
    result = export_report(None, config={"format": "markdown"}, data=data)
    content = open(result.data["file_path"], encoding="utf-8").read()
    assert "null" in content

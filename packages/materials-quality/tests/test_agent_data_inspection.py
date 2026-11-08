import json

import pytest

from materials_quality.agent.data_inspection import authorized_file, inspect_file
from materials_quality.agent.harness import StudyUIAgent, _bounded_tool_content


def test_user_named_csv_reports_structure_without_numeric_rows(tmp_path):
    file = tmp_path / "measurements.csv"
    file.write_text("time;signal\n1.25;99.75\n2.5;98.5\n", encoding="utf-8")
    result = inspect_file(authorized_file(str(file), f"请分析 {file}"))
    assert result["delimiter"] == ";"
    assert result["rows"] == 3
    block = result["numeric_blocks"][0]
    assert (block["start_row"], block["end_row"], block["nonempty_numeric_cells_per_row"]) == (2, 3, 2)
    assert block["first_column_order"]["strictly_increasing"] is True
    assert [cell["label"] for cell in result["first_row_text_labels"]] == ["time", "signal"]
    assert "99.75" not in json.dumps(result)


def test_bam_lis_inspection_reports_sections_headers_units_and_row_counts_only(tmp_path):
    file = tmp_path / "Tensile_A_02.lis"
    file.write_bytes(
        (
            "BAM 5.2 Prüfung\r\n"
            "[Daten]\r\n"
            "Zeit\tWeg\tKraft\tDehnung\tSpannung\r\n"
            "sec\tmm\tkN\t%\tMPa\r\n"
            "0,10\t0,00\t0,00\t0,000\t0,0\r\n"
            "0,20\t0,01\t0,25\t0,001\t12,34\r\n"
            "0,30\t0,02\t0,50\t0,002\t24,68\r\n"
        ).encode("cp1252")
    )

    result = inspect_file(authorized_file(str(file), f"研究 {file}"))

    assert result["format"] == ".lis"
    assert result["encoding"] == "cp1252"
    assert result["delimiter"] == "\t"
    section = result["table_sections"][0]
    assert section["section"] == "Daten"
    assert section["headers"] == ["Zeit", "Weg", "Kraft", "Dehnung", "Spannung"]
    assert section["units"] == ["sec", "mm", "kN", "%", "MPa"]
    assert section["data_rows"] == 3
    assert section["first_column_order"]["strictly_increasing"] is True
    serialized = json.dumps(result, ensure_ascii=False)
    assert "12,34" not in serialized
    assert "24,68" not in serialized


def test_numeric_block_reports_nonmonotonic_order_without_values(tmp_path):
    file = tmp_path / "series.csv"
    file.write_text("x,y\n1.25,9.75\n1.25,8.75\n0.5,7.75\n", encoding="utf-8")
    result = inspect_file(file)
    order = result["numeric_blocks"][0]["first_column_order"]
    assert order == {
        "checked_rows": 3,
        "strictly_increasing": False,
        "strictly_decreasing": False,
        "adjacent_equal_count": 1,
    }
    assert "9.75" not in json.dumps(result)


def test_inspection_rejects_unmentioned_and_non_data_files(tmp_path):
    file = tmp_path / "private.csv"
    file.write_text("x,y\n1,2\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        authorized_file(str(file), "分析另一个文件")
    with pytest.raises(PermissionError):
        authorized_file(str(file), f"分析 {file}.backup")
    secret = tmp_path / "secret.key"
    secret.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError):
        authorized_file(str(secret), f"请分析 {secret}")


def test_mixed_first_measurement_row_does_not_expose_text_identifiers(tmp_path):
    file = tmp_path / "raw.csv"
    file.write_text("private-sample;1.5\nother-sample;2.5\n", encoding="utf-8")
    result = inspect_file(authorized_file(str(file), f"分析 {file}"))
    assert result["first_row_text_labels"] == []
    assert "private-sample" not in json.dumps(result)


def test_workbook_inspection_reports_sheet_metadata_and_hash(tmp_path):
    import openpyxl

    file = tmp_path / "raw.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "DSC"
    sheet.append(["temperature", "heat flow"])
    sheet.append([20, 0.125])
    book.save(file)
    result = inspect_file(authorized_file(str(file), f"研究 {file}"))
    assert len(result["sha256"]) == 64
    assert result["sheets"][0]["name"] == "DSC"
    assert result["sheets"][0]["rows"] == 2
    assert "0.125" not in json.dumps(result)


def test_sparse_group_labels_are_reported_without_measurements(tmp_path):
    import openpyxl

    file = tmp_path / "groups.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["group", "strength"])
    sheet.append(["grade", "MPa"])
    for i in range(300):
        sheet.append([f"G{i // 100}" if i % 100 == 0 else None, i + 0.25])
    book.save(file)
    info = inspect_file(authorized_file(str(file), f"分析 {file}"))
    sparse = info["sheets"][0]["sparse_text_columns_after_first_two_rows"]
    assert sparse == [{"column": 1, "nonempty_text_cells": 3, "rows": [3, 103, 203], "uniform_spacing": 100}]
    assert "299.25" not in json.dumps(info)


def test_adjacent_numeric_pair_coverage_is_metadata_not_measurement_values(tmp_path):
    import openpyxl

    file = tmp_path / "curves.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["temperature", "heat flow"])
    sheet.append([20, None])
    sheet.append([30, 0.1234])
    sheet.append([40, 0.2345])
    book.save(file)
    pair = inspect_file(authorized_file(str(file), f"分析 {file}"))["sheets"][0]["adjacent_numeric_pairs"][0]
    assert pair["columns"] == [1, 2]
    assert pair["first_row"] == 3 and pair["last_row"] == 4
    assert pair["paired_finite_rows"] == 2 and pair["contiguous"] is True
    assert "0.1234" not in json.dumps(pair)


def test_inspector_is_registered_read_only_and_project_scoped(tmp_path):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=object(), model=object())
    project = agent.store.create_project("research")
    project_files = tmp_path / "project-files"
    project_files.mkdir()
    agent.store.add_project_directory(project, project_files)
    session = agent.new_session(project_id=project)
    file = project_files / "raw.csv"
    file.write_text("x,y\n1,2\n", encoding="utf-8")
    decision = agent._authorize_tool(session, "inspect_research_file", {"path": str(file)}, f"读取 {file}")
    assert decision["allowed"] and decision["action"] == "data.inspect"
    assert agent._authorize_tool(
        session, "inspect_research_file", {"path": str(file)}, "继续检查已授权项目文件"
    )["allowed"]
    outside = tmp_path / "outside.csv"
    outside.write_text("x,y\n1,2\n", encoding="utf-8")
    with pytest.raises(PermissionError):
        agent._authorize_tool(session, "inspect_research_file", {"path": str(outside)}, f"读取 {file}")
    assert (
        json.loads(
            _bounded_tool_content(
                "inspect_research_file",
                agent._dispatch(session, "inspect_research_file", {"path": str(file)}, f"读取 {file}"),
            )
        )["name"]
        == "raw.csv"
    )


def test_file_authorization_persists_in_session_and_respects_revocation(tmp_path):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=object(), model=object())
    project = agent.store.create_project("research")
    project_files = tmp_path / "project-files"
    project_files.mkdir()
    agent.store.add_project_directory(project, project_files)
    session = agent.new_session(project_id=project)
    file = project_files / "raw.csv"
    file.write_text("x,y\n1,2\n", encoding="utf-8")
    agent.store.append_message(session, {"role": "user", "content": f"请分析 {file}"})
    assert (
        agent._dispatch(session, "inspect_research_file", {"path": str(file)}, "继续分析")["name"]
        == "raw.csv"
    )
    agent.store.append_message(session, {"role": "user", "content": "禁止读取任何文件"})
    with pytest.raises(PermissionError):
        agent._dispatch(session, "inspect_research_file", {"path": str(file)}, "继续")


def test_skill_discovery_falls_back_to_available_skills(tmp_path):
    agent = StudyUIAgent(tmp_path / "agent.sqlite3", langflow=object(), model=object())
    project = agent.store.create_project("research")
    session = agent.new_session(project_id=project)
    result = agent._dispatch(
        session, "list_research_skills", {"task": "unmatched unique research phrase"}, ""
    )
    assert result["query_matched"] is False
    assert result["skills"]
    assert all(skill["enabled"] for skill in result["skills"])

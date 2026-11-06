import copy
import json
from pathlib import Path

import pytest

from materials_quality.agent.data_inspection import (
    audit_standards_and_dimensions,
    authorized_file,
    inspect_file,
)
from materials_quality.agent.workflow import _port, apply_actions, validate_flow_connections


@pytest.mark.parametrize("filename", ["tensile.csv", "battery.csv", "empty.csv"])
def test_filename_cannot_verify_compliance(filename):
    result = audit_standards_and_dimensions(Path(filename), [], None)
    assert result["compliance_status"] == "not_verified"
    assert result["compliance_passed"] is None
    assert all(check["status"] == "not_verified" for check in result["checks"])
    assert all(check["scope"] and "evidence" in check for check in result["checks"])


@pytest.mark.parametrize(("values", "status"), [((2, 1), "failed"), ((1, 2), "passed")])
def test_only_measured_numeric_block_order_is_verified(tmp_path, values, status):
    file = tmp_path / "xrd.csv"
    file.write_text(f"2theta,intensity\n{values[0]},9\n{values[1]},8\n", encoding="utf-8")
    result = inspect_file(file)["standards_and_compliance"]
    order = next(check for check in result["checks"] if check["id"] == "first_column_increasing")
    assert order["status"] == status
    assert order["evidence"]["checked_rows"] == 2
    assert order["scope"] == {"start_row": 2, "end_row": 3, "column": 1}
    assert result["compliance_passed"] is None


def test_same_basename_and_path_suffix_cannot_authorize_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    approved = tmp_path / "approved"
    approved.mkdir()
    file = approved / "sample.csv"
    file.touch()
    (tmp_path / "sample.csv").touch()
    assert authorized_file(str(file), "Analyze approved/sample.csv.") == file
    assert authorized_file("sample.csv", "Analyze sample.csv.") == tmp_path / "sample.csv"
    assert authorized_file(str(file), 'Use "approved/sample.csv" to build a workflow') == file
    for text in (
        "Analyze sample.csv.",
        f"Analyze {tmp_path / 'sample.csv'}.",
        "Analyze unapproved/sample.csv.",
        f"Analyze {file}:stream",
        "Analyze different approved/sample.csv.",
        'Analyze "different approved/sample.csv".',
        f'Analyze "{file} backup.csv"',
    ):
        with pytest.raises(PermissionError):
            authorized_file(str(file), text)


SOURCE = {
    "outputs": [
        {"name": "table", "types": ["DataFrame"], "display_name": "Curve Data"},
        {"name": "features", "types": ["DataFrame"], "display_name": "Feature Data"},
    ]
}
TARGET = {
    "template": {
        "input_table": {"input_types": ["DataFrame"], "display_name": "Import Table"},
        "configuration": {"type": "str"},
    }
}


@pytest.mark.parametrize("name", ["df", "dataframe", "data_table"])
def test_aliases_depend_on_direction(name):
    assert _port(SOURCE, name, True) == ("table", ["DataFrame"])
    assert _port(TARGET, name, False) == ("input_table", ["DataFrame"])


def test_ports_require_exact_or_unique_declared_match():
    assert _port(SOURCE, "Curve Data", True) == ("table", ["DataFrame"])
    assert _port(TARGET, "Import Table", False) == ("input_table", ["DataFrame"])
    with pytest.raises(ValueError, match="Unknown component input"):
        _port(TARGET, "invented", False)
    with pytest.raises(ValueError, match="Unknown component output"):
        _port({"outputs": SOURCE["outputs"][:1]}, "features", True)
    duplicate_display = {
        "outputs": [
            SOURCE["outputs"][0],
            {
                **SOURCE["outputs"][1],
                "display_name": "Curve Data",
            },
        ]
    }
    with pytest.raises(ValueError, match="Ambiguous.*features.*table"):
        _port(duplicate_display, "Curve Data", True)


def test_serialized_edges_require_canonical_handles():
    source_handle = {"id": "src", "name": "table"}
    target_handle = {"id": "dst", "fieldName": "input_table"}
    edge = {
        "source": "src",
        "target": "dst",
        "sourceHandle": json.dumps(source_handle),
        "targetHandle": json.dumps(target_handle),
        "data": {"sourceHandle": source_handle, "targetHandle": target_handle},
    }
    flow = {
        "data": {
            "nodes": [
                {"id": "src", "data": {"node": SOURCE}},
                {"id": "dst", "data": {"node": TARGET}},
            ],
            "edges": [edge],
        }
    }
    validate_flow_connections(flow)
    edge["sourceHandle"] = json.dumps({**source_handle, "name": "df"})
    with pytest.raises(ValueError, match="canonical"):
        validate_flow_connections(flow)


def test_new_connection_serializes_canonical_ports_and_records_aliases():
    flow = {
        "data": {
            "nodes": [
                {"id": "src", "data": {"node": SOURCE}},
                {"id": "dst", "data": {"node": TARGET}},
            ],
            "edges": [],
        }
    }
    action = {"op": "connect", "source": "src", "target": "dst", "output": "df", "input": "Import Table"}
    candidate, changes = apply_actions(flow, [action], {})
    validate_flow_connections(candidate)
    edge = candidate["data"]["edges"][0]
    assert json.loads(edge["sourceHandle"])["name"] == "table"
    assert json.loads(edge["targetHandle"])["fieldName"] == "input_table"
    assert "src.table" in changes[0] and "dst.input_table" in changes[0]
    assert "df" in changes[0] and "Import Table" in changes[0]
    assert flow["data"]["edges"] == []

    wrong_type = copy.deepcopy(flow)
    wrong_type["data"]["nodes"][1]["data"]["node"]["template"]["input_table"]["input_types"] = ["Message"]
    with pytest.raises(ValueError, match="incompatible"):
        apply_actions(wrong_type, [action], {})

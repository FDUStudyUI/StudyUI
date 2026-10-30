"""Aggregate verified report envelopes without asking a language model to count."""

from copy import deepcopy

from materials_quality.common import FINDING_COLUMNS, validate_limit


def _count(value):
    return type(value) is int and value >= 0


def _validate_report(report):
    required = {
        "check_id",
        "execution_status",
        "passed",
        "metrics",
        "dataset",
        "parameters",
        "total_findings",
        "returned_findings",
        "truncated",
        "findings",
    }
    if not isinstance(report, dict) or report.get("schema_version") != "1.0" or not required <= report.keys():
        raise ValueError("invalid quality report: expected schema_version 1.0 and complete report fields")
    if report["execution_status"] != "completed" or not isinstance(report["passed"], bool):
        raise ValueError("cannot aggregate an uncompleted or malformed check as a completed result")
    dataset = report["dataset"]
    if (
        not isinstance(dataset, dict)
        or not {"rows", "columns"} <= dataset.keys()
        or not all(_count(dataset[k]) for k in ("rows", "columns"))
    ):
        raise ValueError("invalid dataset dimensions")
    if not isinstance(report["metrics"], dict) or not isinstance(report["parameters"], dict):
        raise ValueError("metrics and parameters must be objects")
    if not isinstance(report["check_id"], str) or not report["check_id"]:
        raise ValueError("check_id must identify a completed check")
    total, returned = report["total_findings"], report["returned_findings"]
    findings = report["findings"]
    if (
        not _count(total)
        or not _count(returned)
        or not isinstance(findings, list)
        or returned != len(findings)
        or returned > total
        or (total > 0 and returned == 0)
    ):
        raise ValueError("finding counts are inconsistent")
    if type(report["truncated"]) is not bool or report["truncated"] != (total > returned):
        raise ValueError("truncated flag contradicts finding counts")
    # These six v1 checks emit warning/error findings only; no hidden failures
    # may be reclassified by changing a single boolean on a Data object.
    expected_pass = total == 0 and dataset["rows"] > 0 and dataset["columns"] > 0
    if report["passed"] != expected_pass:
        raise ValueError("passed flag contradicts findings or empty dataset")
    for finding in findings:
        if not isinstance(finding, dict) or not set(FINDING_COLUMNS) <= finding.keys():
            raise ValueError("malformed finding")
        if finding["check_id"] != report["check_id"] or finding["severity"] not in {"warning", "error"}:
            raise ValueError("finding identity or severity is inconsistent")
        if not isinstance(finding["code"], str) or not isinstance(finding["reason"], str):
            raise ValueError("finding code and reason must be strings")
        position = finding["row_position"]
        if position is not None and (not _count(position) or position >= dataset["rows"]):
            raise ValueError("finding row_position is outside the dataset")


def aggregate_reports(reports, *, finding_limit=500):
    validate_limit(finding_limit)
    if not isinstance(reports, list):
        raise ValueError("reports must be a list of quality report objects")
    for report in reports:
        _validate_report(report)
    total = sum(r["total_findings"] for r in reports)
    findings = [f for r in reports for f in r["findings"]][:finding_limit]
    failed = sum(not r["passed"] for r in reports)
    return deepcopy(
        {
            "schema_version": "1.0",
            "check_id": "aggregate",
            "execution_status": "completed" if reports else "insufficient",
            "passed": bool(reports) and failed == 0,
            "dataset": {},
            "parameters": {"finding_limit": finding_limit},
            "metrics": {
                "completed_checks": len(reports),
                "failed_checks": failed,
                "passed_checks": len(reports) - failed,
            },
            "total_findings": total,
            "returned_findings": len(findings),
            "truncated": total > len(findings),
            "findings": findings,
            "checks": reports,
        }
    )

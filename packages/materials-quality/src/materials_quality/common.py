"""Shared validation and JSON-safe reporting; no Langflow dependency."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from numbers import Integral, Number

import numpy as np
import pandas as pd
from pandas.api.types import is_scalar

FINDING_COLUMNS = ["check_id", "code", "severity", "column", "row_position", "row_index", "reason"]


def missing(value, tokens=("",)) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if is_scalar(value) and not isinstance(value, str):
        try:
            if bool(pd.isna(value)):
                return True
        except (TypeError, ValueError):
            return False
    if isinstance(value, str):
        return value.strip() in tokens
    if isinstance(value, Number) and not isinstance(value, (bool, np.bool_)):
        for token in tokens:
            if not token:
                continue
            try:
                if numeric(value) == numeric(token):
                    return True
            except (ValueError, ArithmeticError):
                continue
    return False


def json_value(value):
    if missing(value, ()):
        return None
    if isinstance(value, Mapping):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [json_value(v) for v in value]
    if isinstance(value, np.generic):
        return json_value(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def validate_table(table: pd.DataFrame):
    if not isinstance(table, pd.DataFrame):
        raise ValueError("table must be a pandas/Langflow DataFrame")
    if not table.columns.is_unique:
        raise ValueError("duplicate column names are ambiguous; fix the table header first")
    if any(not isinstance(c, str) or not c.strip() for c in table.columns):
        raise ValueError("column names must be non-empty strings")


def select_columns(table, columns=None):
    selected = list(table.columns) if columns is None else columns
    if not isinstance(selected, (list, tuple)) or not selected:
        raise ValueError("columns must be a non-empty list")
    if any(not isinstance(c, str) for c in selected) or len(set(selected)) != len(selected):
        raise ValueError("columns must contain unique string names")
    unknown = [c for c in selected if c not in table.columns]
    if unknown:
        raise ValueError(f"unknown columns: {unknown}")
    return list(selected)


def validate_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, Integral) or not 1 <= limit <= 10000:
        raise ValueError("finding_limit must be an integer between 1 and 10000")


def numeric(value):
    """Use Decimal to avoid rounding large integers during type validation."""
    if isinstance(value, (bool, np.bool_)) or not is_scalar(value):
        raise ValueError("not a number")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("not a number") from exc
    if not result.is_finite():
        raise ArithmeticError("non-finite number")
    return result


def groups(table, group_by=None):
    if not group_by:
        yield {}, np.arange(len(table))
        return
    names = select_columns(table, group_by)
    # .indices are positions, unlike .groups, whose labels may not be unique.
    for key, positions in table.groupby(names, dropna=False, sort=False, observed=True).indices.items():
        key = key if isinstance(key, tuple) else (key,)
        yield dict(zip(names, (json_value(v) for v in key), strict=True)), positions


class ReportBuilder:
    def __init__(self, table, check_id, parameters, finding_limit=500):
        validate_table(table)
        validate_limit(finding_limit)
        self.table = table
        self.check_id = check_id
        self.parameters = parameters
        self.limit = int(finding_limit)
        self.findings = []
        self.total = 0
        self.problems = 0
        if len(table) == 0:
            self.add("EMPTY_TABLE", "warning", reason="No rows are available for this check.")
        if len(table.columns) == 0:
            self.add("EMPTY_SCHEMA", "warning", reason="No columns are available for this check.")

    def add(self, code, severity="warning", *, column=None, position=None, reason=""):
        self.total += 1
        self.problems += severity in {"warning", "error"}
        if len(self.findings) < self.limit:
            self.findings.append(
                {
                    "check_id": self.check_id,
                    "code": code,
                    "severity": severity,
                    "column": column,
                    "row_position": int(position) if position is not None else None,
                    "row_index": json_value(self.table.index[position]) if position is not None else None,
                    "reason": reason,
                }
            )

    def finish(self, metrics=None):
        return json_value(
            {
                "schema_version": "1.0",
                "check_id": self.check_id,
                "execution_status": "completed",
                "passed": self.problems == 0,
                "dataset": {"rows": len(self.table), "columns": len(self.table.columns)},
                "parameters": self.parameters,
                "metrics": metrics or {},
                "total_findings": self.total,
                "returned_findings": len(self.findings),
                "truncated": self.total > len(self.findings),
                "findings": self.findings,
            }
        )

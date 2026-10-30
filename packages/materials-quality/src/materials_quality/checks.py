"""Schema, missingness, type/format and duplicate checks."""

from collections import Counter
from datetime import datetime

import numpy as np

from materials_quality.common import ReportBuilder, groups, missing, numeric, select_columns


def check_schema(table, *, required_columns, aliases=None, finding_limit=500):
    report = ReportBuilder(
        table, "schema", {"required_columns": required_columns, "aliases": aliases or {}}, finding_limit
    )
    if not isinstance(required_columns, list) or not required_columns:
        raise ValueError("required_columns must be a non-empty list")
    if any(not isinstance(c, str) or not c.strip() for c in required_columns):
        raise ValueError("required column names must be non-empty strings")
    if len(set(required_columns)) != len(required_columns):
        raise ValueError("required_columns must be unique")
    aliases = aliases or {}
    if not isinstance(aliases, dict):
        raise ValueError("aliases must be an object mapping canonical names to lists")
    for name, values in aliases.items():
        if name not in required_columns or not isinstance(values, list):
            raise ValueError("alias keys must be required columns and values must be lists")
        if any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError("aliases must be non-empty strings")
    alias_owner = {}
    for canonical in required_columns:
        for candidate in [canonical, *aliases.get(canonical, [])]:
            if candidate in alias_owner and alias_owner[candidate] != canonical:
                raise ValueError(f"alias {candidate!r} is assigned to multiple required fields")
            alias_owner[candidate] = canonical
    resolved = {}
    for canonical in required_columns:
        candidates = list(dict.fromkeys([canonical, *aliases.get(canonical, [])]))
        found = [c for c in candidates if c in table.columns]
        if not found:
            report.add(
                "MISSING_COLUMN",
                "error",
                column=canonical,
                reason=f"Required field {canonical!r} is missing.",
            )
        elif len(found) > 1:
            report.add(
                "AMBIGUOUS_COLUMN", "error", column=canonical, reason=f"Multiple matching fields: {found!r}."
            )
        else:
            resolved[canonical] = found[0]
    return report.finish({"resolved_columns": resolved})


def check_missing(table, *, columns=None, missing_tokens=None, group_by=None, finding_limit=500):
    tokens = [""] if missing_tokens is None else missing_tokens
    report = ReportBuilder(
        table, "missing", {"columns": columns, "missing_tokens": tokens, "group_by": group_by}, finding_limit
    )
    selected = select_columns(table, columns)
    if not isinstance(tokens, list) or any(not isinstance(t, str) for t in tokens):
        raise ValueError("missing_tokens must be a list of strings")
    tokens = tuple(t.strip() for t in tokens)
    mask = np.array([[missing(v, tokens) for v in table[c]] for c in selected], dtype=bool).T
    if len(table) == 0:
        mask = np.empty((0, len(selected)), dtype=bool)
    by_column = {}
    for j, column in enumerate(selected):
        count = int(mask[:, j].sum())
        by_column[column] = {
            "missing_count": count,
            "missing_ratio": count / len(table) if len(table) else None,
        }
    patterns = Counter()
    per_row = []
    for i in range(len(table)):
        fields = [c for j, c in enumerate(selected) if mask[i, j]]
        if fields:
            patterns[tuple(fields)] += 1
            per_row.append({"row_position": i, "missing_count": len(fields)})
            for column in fields:
                report.add(
                    "MISSING_VALUE",
                    column=column,
                    position=i,
                    reason="Null or explicitly configured missing token.",
                )
    grouped = []
    if group_by:
        for key, positions in groups(table, group_by):
            grouped.append(
                {
                    "group": key,
                    "row_count": len(positions),
                    "columns": {
                        column: {
                            "missing_count": int(mask[positions, j].sum()),
                            "missing_ratio": int(mask[positions, j].sum()) / len(positions),
                        }
                        for j, column in enumerate(selected)
                    },
                }
            )
    return report.finish(
        {
            "columns": by_column,
            "affected_rows": len(per_row),
            "rows": per_row,
            "patterns": [{"columns": list(k), "row_count": v} for k, v in patterns.items()],
            "groups": grouped,
        }
    )


def _type_rule(spec):
    rule = {"type": spec} if isinstance(spec, str) else spec
    if not isinstance(rule, dict) or rule.get("type") not in {
        "number",
        "integer",
        "string",
        "boolean",
        "datetime",
        "category",
    }:
        raise ValueError(f"unsupported type rule: {spec!r}")
    kind = rule["type"]
    if kind == "datetime" and (not isinstance(rule.get("format"), str) or not rule["format"]):
        raise ValueError("datetime rules require an explicit format")
    if kind == "category" and (not isinstance(rule.get("allowed"), list) or not rule["allowed"]):
        raise ValueError("category rules require a non-empty allowed list")
    return rule


def _matches(value, rule):
    kind = rule["type"]
    if kind in {"number", "integer"}:
        try:
            number = numeric(value)
        except (ValueError, ArithmeticError):
            return False
        return kind == "number" or number == number.to_integral_value()
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, (bool, np.bool_)) or (
            isinstance(value, str) and value.strip().lower() in {"true", "false"}
        )
    if kind == "datetime":
        if not isinstance(value, str):
            return False
        try:
            parsed = datetime.strptime(value, rule["format"])
            return parsed.strftime(rule["format"]) == value
        except ValueError:
            return False
    try:
        return bool(value in rule["allowed"])
    except (TypeError, ValueError):
        return False


def check_types(table, *, expectations, finding_limit=500):
    report = ReportBuilder(table, "types", {"expectations": expectations}, finding_limit)
    if not isinstance(expectations, dict) or not expectations:
        raise ValueError("expectations must be a non-empty object")
    selected = select_columns(table, list(expectations))
    rules = {column: _type_rule(expectations[column]) for column in selected}
    metrics = {}
    for column in selected:
        checked = invalid = 0
        for position, value in enumerate(table[column]):
            if missing(value):
                continue
            checked += 1
            if not _matches(value, rules[column]):
                invalid += 1
                report.add(
                    "TYPE_OR_FORMAT",
                    "error",
                    column=column,
                    position=position,
                    reason=f"Value does not satisfy {rules[column]!r}.",
                )
        metrics[column] = {
            "expected_type": rules[column]["type"],
            "checked_count": checked,
            "invalid_count": invalid,
            "missing_count": len(table) - checked,
            "observed_python_types": sorted({type(v).__name__ for v in table[column] if not missing(v)}),
        }
    return report.finish({"columns": metrics})


def check_duplicates(table, *, columns=None, finding_limit=500):
    report = ReportBuilder(table, "duplicates", {"columns": columns}, finding_limit)
    selected = select_columns(table, columns)
    try:
        mask = table.duplicated(subset=selected, keep=False).to_numpy()
        duplicate_groups = len(table.loc[mask, selected].drop_duplicates())
    except TypeError as exc:
        raise ValueError("duplicate checking requires scalar/hashable cell values") from exc
    for position in np.flatnonzero(mask):
        report.add(
            "DUPLICATE_RECORD",
            position=position,
            reason=f"Repeated combination of {selected!r}; review whether this is a valid replicate.",
        )
    return report.finish(
        {
            "duplicate_rows": int(mask.sum()),
            "duplicate_groups": duplicate_groups,
            "key_columns": selected,
            "duplicate_ratio": float(mask.mean()) if len(mask) else None,
        }
    )

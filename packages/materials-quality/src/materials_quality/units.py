"""Explicit dimensional checks; this module never guesses or converts stored values."""

import re

import pint

from materials_quality.common import ReportBuilder, missing, numeric, select_columns
from materials_quality.common import missing_tokens as normalize_missing_tokens

_REGISTRY = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
_ALIASES = {"℃": "degC", "°C": "degC", "摄氏度": "degC", "°F": "degF", "℉": "degF", "微米": "um"}
_QUANTITY = re.compile(r"^\s*([+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|inf|nan))\s*(.*?)\s*$", re.I)


def _unit(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("units must be non-empty strings")
    value = _ALIASES.get(text.strip(), text.strip())
    try:
        return _REGISTRY.Unit(value)
    except (pint.UndefinedUnitError, pint.DefinitionSyntaxError, ValueError, TypeError) as exc:
        raise ValueError(f"unknown or invalid unit: {text!r}") from exc


def check_units(table, *, source_units, expected_units, columns=None, finding_limit=500, missing_tokens=None):
    tokens = normalize_missing_tokens(missing_tokens)
    parameters = {"source_units": source_units, "expected_units": expected_units, "columns": columns}
    if missing_tokens is not None:
        parameters["missing_tokens"] = list(tokens)
    report = ReportBuilder(
        table,
        "units",
        parameters,
        finding_limit,
    )
    if not isinstance(source_units, dict) or not isinstance(expected_units, dict) or not expected_units:
        raise ValueError("source_units must be an object; expected_units must be a non-empty object")
    selected = select_columns(table, list(expected_units) if columns is None else columns)
    if any(c not in expected_units for c in selected):
        raise ValueError("every selected column requires an expected unit")
    if source_units:
        select_columns(table, list(source_units))
    expected = {c: _unit(v) for c, v in expected_units.items()}
    source = {c: _unit(v) for c, v in source_units.items()}
    metrics = {}
    for column in selected:
        target = expected[column]
        declared = source.get(column)
        compatible = True
        if declared is not None and declared.dimensionality != target.dimensionality:
            compatible = False
            report.add(
                "UNIT_INCOMPATIBLE",
                "error",
                column=column,
                reason=f"Declared {declared} is incompatible with expected {target}.",
            )
        seen = set()
        unspecified = 0
        checked = 0
        for position, value in enumerate(table[column]):
            if missing(value, tokens):
                continue
            match = _QUANTITY.fullmatch(value) if isinstance(value, str) else None
            unit_text = match.group(2) if match else ""
            magnitude = match.group(1) if match else value
            try:
                numeric(magnitude)
            except ArithmeticError:
                compatible = False
                report.add(
                    "NON_FINITE",
                    "error",
                    column=column,
                    position=position,
                    reason="Quantity magnitude is not finite.",
                )
                continue
            except ValueError:
                compatible = False
                report.add(
                    "UNIT_VALUE_FORMAT",
                    "error",
                    column=column,
                    position=position,
                    reason="Expected a number or an explicit quantity such as '1 MPa'.",
                )
                continue
            checked += 1
            if unit_text:
                try:
                    actual = _unit(unit_text)
                except ValueError:
                    compatible = False
                    report.add(
                        "UNIT_UNKNOWN",
                        "error",
                        column=column,
                        position=position,
                        reason=f"Unknown inline unit {unit_text!r}.",
                    )
                    continue
            else:
                actual = declared
            if actual is None:
                unspecified += 1
                compatible = False
                continue
            seen.add(str(actual))
            if actual.dimensionality != target.dimensionality:
                compatible = False
                report.add(
                    "UNIT_INCOMPATIBLE",
                    "error",
                    column=column,
                    position=position,
                    reason=f"Inline {actual} is incompatible with expected {target}.",
                )
        if unspecified:
            report.add(
                "UNIT_UNSPECIFIED",
                "warning",
                column=column,
                reason=(
                    f"{unspecified} numeric values have no declared source unit; units cannot be inferred."
                ),
            )
        if len(seen) > 1:
            report.add(
                "UNIT_MIXED",
                "warning",
                column=column,
                reason=f"Multiple source units in one column: {sorted(seen)!r}; values were not converted.",
            )
        metrics[column] = {
            "source_unit": str(declared) if declared is not None else None,
            "expected_unit": str(target),
            "observed_units": sorted(seen),
            "compatible": compatible,
            "checked_count": checked,
            "unspecified_count": unspecified,
        }
    return report.finish({"columns": metrics, "converted": False})

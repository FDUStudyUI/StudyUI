"""Template validation, conservative type suggestions and explicit similarity."""

import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from fractions import Fraction

import numpy as np
import pandas as pd

from materials_quality.common import json_value, missing, numeric, select_columns


def template_errors(table, template):
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    from referencing import Registry

    if not isinstance(template, dict):
        raise ValueError("schema_template must be a JSON Schema object")
    try:
        Draft202012Validator.check_schema(template)
    except SchemaError as exc:
        raise ValueError(f"invalid schema_template: {exc.message}") from exc

    def reject_external_refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"$ref", "$dynamicRef"} and isinstance(item, str) and not item.startswith("#"):
                    raise ValueError("schema_template permits only local references in $defs")
                reject_external_refs(item)
        elif isinstance(value, list):
            for item in value:
                reject_external_refs(item)

    reject_external_refs(template)
    validator = Draft202012Validator(template, registry=Registry())
    for position, record in enumerate(table.to_dict("records")):
        for error in sorted(validator.iter_errors(json_value(record)), key=lambda e: str(list(e.path))):
            path = list(error.path)
            column = path[0] if path and isinstance(path[0], str) else None
            yield position, column, f"JSON Schema path {path}: {error.message}"


def infer_expectations(table, tokens=("",), date_formats=None):
    formats = date_formats or ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]
    if not isinstance(formats, list) or any(not isinstance(f, str) or not f for f in formats):
        raise ValueError("date_formats must be a non-empty list of explicit date patterns")
    rules, unknown = {}, []
    for column in table:
        values = [v for v in table[column] if not missing(v, tokens)]
        if not values:
            unknown.append(column)
            continue
        if all(
            isinstance(v, (bool, np.bool_)) or isinstance(v, str) and v.lower() in {"true", "false"}
            for v in values
        ):
            rules[column] = {"type": "boolean"}
            continue
        try:
            numbers = [numeric(v) for v in values]
        except (ValueError, ArithmeticError):
            numbers = None
        if numbers is not None:
            kind = "integer" if all(v == v.to_integral_value() for v in numbers) else "number"
            rules[column] = {"type": kind}
            continue
        matched = None
        if all(isinstance(v, str) for v in values):
            for pattern in formats:
                try:
                    if all(datetime.strptime(v, pattern).strftime(pattern) == v for v in values):
                        matched = pattern
                        break
                except ValueError:
                    continue
        elif all(isinstance(v, (datetime, pd.Timestamp, np.datetime64)) for v in values):
            matched = "%Y-%m-%dT%H:%M:%S"
        if matched:
            rules[column] = {"type": "datetime", "format": matched}
        elif isinstance(table[column].dtype, pd.CategoricalDtype):
            rules[column] = {"type": "category", "allowed": json_value(list(table[column].cat.categories))}
        elif all(isinstance(v, str) for v in values):
            unique = list(dict.fromkeys(values))
            rules[column] = (
                {"type": "category", "allowed": unique}
                if len(unique) <= 20 and len(unique) <= len(values) / 2
                else {"type": "string"}
            )
        else:
            # Mixed scalar content cannot be safely guessed as a coherent type.
            unknown.append(column)
    return rules, unknown


def similar_pairs(table, columns, threshold, tolerances=None, max_pairs=100000):
    selected = select_columns(table, columns)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ValueError("similarity_threshold must be a number in (0,1]")
    if type(max_pairs) is not int or max_pairs < 1:
        raise ValueError("max_pairs must be a positive integer")
    if len(table) * (len(table) - 1) // 2 > max_pairs:
        raise ValueError("similar matching exceeds max_pairs; partition data or increase the budget")
    tolerances = tolerances or {}
    if not isinstance(tolerances, dict) or tolerances.keys() - set(selected):
        raise ValueError("numeric_tolerances must configure selected columns")
    limits = {}
    for column, rule in tolerances.items():
        if not isinstance(rule, dict) or rule.keys() - {"atol", "rtol"}:
            raise ValueError("numeric tolerance rules accept atol/rtol only")
        try:
            absolute, relative = (Fraction(numeric(rule.get(key, 0))) for key in ("atol", "rtol"))
        except (ValueError, ArithmeticError) as exc:
            raise ValueError("tolerances must be finite nonnegative numbers") from exc
        if absolute < 0 or relative < 0:
            raise ValueError("tolerances must be finite nonnegative numbers")
        limits[column] = (absolute, relative)
    records = list(table[selected].itertuples(index=False, name=None))
    for left in range(len(records)):
        for right in range(left + 1, len(records)):
            scores, exact = [], True
            for column, a, b in zip(selected, records[left], records[right], strict=True):
                if missing(a) or missing(b):
                    break
                exact &= a == b
                if column in limits:
                    try:
                        x, y = Fraction(numeric(a)), Fraction(numeric(b))
                    except (ValueError, ArithmeticError):
                        break
                    absolute, relative = limits[column]
                    scores.append(float(abs(x - y) <= max(absolute, relative * max(abs(x), abs(y)))))
                else:
                    x = unicodedata.normalize("NFKC", str(a)).strip().casefold()
                    y = unicodedata.normalize("NFKC", str(b)).strip().casefold()
                    scores.append(SequenceMatcher(None, x, y, autojunk=False).ratio())
            if len(scores) == len(selected) and not exact:
                score = sum(scores) / len(scores)
                if score >= threshold:
                    yield {"positions": [left, right], "score": score, "columns": selected}

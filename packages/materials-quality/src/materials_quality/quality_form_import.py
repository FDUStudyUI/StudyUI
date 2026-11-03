"""Lossless native-control imports for the eight original quality components.

Only installed controls and check signatures are inspected; saved Python is never
loaded. A failed round trip retains the original JSON inputs verbatim.
"""

import inspect
from copy import deepcopy

from .checks import _type_rule
from .context import CHECKS, _rules
from .quality_ui import JSON_COMMON_FIELDS, LEGACY_FIELDS, quality_parameters, shared_rules


def _equal(first, second):
    if (type(first) is bool) != (type(second) is bool):
        return False
    if isinstance(first, dict):
        return (
            isinstance(second, dict)
            and first.keys() == second.keys()
            and all(_equal(v, second[k]) for k, v in first.items())
        )
    if isinstance(first, list):
        return (
            isinstance(second, list)
            and len(first) == len(second)
            and all(_equal(a, b) for a, b in zip(first, second, strict=True))
        )
    return first == second


def _effective(check, parameters):
    bound = inspect.signature(CHECKS[check]).bind(None, **parameters)
    bound.apply_defaults()
    result = dict(bound.arguments)
    result.pop("table", None)
    result.pop("finding_limit", None)
    if isinstance(result.get("expectations"), dict):
        result["expectations"] = {c: _type_rule(v) for c, v in result["expectations"].items()}
    for name in ("aliases", "schema_template", "bounds", "numeric_tolerances"):
        if name in result and result[name] is None:
            result[name] = {}
    return result


def _settings(check, parameters):
    p = deepcopy(parameters)
    result = {}
    direct = {
        "missing": ("columns", "missing_tokens", "group_by"),
        "schema": ("required_columns",),
        "types": (),
        "units": ("columns", "convert_values"),
        "duplicates": ("numeric_tolerances",),
        "outliers": ("group_by",),
    }
    for name in direct[check]:
        if name in p:
            result[name] = [] if p[name] is None and name in {"columns", "group_by"} else p[name]
    if check == "schema":
        result["alias_rules"] = [
            {"column": c, "alias": a} for c, aliases in p.get("aliases", {}).items() for a in aliases
        ]
        schema = p.get("schema_template") or {}
        if schema and (schema.keys() - {"type", "properties"} or schema.get("type") != "object"):
            raise ValueError("schema has fields unsupported by the numeric constraint editor")
        rows = []
        for column, rule in schema.get("properties", {}).items():
            if rule.keys() - {"type", "minimum", "maximum"} or rule.get("type") != "number":
                raise ValueError("schema property cannot be represented by numeric constraints")
            rows.append(
                {
                    "column": column,
                    **{k: rule[v] for k, v in (("min", "minimum"), ("max", "maximum")) if v in rule},
                }
            )
        result["constraint_rules"] = rows
    elif check == "types":
        result["infer_types"] = p.get("infer", False)
        result["field_rules"] = [
            {"column": c, **_type_rule(v)} for c, v in (p.get("expectations") or {}).items()
        ]
    elif check == "units":
        source, expected = p.get("source_units") or {}, p.get("expected_units") or {}
        if source.keys() - expected.keys():
            raise ValueError("source-only unit rules cannot be represented")
        result["unit_rules"] = [
            {"column": c, "source_unit": source.get(c, ""), "expected_unit": u} for c, u in expected.items()
        ]
    elif check == "duplicates":
        result["duplicate_keys"] = p.get("columns") or []
        result["match_similar"] = p.get("similarity_threshold") is not None
        if result["match_similar"]:
            result["similarity_threshold"] = p["similarity_threshold"]
    elif check == "outliers":
        result.update(
            outlier_columns=p.get("columns") or [],
            detection_method=p.get("method", "iqr"),
            iqr_multiplier=p.get("multiplier", 1.5),
            mad_threshold=p.get("mad_threshold", 3.5),
        )
        result["constraint_rules"] = [
            {"column": c, **bounds} for c, bounds in (p.get("bounds") or {}).items()
        ]
    return result


def quality_to_form(component, saved):
    """Return ``(set_values, reason)``; JSON fallback keeps every saved field.

    Summary already uses native controls and returns an empty mapping. Shared
    check defaults are compared against actual algorithm signature defaults.
    """
    check = getattr(component, "quality_check", None)
    if check is None:
        return {}, None
    fallback = {"ui_mode": "json"}
    names = set(LEGACY_FIELDS[check]) | JSON_COMMON_FIELDS.get(check, set())
    legacy = {name: deepcopy(value) for name, value in saved.items() if name in names}
    fallback.update(legacy)
    try:
        component.set(ui_mode="json", **legacy)
        if check == "context":
            original = _rules(shared_rules(component))
            values = {
                "enabled_checks": list(original["checks"]),
                "missing_tokens": original["missing_tokens"],
                "group_by": original["group_by"],
            }
            for kind, parameters in original["checks"].items():
                settings = _settings(kind, parameters)
                for key, value in settings.items():
                    if key in values and not _equal(values[key], value):
                        raise ValueError(f"shared editor conflict: {key}")
                    values[key] = value
            component.set(ui_mode="form", **values)
            actual = _rules(shared_rules(component))
            if any(original[key] != actual[key] for key in ("missing_tokens", "group_by")):
                raise ValueError("shared markers/grouping changed")
            if any(
                not _equal(_effective(kind, parameters), _effective(kind, actual["checks"][kind]))
                for kind, parameters in original["checks"].items()
            ):
                raise ValueError("shared check parameters changed")
        else:
            original = quality_parameters(component, check)
            values = _settings(check, original)
            component.set(ui_mode="form", **values)
            actual = quality_parameters(component, check)
            # Unit component serializes its boolean controller as a dropdown.
            if check == "units":
                for parameters in (original, actual):
                    value = parameters["convert_values"]
                    parameters["convert_values"] = value is True or value == "是"
            if not _equal(_effective(check, original), _effective(check, actual)):
                raise ValueError("native controls change effective check parameters")
        return {"ui_mode": "form", **values}, None
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError) as exc:
        return fallback, str(exc)

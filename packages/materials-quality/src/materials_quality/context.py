"""Bind non-destructive checks to a frozen ruleset and typed table identity.

Hashes detect accidental edits; they are not signatures or file authenticity proof.
"""

import hashlib
import inspect
import json
import math
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from materials_quality.checks import check_duplicates, check_missing, check_schema, check_types
from materials_quality.common import json_value, validate_table
from materials_quality.outliers import check_outliers
from materials_quality.units import check_units

CHECKS = {"schema": check_schema, "missing": check_missing, "types": check_types,
          "units": check_units, "duplicates": check_duplicates, "outliers": check_outliers}
CONTEXT_SCHEMA = "materials-quality-context/1"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _typed(value):
    # .item() returns an int for ns temporal scalars; retain type and unit.
    if isinstance(value, (np.datetime64, np.timedelta64)):
        return [str(value.dtype), str(value.view("i8"))]
    if isinstance(value, pd.Timedelta):
        return ["pd.Timedelta", value.isoformat()]
    if isinstance(value, timedelta):
        return ["timedelta", value.days, value.seconds, value.microseconds]
    if isinstance(value, np.generic):
        value = value.item()
    if value is pd.NA:
        return ["pd.NA"]
    if value is pd.NaT:
        return ["pd.NaT"]
    if value is None:
        return ["null"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float", value.hex() if math.isfinite(value) else str(value)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, Decimal):
        return ["Decimal", str(value)]
    if isinstance(value, (list, tuple)):
        return [type(value).__name__, [_typed(v) for v in value]]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return ["dict", {k: _typed(v) for k, v in value.items()}]
    raise ValueError(f"unsupported value for reproducible table fingerprint: {type(value).__name__}")


def table_fingerprint(table):
    """Versioned streaming hash includes values, column order/dtypes and row index."""
    validate_table(table)
    digest = hashlib.sha256()
    header = ["materials-table/1", list(table.columns), [str(t) for t in table.dtypes],
              [_typed(n) for n in table.index.names]]
    digest.update((_json(header) + "\n").encode("utf-8"))
    for index, row in zip(table.index, table.itertuples(index=False, name=None), strict=True):
        digest.update((_json([_typed(index), [_typed(v) for v in row]]) + "\n").encode("utf-8"))
    return digest.hexdigest()


def _dataset(table):
    return {"rows": len(table), "columns": len(table.columns), "fingerprint": table_fingerprint(table)}


def _source(source):
    source = {} if source is None else deepcopy(source)
    allowed = {"dataset_id", "source_name", "source_sha256"}
    if not isinstance(source, dict) or source.keys() - allowed:
        raise ValueError("source: expected dataset_id, source_name and/or source_sha256")
    if any(not isinstance(v, str) or not v.strip() for v in source.values()):
        raise ValueError("source fields must be non-empty strings")
    if "source_sha256" in source and not _SHA.fullmatch(source["source_sha256"]):
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    return source


def _rules(rules):
    try:
        rules = json.loads(_json(rules))
    except (TypeError, ValueError) as exc:
        raise ValueError("rules must be strict JSON") from exc
    if not isinstance(rules, dict) or rules.keys() - {"missing_tokens", "group_by", "checks"}:
        raise ValueError("unknown shared rules field")
    rules.setdefault("missing_tokens", [""])
    rules.setdefault("group_by", [])
    tokens, groups = rules["missing_tokens"], rules["group_by"]
    if not isinstance(tokens, list) or any(not isinstance(t, str) for t in tokens):
        raise ValueError("missing_tokens must be a list of strings")
    rules["missing_tokens"] = list(dict.fromkeys(t.strip() for t in tokens))
    if (not isinstance(groups, list) or any(not isinstance(c, str) or not c.strip() for c in groups)
            or len(set(groups)) != len(groups)):
        raise ValueError("group_by must be a unique list of column names")
    checks = rules.get("checks")
    if not isinstance(checks, dict) or not checks or checks.keys() - CHECKS.keys():
        raise ValueError("checks must configure at least one supported check")
    for name, parameters in checks.items():
        reserved = {"missing_tokens", "group_by", "finding_limit"}
        if not isinstance(parameters, dict) or reserved & parameters.keys():
            raise ValueError(f"{name}: missing_tokens/group_by are shared; finding_limit is node-local")
        try:
            inspect.signature(CHECKS[name]).bind(None, **parameters)
        except TypeError as exc:
            raise ValueError(f"{name}: invalid check parameters: {exc}") from exc
    return rules


def make_context(table, rules, source=None, rule_set_id="custom", rule_set_version="1"):
    if any(not isinstance(v, str) or not v.strip() for v in (rule_set_id, rule_set_version)):
        raise ValueError("rule_set_id and rule_set_version must be non-empty strings")
    rules = _rules(rules)
    result = {"schema_version": CONTEXT_SCHEMA, "dataset": _dataset(table), "source": _source(source),
              "rule_set_id": rule_set_id, "rule_set_version": rule_set_version,
              "rules_sha256": _digest(rules), "rules": rules}
    result["context_sha256"] = _digest(result)
    return result


def _validate_context(context, table):
    if not isinstance(context, dict) or context.get("schema_version") != CONTEXT_SCHEMA:
        raise ValueError("invalid quality context")
    fields = {
        "schema_version", "dataset", "source", "rule_set_id", "rule_set_version", "rules_sha256", "rules"
    }
    if set(context) != fields | {"context_sha256"}:
        raise ValueError("incomplete quality context")
    if _digest({k: context[k] for k in fields}) != context["context_sha256"]:
        raise ValueError("context integrity mismatch; rebuild the context after editing")
    expected = make_context(table, context["rules"], context["source"],
                            context["rule_set_id"], context["rule_set_version"])
    if expected != context:
        raise ValueError("context/table fingerprint mismatch; rebuild the context for this table")


def run_check(table, check_id, parameters=None, context=None, finding_limit=500):
    if check_id not in CHECKS:
        raise ValueError(f"unsupported check: {check_id}")
    original_dataset = _dataset(table)
    work = table
    rule_set, source = None, {}
    if context is not None:
        _validate_context(context, table)
        rules = context["rules"]
        if check_id not in rules["checks"]:
            raise ValueError(f"{check_id} is not configured in the shared rules")
        parameters = deepcopy(rules["checks"][check_id])
        if check_id in {"missing", "outliers"}:
            parameters["group_by"] = rules["group_by"] or None
        if check_id in {"missing", "types", "units", "outliers"}:
            parameters["missing_tokens"] = rules["missing_tokens"]
        rule_set = {"id": context["rule_set_id"], "version": context["rule_set_version"],
                    "sha256": context["rules_sha256"], "rules": deepcopy(rules)}
        source = deepcopy(context["source"])
    result = CHECKS[check_id](work, finding_limit=finding_limit, **(parameters or {}))
    result["dataset"] = original_dataset
    result["provenance"] = {
        "version": "1", "mode": "shared" if context is not None else "local",
        "dataset_fingerprint": original_dataset["fingerprint"], "source": source, "rule_set": rule_set,
        "parameters_sha256": _digest(result["parameters"]),
    }
    if context is not None:
        result["provenance"]["missing_tokens"] = deepcopy(context["rules"]["missing_tokens"])
    return json_value(result)


def provenance_identity(report):
    """Validate trace fields and return a comparable source/rules identity."""
    provenance = report.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("version") != "1":
        raise ValueError("invalid report provenance")
    fingerprint = report["dataset"].get("fingerprint")
    if not isinstance(fingerprint, str) or not _SHA.fullmatch(fingerprint):
        raise ValueError("invalid dataset fingerprint")
    if provenance.get("dataset_fingerprint") != fingerprint:
        raise ValueError("report fingerprint contradicts provenance")
    if provenance.get("parameters_sha256") != _digest(report["parameters"]):
        raise ValueError("effective parameters integrity mismatch")
    mode = provenance.get("mode")
    source = _source(provenance.get("source"))
    rule_set = provenance.get("rule_set")
    if mode == "shared":
        if not isinstance(rule_set, dict) or set(rule_set) != {"id", "version", "sha256", "rules"}:
            raise ValueError("invalid shared ruleset provenance")
        rules = _rules(rule_set["rules"])
        if _digest(rules) != rule_set["sha256"]:
            raise ValueError("ruleset integrity mismatch")
    elif mode != "local" or rule_set is not None:
        raise ValueError("invalid provenance mode")
    return _json([report["dataset"], mode, source, rule_set])

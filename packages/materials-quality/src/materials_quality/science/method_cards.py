"""Offline, deterministic method retrieval and conservative precondition checking.

Eligibility checks declarations and available table facts, never scientific validity.
No LLM, network access, parameter fitting, or input mutation occurs here.
"""

import json
import re
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import NodeResult, numeric_matrix

BOOL_FIELDS = (
    "allow_intensity_loss",
    "equally_spaced",
    "nonzero_variance",
    "positive_peaks",
    "nonnegative",
    "split_confirmed",
    "groups_disjoint",
)
TABLE_COLUMNS = [
    "method_id",
    "name",
    "score",
    "status",
    "missing",
    "blocked",
    "operation",
    "source_title",
    "source_url",
    "source_kind",
    "source_locator",
]


def load_cards():
    """Return fresh independent records; packaged JSON is included in the wheel."""
    return json.loads(Path(__file__).with_name("method_cards.json").read_text(encoding="utf-8"))


CATALOG = [
    {
        "key": "lit.method_recommend",
        "title": "有依据的方法建议",
        "function": "materials_quality.science.method_cards:recommend_methods",
        "category": "literature",
        "requirement": "文献方法检索与适用条件检查",
        "table_input": True,
        "data_input": True,
        "tables_input": False,
        "default_config": {"top_k": 5, "signal_type": "unknown", "x_unit": "unknown"},
    }
]


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower()))


def _conditions(config, table):
    facts = deepcopy(config)
    for key in BOOL_FIELDS:
        value = facts.get(key)
        if value is None or value == "unknown":
            facts.pop(key, None)
        elif value in ("yes", "no"):
            facts[key] = value == "yes"
        elif type(value) is not bool:
            raise ValueError(f"{key} must be a boolean or unknown/yes/no")
    if table is None:
        return facts
    if not isinstance(table, pd.DataFrame):
        raise ValueError("table must be a pandas DataFrame")
    x, y = facts.get("x", "x"), facts.get("y", "y")
    if x in table and y in table:
        values = numeric_matrix(table, [x, y])
        dx = np.diff(values[:, 0])
        facts["increasing_coordinates"] = bool(len(dx) and (dx > 0).all())
        facts["equally_spaced"] = bool(len(dx) and np.allclose(dx, dx[0], rtol=1e-5, atol=1e-12))
        facts["nonzero_variance"] = bool(np.std(values[:, 1]) > 0)
        facts["nonnegative"] = bool((values[:, 1] >= 0).all())
        facts["point_count"] = len(table)
    split, sample = facts.get("split_column"), facts.get("sample_column")
    if split in table and sample in table:
        labels = table[split]
        facts["split_confirmed"] = bool(labels.notna().all() and set(labels) == {"train", "test"})
        identities = [sample] + ([facts["group_column"]] if facts.get("group_column") else [])
        disjoint = True
        for column in identities:
            if column not in table or table[column].isna().any():
                disjoint = False
                continue
            train = set(table.loc[labels == "train", column])
            test = set(table.loc[labels == "test", column])
            disjoint = disjoint and not bool(train & test)
        facts["groups_disjoint"] = disjoint
    return facts


def _missing(value):
    return (
        value is None
        or isinstance(value, str)
        and value.strip().lower() in {"", "unknown", "unspecified"}
        or isinstance(value, (list, tuple))
        and not value
    )


def _check(card, facts, table):
    missing, blocked = [], []
    for key, allowed in (("signal_type", card["signal_types"]), ("x_unit", card["coordinate_units"])):
        value = facts.get(key)
        if _missing(value):
            missing.append(key)
        elif value not in allowed:
            blocked.append(key)
    if _missing(facts.get("y_unit")):
        missing.append("y_unit")
    for key, expected in card["requirements"].items():
        value = facts.get(key)
        if _missing(value):
            missing.append(key)
        elif expected != "present" and value != expected:
            blocked.append(key)
    if card["planned"]:
        blocked.append("operation_not_implemented")
    if table is not None and card["operation"] == "materials.spectra":
        if any(facts.get(key, key) not in table for key in ("x", "y")):
            blocked.append("curve_columns")
        if len(table) < 3:
            blocked.append("curve_point_count")
    if card["id"] == "peak_detection" and not _missing(facts.get("prominence")):
        value = facts["prominence"]
        try:
            valid = type(value) is not bool and np.isfinite(float(value)) and float(value) > 0
        except (TypeError, ValueError):
            valid = False
        if not valid:
            blocked.append("prominence")
    if card["id"] == "trapezoid" and not _missing(facts.get("area_ranges")):
        try:
            ranges = np.asarray(facts["area_ranges"], dtype=float)
            valid = (
                ranges.ndim == 2
                and ranges.shape[1] == 2
                and len(ranges) > 0
                and np.isfinite(ranges).all()
                and (ranges[:, 0] < ranges[:, 1]).all()
            )
            if valid and table is not None and facts.get("x", "x") in table:
                coordinates = numeric_matrix(table, [facts.get("x", "x")])[:, 0]
                valid = bool(
                    (ranges[:, 0] >= coordinates.min()).all() and (ranges[:, 1] <= coordinates.max()).all()
                )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            blocked.append("area_ranges")
    if facts.get("increasing_coordinates") is False and card["operation"] == "materials.spectra":
        blocked.append("increasing_coordinates")
    if card["id"] in {"snv", "msc", "sg_derivative1", "sg_derivative2"}:
        if facts.get("goal") in {"absolute_intensity", "area", "peak_width"}:
            blocked.append("goal_requires_original_intensity")
    if card["id"].startswith("sg_"):
        window, order = facts.get("smooth_window"), facts.get("smooth_order")
        if not _missing(window) and (type(window) is not int or window < 3 or window % 2 != 1):
            blocked.append("smooth_window")
        if not _missing(order) and (
            type(order) is not int or order < card["default_config"].get("derivative_order", 0)
        ):
            blocked.append("smooth_order")
        if type(window) is int and type(order) is int and window <= order:
            blocked.append("smooth_window")
        if type(window) is int and window > facts.get("point_count", window):
            blocked.append("smooth_window")
    if "n_components" in card["requirements"] and not _missing(facts.get("n_components")):
        if type(facts["n_components"]) is not int or facts["n_components"] < 1:
            blocked.append("n_components")
    if table is not None and card["operation"] == "materials.chemometrics":
        selected = facts.get("feature_columns", [])
        if (
            not isinstance(selected, list)
            or not selected
            or any(not isinstance(c, str) or c not in table for c in selected)
        ):
            blocked.append("feature_columns")
            selected = []
        for key in ("sample_column", "split_column", "target_column"):
            if key in card["requirements"] and facts.get(key) not in table:
                blocked.append(key)
        if facts.get("target_column") in selected:
            blocked.append("target_in_features")
        if any(facts.get(key) in selected for key in ("sample_column", "split_column", "group_column")):
            blocked.append("identity_in_features")
        if selected and facts.get("split_column") in table:
            training = table.loc[table[facts["split_column"]] == "train"]
            if len(training) < 3:
                blocked.append("training_sample_count")
            try:
                numeric_matrix(table, selected)
                matrix = numeric_matrix(training, selected)
            except ValueError:
                blocked.append("nonfinite_features")
            else:
                if np.any(np.ptp(matrix, axis=0) == 0):
                    blocked.append("zero_variance_features")
                rank = int(np.linalg.matrix_rank(matrix - matrix.mean(axis=0)))
                limit = min(len(training) - 1, len(selected))
                if facts.get("cv_folds", 0) == 0:
                    limit = min(limit, rank)
                if type(facts.get("n_components")) is int and facts["n_components"] > limit:
                    blocked.append("n_components")
    return sorted(set(missing)), sorted(set(blocked))


def _sequence_check(sequence, candidates):
    blocked, missing = [], []
    signed = None
    for method in sequence:
        if method == "nmf" and signed:
            blocked.append(f"{signed}->nmf")
        if method in {"snv", "sg_derivative1", "sg_derivative2", "pca", "asls", "msc"}:
            signed = method
        row = candidates[method]
        blocked.extend(f"{method}:{key}" for key in row["blocked"])
        missing.extend(f"{method}:{key}" for key in row["missing"])
    return {
        "status": "blocked" if blocked else "missing" if missing else "eligible",
        "blocked": blocked,
        "missing": missing,
        "methods": sequence,
        "scope": "Declared preconditions and known sign incompatibilities; execution still validates data.",
    }


def recommend_methods(table=None, *, config=None, data=None, tables=None):
    """Return ranked method cards and an optional ordered compatibility check.

    ``method_ids`` explicitly selects cards even if their scientific conditions fail.
    With free text, zero token overlap yields no candidates. ``material`` is never
    treated as a substitute for signal definition. Empty query lists available cards.
    """
    if config is not None and not isinstance(config, dict):
        raise ValueError("config must be an object")
    config = deepcopy(config or {})
    cards = load_cards()
    lookup = {card["id"]: card for card in cards}
    top_k = config.get("top_k", 5)
    if type(top_k) is not int or not 1 <= top_k <= 20:
        raise ValueError("top_k must be an integer from 1 to 20")
    for key in ("method_ids", "sequence"):
        value = config.get(key, [])
        if not isinstance(value, list) or any(not isinstance(m, str) or m not in lookup for m in value):
            raise ValueError(f"{key} must be a list of known method IDs")
    query = config.get("query", "")
    if not isinstance(query, str):
        raise ValueError("query must be text")
    facts = _conditions(config, table)
    explicit = config.get("method_ids", [])
    sequence = config.get("sequence", [])
    query_tokens = _tokens(query)
    rows = []
    for card in cards:
        if explicit and card["id"] not in explicit and card["id"] not in sequence:
            continue
        searchable = " ".join([card["id"], card["name"], *card["goals"], *card["signal_types"]])
        score = len(query_tokens & _tokens(searchable))
        if query_tokens and not score and card["id"] not in explicit and card["id"] not in sequence:
            continue
        score += int(bool(config.get("goal")) and config["goal"] in card["goals"])
        missing, blocked = _check(card, facts, table)
        status = "blocked" if blocked else "missing" if missing else "eligible"
        execution = None
        if status == "eligible":
            bound = deepcopy(card["default_config"])
            bound.update({key: deepcopy(facts[key]) for key in card["config_fields"] if key in facts})
            execution = {"operation": card["operation"], "config": bound}
        rows.append(
            {
                **deepcopy(card),
                "method_id": card["id"],
                "score": score,
                "status": status,
                "missing": missing,
                "blocked": blocked,
                "execution": execution,
                "scientifically_validated": False,
            }
        )
    rows.sort(key=lambda row: (-row["score"], row["method_id"]))
    all_rows = {row["method_id"]: row for row in rows}
    # Requested sequences are checked in full even when the displayed table is bounded.
    check = _sequence_check(sequence, all_rows) if sequence else None
    rows = rows[:top_k] if not explicit else rows
    summary = [
        {
            "method_id": r["method_id"],
            "name": r["name"],
            "score": r["score"],
            "status": r["status"],
            "missing": ", ".join(r["missing"]),
            "blocked": ", ".join(r["blocked"]),
            "operation": r["operation"],
            "source_title": r["source"]["title"],
            "source_url": r["source"]["url"],
            "source_kind": r["source"]["kind"],
            "source_locator": r["source"]["locator"],
        }
        for r in rows
    ]
    return NodeResult(
        table=pd.DataFrame(summary, columns=TABLE_COLUMNS),
        data={
            "candidates": rows,
            "sequence_check": check,
            "retrieval": "deterministic lexical overlap; stable ID tie-break",
            "eligibility_scope": "Declared conditions plus available table checks; not validation.",
        },
        warnings=["候选与适用条件检查不是实验验证；文献参数不会自动成为当前实验配方。"],
    )

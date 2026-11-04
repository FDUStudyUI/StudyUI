"""Explicit, auditable table transformations; inputs are never mutated."""

import ast
from copy import deepcopy
from numbers import Integral

import numpy as np
import pandas as pd

from materials_quality.common import groups, json_value, missing, numeric, select_columns, validate_table
from materials_quality.common import missing_tokens as normalize_missing_tokens
from materials_quality.science.contracts import NodeResult, numeric_matrix, require_table
from materials_quality.science.table_contract import (
    attach_contract,
    make_contract,
    read_contract,
    restore_contract_units,
)
from materials_quality.units import _QUANTITY, _REGISTRY, _unit


def _changes(before, after):
    changes = []
    for column in before.columns.intersection(after.columns):
        if len(before) != len(after):
            continue
        for position, (old, new) in enumerate(zip(before[column], after[column], strict=True)):
            a, b = json_value(old), json_value(new)
            if a != b or (type(old) is not type(new) and a is not None):
                changes.append(
                    {
                        "row_position": position,
                        "row_index": json_value(before.index[position]),
                        "column": column,
                        "before": a,
                        "after": b,
                    }
                )
    return changes


def _result(original, output, method, config, warnings=None, **details):
    validate_table(output)
    return NodeResult(
        table=output,
        data=json_value(
            {
                "method": method,
                "parameters": deepcopy(config),
                "input_rows": len(original),
                "output_rows": len(output),
                "input_columns": list(original.columns),
                "output_columns": list(output.columns),
                **details,
            }
        ),
        warnings=warnings or [],
    )


def _complete_keys(frame, columns, tokens=("",)):
    names = select_columns(frame, [columns] if isinstance(columns, str) else columns)
    for name in names:
        if frame[name].map(lambda value: missing(value, tokens)).any():
            raise ValueError(f"{name}: matching, grouping and ordered filling require nonmissing keys")
    return names


def table_units(frame, data=None, declared=None):
    """Combine explicit column labels without assuming that equal dimensions imply equal units."""
    units = {}
    upstream = data.get("units", {}) if isinstance(data, dict) else {}
    if not isinstance(upstream, dict):
        raise ValueError("upstream units must be a mapping")
    # Reports can describe the preceding schema. Unknown old fields carry no
    # unit information about new columns; explicit declarations stay strict.
    upstream = {key: value for key, value in upstream.items() if key in frame.columns}
    for mapping in (frame.attrs.get("units", {}), upstream, {} if declared is None else declared):
        if not isinstance(mapping, dict) or set(mapping) - set(frame.columns):
            raise ValueError("unit declarations must map existing columns to nonempty unit labels")
        for column, label in mapping.items():
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f"{column}: unit label must be a nonempty string")
            label = label.strip()
            if column in units and units[column] != label:
                try:
                    same = _unit(units[column]) == _unit(label)
                except ValueError:
                    same = False
                if not same:
                    raise ValueError(f"conflicting units for {column}: {units[column]!r} and {label!r}")
            units[column] = label
    return units


def _formula(expression, frame, units):
    """Interpret a small arithmetic AST. No Python evaluation or object access."""
    if not isinstance(expression, str) or len(expression) > 1000:
        raise ValueError("formula must be a string of at most 1000 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("invalid formula syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError("formula is too complex")

    def same_unit(a, b):
        if a == b:
            return a
        if a is None or b is None:
            return None
        if _unit(a) != _unit(b):
            raise ValueError("formula addition/comparison requires identical units; convert units first")
        return a

    def combine(a, b, divide=False):
        if b == "dimensionless":
            return a, False
        if a == "dimensionless" and not divide:
            return b, False
        if a is None or b is None:
            return None, True
        return str(_unit(a) / _unit(b) if divide else _unit(a) * _unit(b)), True

    def visit(node, depth=0):
        if depth > 20:
            raise ValueError("formula nesting is too deep")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if not np.isfinite(node.value):
                raise ValueError("formula constants must be finite")
            return float(node.value), "dimensionless", False
        if isinstance(node, ast.Name) and node.id in frame.columns and not node.id.startswith("__"):
            return numeric_matrix(frame, [node.id])[:, 0], units.get(node.id), False
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v, u, explicit = visit(node.operand, depth + 1)
            return (v if isinstance(node.op, ast.UAdd) else -v), u, explicit
        if isinstance(node, ast.BinOp):
            left, lu, le = visit(node.left, depth + 1)
            right, ru, re = visit(node.right, depth + 1)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                unit = same_unit(lu, ru)
                value = left + right if isinstance(node.op, ast.Add) else left - right
                return value, unit, le or re
            if isinstance(node.op, (ast.Mult, ast.Div)):
                unit, explicit = combine(lu, ru, isinstance(node.op, ast.Div))
                value = left * right if isinstance(node.op, ast.Mult) else left / right
                return value, unit, explicit or le or re
            if isinstance(node.op, ast.Pow):
                if not np.isscalar(right) or abs(right) > 32 or ru != "dimensionless":
                    raise ValueError(
                        "formula power must be a scalar dimensionless exponent with absolute value <=32"
                    )
                return np.power(left, right), str(_unit(lu) ** right) if lu is not None else None, True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            name = node.func.id
            arity = {"abs": 1, "sqrt": 1, "log": 1, "log10": 1, "exp": 1, "minimum": 2, "maximum": 2}
            if name not in arity or len(node.args) != arity[name]:
                raise ValueError("formula uses an unapproved function or argument count")
            args = [visit(arg, depth + 1) for arg in node.args]
            value, unit, explicit = args[0]
            if name == "abs":
                return np.abs(value), unit, explicit
            if name == "sqrt":
                return np.sqrt(value), str(_unit(unit) ** 0.5) if unit is not None else None, True
            if name in {"minimum", "maximum"}:
                other, other_unit, other_explicit = args[1]
                unit = same_unit(unit, other_unit)
                return getattr(np, name)(value, other), unit, explicit or other_explicit
            if unit is None or not _unit(unit).dimensionless:
                raise ValueError("formula logarithm/exponential requires explicitly dimensionless inputs")
            value = _REGISTRY.Quantity(value, _unit(unit)).to("dimensionless").magnitude
            return getattr(np, name)(value), "dimensionless", explicit
        raise ValueError(
            "formula supports only numeric arithmetic, named columns, and approved numeric functions"
        )

    try:
        with np.errstate(all="raise"):
            return visit(tree.body)
    except (ArithmeticError, TypeError, OverflowError) as exc:
        raise ValueError("formula produced invalid numeric values") from exc


def _derive_columns(frame, rules, units):
    if not isinstance(rules, list):
        raise ValueError("derived_columns must be a formula rule table")
    records = []
    for rule in rules:
        column = rule.get("column")
        if not isinstance(column, str) or not column.strip() or column in frame:
            raise ValueError("formula output column must be a new nonempty name")
        values, inferred, needs_unit = _formula(rule.get("expression"), frame, units)
        declared = rule.get("unit") or None
        if declared is not None and (not isinstance(declared, str) or not declared.strip()):
            raise ValueError("formula unit must be a nonempty label")
        if (needs_unit or inferred is None) and not declared:
            raise ValueError("formula requires an explicit output unit for compound/undeclared input units")
        if declared and inferred is not None and _unit(declared) != _unit(inferred):
            raise ValueError("formula output unit does not match arithmetic units; convert units explicitly")
        values = np.asarray(values, dtype=float)
        if values.ndim == 0:
            values = np.full(len(frame), values.item())
        if values.shape != (len(frame),) or not np.isfinite(values).all():
            raise ValueError("formula must produce one finite number per row")
        frame[column] = values
        units[column] = declared or inferred
        records.append(
            {
                "column": column,
                "expression": rule["expression"],
                "unit": units[column],
                "unit_verified": inferred is not None,
            }
        )
    return records


def filter_rows(table=None, *, config=None, data=None, tables=None):
    config = config or {}
    frame = require_table(table, min_rows=0)
    original = frame.copy(deep=True)
    source_units = table_units(frame, data)
    derived = _derive_columns(frame, config.get("derived_columns", []), source_units)
    frame.attrs["units"] = source_units
    logic = config.get("logic", "and")
    if logic not in {"and", "or"}:
        raise ValueError("logic must be and or or")
    conditions = config.get("conditions", [])
    if not isinstance(conditions, list):
        raise ValueError("conditions must be a list")
    mask = np.ones(len(frame), dtype=bool) if logic == "and" or not conditions else np.zeros(len(frame), bool)
    for rule in conditions:
        column, op, value = rule.get("column"), rule.get("op"), rule.get("value")
        select_columns(frame, [column])
        series = frame[column]
        try:
            if op == "eq":
                selected = series.eq(value)
            elif op == "ne":
                selected = series.ne(value)
            elif op in {"lt", "le", "gt", "ge"}:
                selected = getattr(series, op)(value)
            elif op in {"in", "not_in"}:
                if not isinstance(value, list):
                    raise ValueError("in/not_in requires a list value")
                selected = series.isin(value)
                if op == "not_in":
                    selected = ~selected
            elif op == "contains":
                selected = series.astype("string").str.contains(str(value), regex=False, na=False)
            elif op in {"isna", "notna"}:
                selected = series.isna() if op == "isna" else series.notna()
            else:
                raise ValueError(f"unsupported filter operator: {op}")
        except TypeError as exc:
            raise ValueError(f"incompatible comparison for {column}; convert types explicitly first") from exc
        selected = selected.fillna(False).to_numpy(dtype=bool)
        mask = mask & selected if logic == "and" else mask | selected
    if config.get("drop_empty", False):
        empty = frame.apply(lambda s: s.map(missing)).all(axis=1).to_numpy()
        mask &= ~empty
    output = frame.iloc[np.flatnonzero(mask)].copy(deep=True)
    if config.get("columns") is not None:
        output = output[select_columns(output, config["columns"])].copy()
    rename = config.get("rename", {})
    if not isinstance(rename, dict) or rename.keys() - set(output.columns):
        raise ValueError("rename must map existing selected columns to new names")
    units = {rename.get(col, col): unit for col, unit in source_units.items() if col in output.columns}
    output = output.rename(columns=rename)
    output.attrs["units"] = units
    return _result(
        original,
        output,
        "filter",
        config,
        removed_positions=np.flatnonzero(~mask).tolist(),
        retained_positions=np.flatnonzero(mask).tolist(),
        renamed_columns=rename,
        derived_columns=derived,
        units=units,
    )


def handle_missing(table=None, *, config=None, data=None, tables=None):
    config = config or {}
    frame = require_table(table, min_rows=0)
    selected = select_columns(frame, config.get("columns"))
    method = config.get("method", "keep")
    if method not in {"keep", "drop", "mean", "median", "mode", "ffill", "linear"}:
        raise ValueError("unknown missing-value method")
    tokens = normalize_missing_tokens(config.get("missing_tokens"))
    mask = np.array([[missing(v, tokens) for v in frame[c]] for c in selected], dtype=bool).T
    if len(frame) == 0:
        mask = np.empty((0, len(selected)), dtype=bool)
    if method in {"keep", "drop"}:
        keep = ~mask.any(axis=1) if method == "drop" else np.ones(len(frame), bool)
        return _result(
            frame,
            frame.iloc[np.flatnonzero(keep)].copy(),
            method,
            config,
            changes=[],
            removed_positions=np.flatnonzero(~keep).tolist(),
        )
    if method == "linear" and config.get("continuous") is not True:
        raise ValueError("linear interpolation requires explicit continuous=true")
    order_by = config.get("order_by")
    if method in {"ffill", "linear"} and not order_by:
        raise ValueError("ordered filling requires an explicit order_by coordinate")
    output = frame.copy(deep=True)
    warnings = []
    if config.get("group_by"):
        _complete_keys(frame, config["group_by"], tokens)
    if method in {"ffill", "linear"}:
        _complete_keys(frame, [order_by], tokens)
    for group, positions in groups(frame, config.get("group_by")):
        coordinates = None
        if method in {"ffill", "linear"}:
            select_columns(frame, [order_by])
            coordinate = frame[order_by].iloc[positions]
            if pd.api.types.is_datetime64_any_dtype(coordinate):
                integers = coordinate.astype("int64").to_numpy()
                coordinates = np.asarray([int(t) - int(integers[0]) for t in integers], dtype=float)
            else:
                coordinates = numeric_matrix(frame.iloc[positions], [order_by])[:, 0]
            if len(np.unique(coordinates)) != len(coordinates):
                raise ValueError("ordered interpolation coordinates must be unique within each group")
            differences = np.diff(coordinates)
            if len(differences) and not (np.all(differences > 0) or np.all(differences < 0)):
                raise ValueError("order_by must be monotonic within each group; explicitly sort the source")
        for j, column in enumerate(selected):
            local_missing = mask[positions, j]
            if not local_missing.any():
                continue
            values = frame[column].iloc[positions].astype(object).tolist()
            observed = [v for v, absent in zip(values, local_missing, strict=True) if not absent]
            if not observed:
                raise ValueError(f"no observed baseline for {column} in group {group}")
            replacements = {}
            if method in {"mean", "median"}:
                numbers = np.array([float(numeric(v)) for v in observed])
                fill = float(np.mean(numbers) if method == "mean" else np.median(numbers))
                if not np.isfinite(fill):
                    raise ValueError("imputation baseline is not finite")
                replacements = dict.fromkeys(np.flatnonzero(local_missing), fill)
            elif method == "mode":
                modes = pd.Series(observed).mode(dropna=True)
                if len(modes) > 1:
                    warnings.append(f"{column}, group {group}: tied modes; selected the first sorted mode")
                replacements = dict.fromkeys(np.flatnonzero(local_missing), modes.iloc[0])
            elif method == "ffill":
                last, has_last = None, False
                for i, absent in enumerate(local_missing):
                    if absent and has_last:
                        replacements[i] = last
                    elif not absent:
                        last, has_last = values[i], True
            else:
                known_x = coordinates[~local_missing]
                known_y = np.array([float(numeric(v)) for v in observed])
                if len(known_x) < 2:
                    raise ValueError("linear interpolation needs at least two observed points per group")
                order = np.argsort(known_x)
                for i in np.flatnonzero(local_missing):
                    if known_x.min() <= coordinates[i] <= known_x.max():
                        replacements[i] = float(np.interp(coordinates[i], known_x[order], known_y[order]))
            col = output.columns.get_loc(column)
            # Object storage preserves original scalars and avoids float coercion
            # in untouched cells when introducing replacements.
            output[column] = output[column].astype(object)
            for local, replacement in replacements.items():
                output.iat[int(positions[local]), col] = replacement
            if len(replacements) < int(local_missing.sum()):
                warnings.append(f"{column}, group {group}: boundary values retained; no extrapolation")
    return _result(frame, output, method, config, warnings, changes=_changes(frame, output))


def convert_units(table=None, *, config=None, data=None, tables=None):
    config = config or {}
    frame = require_table(table, min_rows=0)
    source = config.get("source_units", {})
    target = config.get("target_units", config.get("expected_units", {}))
    if not isinstance(source, dict) or not isinstance(target, dict) or not target:
        raise ValueError("provide source_units and non-empty target_units mappings")
    source = table_units(frame, data, source)
    selected = select_columns(frame, list(target))
    tokens = normalize_missing_tokens(config.get("missing_tokens"))
    output = frame.copy(deep=True)
    records = []
    for column in selected:
        destination = _unit(target[column])
        declared = _unit(source[column]) if column in source else None
        converted = []
        for position, value in enumerate(frame[column]):
            if missing(value, tokens):
                converted.append(value)
                continue
            match = _QUANTITY.fullmatch(value) if isinstance(value, str) else None
            inline = match.group(2) if match else ""
            magnitude = match.group(1) if match else value
            actual = _unit(inline) if inline else declared
            if actual is None:
                raise ValueError(f"{column}: an explicit source unit is required")
            if actual.dimensionality != destination.dimensionality:
                raise ValueError(f"{column}: incompatible units {actual} -> {destination}")
            quantity = _REGISTRY.Quantity(float(numeric(magnitude)), actual).to(destination)
            number = float(quantity.magnitude)
            if not np.isfinite(number):
                raise ValueError("converted values overflowed; choose a representable unit/precision")
            converted.append(number)
            records.append(
                {
                    "row_position": position,
                    "row_index": json_value(frame.index[position]),
                    "column": column,
                    "before": json_value(value),
                    "after": number,
                    "source_unit": str(actual),
                    "target_unit": str(destination),
                }
            )
        output[column] = pd.Series(converted, index=frame.index)
    output.attrs["units"] = {**source, **target}
    return _result(frame, output, "unit_conversion", config, changes=records, units=output.attrs["units"])


def reshape_table(table=None, *, config=None, data=None, tables=None):
    config = config or {}
    frame = require_table(table, min_rows=0)
    method = config.get("method", "types")
    if method == "wide_to_long":
        output = frame.melt(
            id_vars=config.get("id_vars"),
            value_vars=config.get("value_vars"),
            var_name=config.get("var_name", "variable"),
            value_name=config.get("value_name", "value"),
        )
    elif method == "long_to_wide":
        try:
            pivot = frame.pivot(index=config["index"], columns=config["columns"], values=config["values"])
            output = pivot.reset_index()
        except (KeyError, ValueError) as exc:
            raise ValueError("long_to_wide requires unique index/column pairs; aggregate duplicates") from exc
        if isinstance(output.columns, pd.MultiIndex):
            raise ValueError("select one values field for an unambiguous flat output schema")
        output.columns.name = None
        output.columns = [str(c) for c in output.columns]
    elif method == "types":
        rules = config.get("types", {})
        if not isinstance(rules, dict) or not rules:
            raise ValueError("types must explicitly map fields to target types")
        select_columns(frame, list(rules))
        output = frame.copy(deep=True)
        for column, target in rules.items():
            if target in {"number", "integer"}:
                series = output[column]
                parsed = []
                for value in series:
                    if pd.isna(value):
                        parsed.append(None)
                        continue
                    try:
                        number = numeric(value)
                    except (ValueError, ArithmeticError) as exc:
                        raise ValueError(f"{column}: expected finite numbers") from exc
                    if target == "integer":
                        if number != number.to_integral_value() or not -(2**63) <= number < 2**63:
                            raise ValueError(f"{column}: value is not an exactly representable Int64 integer")
                        parsed.append(int(number))
                    else:
                        parsed.append(value)
                if target == "integer":
                    output[column] = pd.array(parsed, dtype="Int64")
                else:
                    output[column] = pd.to_numeric(series, errors="raise")
            elif target == "datetime":
                pattern = config.get("date_formats", {}).get(column)
                if not pattern:
                    raise ValueError("date conversion requires an explicit date_formats entry")
                parsed = pd.to_datetime(output[column], format=pattern, errors="raise")
                observed = output[column].notna()
                if not parsed[observed].dt.strftime(pattern).eq(output.loc[observed, column]).all():
                    raise ValueError("date values do not exactly match the configured format")
                output[column] = parsed
            elif target == "category":
                allowed = config.get("categories", {}).get(column)
                if allowed is not None and not output[column].dropna().isin(allowed).all():
                    raise ValueError(f"{column} contains values outside configured categories")
                output[column] = pd.Categorical(output[column], categories=allowed)
            elif target == "string":
                output[column] = output[column].astype("string")
            elif target == "boolean":
                mapping = {True: True, False: False, "true": True, "false": False}
                if not all(
                    isinstance(v, (bool, np.bool_)) or isinstance(v, str) and v in mapping
                    for v in output[column].dropna()
                ):
                    raise ValueError(f"{column}: boolean conversion accepts only true/false")
                output[column] = output[column].map(mapping).astype("boolean")
            else:
                raise ValueError(f"unknown target type: {target}")
    else:
        raise ValueError("method must be wide_to_long, long_to_wide or types")
    details = (
        {"changes": _changes(frame, output)} if method == "types" else {"record_mapping": "see id_vars/index"}
    )
    return _result(frame, output, method, config, **details)


def _specimen_keys(frame, keys, label):
    columns, types = [], {}
    for key in select_columns(frame, keys):
        values = []
        for position, value in enumerate(frame[key]):
            if missing(value):
                raise ValueError(f"{label}: missing specimen key {key!r} at row position {position}")
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, Integral) and not isinstance(value, (bool, np.bool_)):
                values.append(int(value))
            else:
                raise ValueError(
                    f"{label}: specimen keys must be exact strings or integers ({key!r}, row {position})"
                )
        kinds = {type(value) for value in values}
        if len(kinds) > 1:
            raise ValueError(f"{label}: mixed key types in {key!r}; normalize identifiers explicitly")
        if kinds:
            types[key] = kinds.pop()
        columns.append(values)
    lookup, duplicates = {}, {}
    for position, identity in enumerate(zip(*columns, strict=True)):
        if identity in lookup:
            duplicates[identity] = duplicates.get(identity, 1) + 1
        else:
            lookup[identity] = position
    if duplicates:
        examples = [
            {"key": dict(zip(keys, identity, strict=True)), "rows": count}
            for identity, count in list(duplicates.items())[:10]
        ]
        raise ValueError(
            f"{label}: {len(duplicates)} duplicate specimen keys ({sum(duplicates.values())} rows). "
            f"Preview: {examples}. "
            "Resolve repeated measurements at an explicit specimen and measurement-condition grain upstream."
        )
    return lookup, types


def _specimen_contract(frame, keys, label, *, master=False, allow_undeclared=False):
    contract = read_contract(frame)
    if contract is None:
        if not master and not allow_undeclared:
            raise ValueError(f"{label}: undeclared feature table. Confirm its specimen grain explicitly")
        return None, table_units(frame)
    grain, roles = contract["granularity"], contract["roles"]
    allowed_grains = {"sample", "experimental_unit"} if master else {"sample", "experimental_unit", "curve"}
    if grain not in allowed_grains:
        raise ValueError(f"{label}: incompatible grain {grain!r}. Connect a specimen-level table")
    if grain == "curve" and "curve_id" not in roles:
        raise ValueError(f"{label}: curve-grain features require a declared curve_id")
    if not master and "variable" in roles and frame[roles["variable"]].nunique(dropna=False) > 1:
        raise ValueError(f"{label}: multiple measured variables in one feature column. Pivot them upstream")
    identity = roles.get("sample_id", roles.get("experimental_unit"))
    if grain == "experimental_unit":
        identity = roles.get("experimental_unit", identity)
    # Contract roles are scalar. An immediately preceding association can
    # establish composite identity, while historical records are provenance.
    last_derivation = contract["derived_from"][-1] if contract["derived_from"] else {}
    if identity is not None:
        identity_matches = identity in keys
    elif last_derivation.get("operation") == "preprocess.merge.specimen":
        previous_keys = last_derivation.get("keys")
        identity_matches = (
            isinstance(previous_keys, list)
            and len(previous_keys) == len(keys)
            and all(key in previous_keys for key in keys)
        )
    else:
        identity_matches = master
    if not identity_matches:
        raise ValueError(f"{label}: declared specimen identity must be represented by the selected keys")
    non_specimen_roles = {
        "curve_id", "technical_replicate", "peak_id", "x", "response", "variable", "value", "pair_id"
    }
    for role in sorted(non_specimen_roles & roles.keys()):
        if roles[role] in keys and roles[role] != identity:
            raise ValueError(f"{label}: specimen keys cannot include the declared {role} column")
    return contract, table_units(restore_contract_units(frame, contract))


def _associate_specimens(master, features, config, sources):
    on = config.get("on")
    if not on:
        raise ValueError("specimen association requires explicit master specimen keys")
    keys = select_columns(master, [on] if isinstance(on, str) else on)
    unmatched = config.get("unmatched", "report")
    allow_undeclared = config.get("allow_undeclared_features", False)
    if unmatched not in ("report", "error") or type(allow_undeclared) is not bool:
        raise ValueError("unmatched must be report or error; allow_undeclared_features must be boolean")
    if config.get("how", "left") != "left" or config.get("validate", "one_to_one") != "one_to_one":
        raise ValueError("specimen association requires a one-to-one master-left join")
    master_lookup, master_types = _specimen_keys(master, keys, "specimen master")
    contract, units = _specimen_contract(master, keys, "specimen master", master=True)
    if set(keys) & units.keys():
        raise ValueError("specimen master keys must be unitless identifiers")
    parts = [master.reset_index(drop=True)]
    parts[0].attrs = {}
    columns = set(master.columns)
    diagnostics, warnings = [], []
    for position, feature in enumerate(features, start=1):
        label = f"feature table {position}"
        feature_lookup, feature_types = _specimen_keys(feature, keys, label)
        feature_contract, feature_units = _specimen_contract(
            feature, keys, label, allow_undeclared=allow_undeclared
        )
        for key, kind in feature_types.items():
            if kind != master_types[key]:
                raise ValueError(f"{label}: incompatible key types for {key!r}. Normalize keys explicitly")
        if set(keys) & feature_units.keys():
            raise ValueError(f"{label}: specimen keys must be unitless identifiers")
        feature_columns = [column for column in feature if column not in keys]
        if not feature_columns:
            raise ValueError(f"{label}: connect a feature table containing at least one non-key column")
        collisions = columns.intersection(feature_columns)
        if collisions:
            table_units(
                feature,
                declared={c: units[c] for c in collisions if c in units},
                data={"units": feature_units},
            )
            raise ValueError(f"{label}: duplicate non-key columns {sorted(collisions)}. Rename upstream")
        columns.update(feature_columns)
        units.update(feature_units)

        positions = [feature_lookup.get(identity, -1) for identity in master_lookup]
        missing_keys = [identity for identity in master_lookup if identity not in feature_lookup]
        orphan_keys = [identity for identity in feature_lookup if identity not in master_lookup]
        record = {
            "table_position": position,
            "input_grain": None if feature_contract is None else feature_contract["granularity"],
            "identity_evidence": "explicit_user_declaration" if not feature_contract else "table_contract",
            "cardinality": "one_to_one",
            "matched_rows": len(master) - len(missing_keys),
            "missing_master_rows": len(missing_keys),
            "orphan_feature_rows": len(orphan_keys),
            "missing_master_preview": [dict(zip(keys, row, strict=True)) for row in missing_keys[:10]],
            "orphan_feature_preview": [dict(zip(keys, row, strict=True)) for row in orphan_keys[:10]],
        }
        diagnostics.append(record)
        if missing_keys or orphan_keys:
            warnings.append(
                f"{label}: {len(missing_keys)} missing master specimens and "
                f"{len(orphan_keys)} orphan feature rows. "
                f"Missing preview: {record['missing_master_preview']}. "
                f"Orphan preview: {record['orphan_feature_preview']}."
            )
        part = feature[feature_columns].reset_index(drop=True)
        part.attrs = {}
        if missing_keys:
            for column in part.select_dtypes(include=["integer", "bool"]):
                part[column] = part[column].convert_dtypes()
        parts.append(part.reindex(positions).reset_index(drop=True))
    if unmatched == "error" and warnings:
        raise ValueError("incomplete specimen association: " + " ".join(warnings))

    output = pd.concat(parts, axis=1)
    output.index = master.index.copy()
    output.attrs["units"] = units
    master_declaration = contract or {}
    lineage = {
        "operation": "preprocess.merge.specimen",
        "keys": keys,
        "sources": [{key: source[key] for key in ("table_sha256", "contract_sha256")} for source in sources],
    }
    output_contract = make_contract(
        output,
        granularity=master_declaration.get("granularity", "sample"),
        roles=master_declaration.get("roles", {"sample_id": keys[0]} if len(keys) == 1 else {}),
        experimental_design=master_declaration.get("experimental_design"),
        aggregation=master_declaration.get("aggregation"),
        derived_from=[*master_declaration.get("derived_from", []), lineage],
    )
    return attach_contract(output, output_contract), warnings, {"keys": keys, "features": diagnostics}


def merge_tables(table=None, *, config=None, data=None, tables=None):
    config = config or {}
    method = config.get("method", "join")
    if method == "specimen":
        if table is None or not isinstance(tables, list) or not tables:
            raise ValueError("connect a specimen master and at least one feature table")
        frames = [require_table(table), *(require_table(t, min_rows=0) for t in tables)]
    else:
        if not isinstance(tables, list) or len(tables) < 2:
            raise ValueError("connect at least two input tables")
        frames = [require_table(t, min_rows=0) for t in tables]
    details = {}
    warnings = []
    if method == "specimen":
        sources = _merge_sources(frames, include_contracts=True)
        output, warnings, details["association"] = _associate_specimens(
            frames[0], frames[1:], config, sources
        )
    elif method == "append":
        output = pd.concat(frames, ignore_index=config.get("ignore_index", True), sort=False)
    elif method == "join":
        on = config.get("on")
        if not on:
            raise ValueError("join requires an explicit on key or key list")
        for frame in frames:
            _complete_keys(frame, on)
        output = frames[0]
        for right in frames[1:]:
            output = output.merge(
                right,
                on=on,
                how=config.get("how", "left"),
                validate=config.get("validate", "one_to_one"),
                suffixes=tuple(config.get("suffixes", ["_left", "_right"])),
                sort=False,
            )
    elif method == "asof":
        if len(frames) != 2 or config.get("tolerance") is None:
            raise ValueError("asof requires exactly two tables and an explicit tolerance")
        key = config.get("on")
        if not isinstance(key, str):
            raise ValueError("asof requires a single on coordinate")
        by = config.get("by")
        group_keys = [by] if isinstance(by, str) else list(by or [])
        keys = [*group_keys, key]
        for frame in frames:
            _complete_keys(frame, keys)
            if not frame[key].is_monotonic_increasing:
                raise ValueError("asof coordinates must be nonmissing and sorted increasing")
        left, right = frames
        if right.duplicated(keys).any():
            raise ValueError("duplicate right-hand asof coordinates within a group; resolve replicates first")
        tolerance = config["tolerance"]
        if pd.api.types.is_datetime64_any_dtype(frames[0][key]):
            tolerance = pd.Timedelta(tolerance)
        marker = "__matched_source_position"
        while marker in left.columns or marker in right.columns:
            marker += "_"
        right[marker] = np.arange(len(right))
        options = {"on": key, "by": by, "tolerance": tolerance}
        direction = config.get("direction", "nearest")
        if direction == "nearest":
            # Pandas silently prefers the earlier record on a tie.
            candidates = [
                pd.merge_asof(left[keys], right[[*keys, marker]], direction=side, **options)[marker]
                for side in ("backward", "forward")
            ]
            for i, (before, after) in enumerate(zip(*candidates, strict=True)):
                if pd.notna(before) and pd.notna(after) and before != after:
                    t = left[key].iat[i]
                    earlier = right[key].iat[int(before)]
                    later = right[key].iat[int(after)]
                    if _coordinate_distance(t, earlier) == _coordinate_distance(t, later):
                        raise ValueError(f"ambiguous nearest asof match at left row {i}; choose a direction")
        output = pd.merge_asof(
            left,
            right,
            direction=direction,
            suffixes=tuple(config.get("suffixes", ["_left", "_right"])),
            **options,
        )
        matches = []
        for i, pos in enumerate(output.pop(marker)):
            j = int(pos) if pd.notna(pos) else None
            coordinate = right[key].iat[j] if j is not None else None
            distance = _coordinate_distance(left[key].iat[i], coordinate) if j is not None else None
            matches.append(
                {
                    "left_position": i,
                    "left_coordinate": left[key].iat[i],
                    "right_position": j,
                    "right_coordinate": coordinate,
                    "distance": distance,
                }
            )
        details["matches"] = matches
    else:
        raise ValueError("merge method must be join, asof, append or specimen")
    return _result(
        frames[0],
        output,
        method,
        config,
        warnings=warnings,
        input_table_rows=[len(t) for t in frames],
        sources=sources if method == "specimen" else _merge_sources(frames),
        **details,
    )


def _merge_sources(frames, *, include_contracts=False):
    from materials_quality.context import table_fingerprint

    sources = [
        {
            "table_position": i,
            "source_name": t.attrs.get("source_name"),
            "source_sha256": t.attrs.get("source_sha256"),
            "table_sha256": table_fingerprint(t),
            "rows": len(t),
            "columns": list(t.columns),
        }
        for i, t in enumerate(frames)
    ]
    if include_contracts:
        for source, frame in zip(sources, frames, strict=True):
            contract = read_contract(frame)
            source["contract_sha256"] = None if contract is None else contract["contract_sha256"]
    return sources


def _coordinate_distance(first, second):
    # Python integers avoid unsigned subtraction wrapping around the coordinate origin.
    first = first.item() if isinstance(first, np.generic) else first
    second = second.item() if isinstance(second, np.generic) else second
    return abs(first - second)


def normalize_table(table=None, *, config=None, data=None, tables=None):
    config = config or {}
    frame = require_table(table)
    method = config.get("method", "minmax")
    if method in {"blank_subtract", "reference_ratio", "linear_calibration"}:
        from .calibration import calibrate_signal

        return calibrate_signal(frame, config, data)
    selected = select_columns(frame, config.get("columns"))
    if method not in {"minmax", "zscore", "robust"}:
        raise ValueError("normalization method must be minmax, zscore or robust")
    values = numeric_matrix(frame, selected)
    output = frame.copy(deep=True)
    parameters, warnings = {}, []
    group_by = config.get("group_by") or []
    if isinstance(group_by, str):
        group_by = [group_by]
    if group_by:
        _complete_keys(frame, group_by)
    by_group = []
    # Allocate numeric destination columns before positional group assignment.
    for column in selected:
        output[column] = output[column].astype(float)
    for group, positions in groups(frame, group_by):
        local_parameters = {}
        for j, column in enumerate(selected):
            series = values[positions, j]
            center, scale = _normalization_baseline(series, method, column)
            if scale == 0:
                warnings.append(f"{column}, group {group}: constant/zero-spread baseline; mapped to zero")
                normalized = np.zeros(len(series))
            else:
                normalized = (series - center) / scale
            if not np.isfinite(normalized).all():
                raise ValueError("normalization results are not finite")
            output.iloc[positions, output.columns.get_loc(column)] = normalized
            local_parameters[column] = {
                "center": center,
                "scale": scale,
                "ddof": 0 if method == "zscore" else None,
            }
        by_group.append({"group": group, "parameters": local_parameters, "count": len(positions)})
        if not group_by:
            parameters = local_parameters
    units = {**table_units(frame, data), **dict.fromkeys(selected, "dimensionless")}
    output.attrs["units"] = units
    return _result(
        frame,
        output,
        method,
        config,
        warnings,
        units=units,
        fit_parameters=parameters,
        fit_parameters_by_group=by_group,
        group_by=group_by,
        changes=_changes(frame, output),
    )


def _normalization_baseline(series, method, column):
    if method == "minmax":
        center, scale = float(series.min()), float(series.max() - series.min())
    elif method == "zscore":
        center, scale = float(np.mean(series)), float(np.std(series, ddof=0))
    else:
        q1, q3 = np.quantile(series, [0.25, 0.75])
        center, scale = float(np.median(series)), float(q3 - q1)
    if not np.isfinite([center, scale]).all():
        raise ValueError("normalization baseline overflowed")
    if scale == 0 and method == "robust" and series.min() != series.max():
        raise ValueError(f"{column}: nonconstant series has zero IQR; choose a different scaling method")
    return center, scale


CATALOG = [
    {
        "key": f"preprocess.{key}",
        "title": title,
        "function": f"materials_quality.science.preprocessing:{function}",
        "category": "preprocessing",
        "requirement": requirement,
        "table_input": True,
        "data_input": key in {"filter", "units", "normalize"},
        "tables_input": key == "merge",
        "default_config": config,
    }
    for key, title, function, requirement, config in [
        ("filter", "行列筛选", "filter_rows", "行列筛选", {}),
        ("missing", "缺失值处理", "handle_missing", "缺失值处理", {"method": "keep"}),
        ("units", "单位换算", "convert_units", "单位换算", {"source_units": {}, "target_units": {}}),
        ("reshape", "格式转换", "reshape_table", "格式转换", {"method": "types", "types": {}}),
        ("merge", "多表合并", "merge_tables", "多表合并", {"method": "join", "on": ["sample_id"]}),
        ("normalize", "数据归一化", "normalize_table", "数据归一化", {"method": "minmax"}),
    ]
]

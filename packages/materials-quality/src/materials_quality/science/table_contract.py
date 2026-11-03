"""Bounded scientific table declarations, independently hashed from table values.

Contracts describe declared meaning. They do not establish physical attribution or
experimental independence from the number of records in a table.
"""

import hashlib
import json
import math
from copy import deepcopy

import pandas as pd

from materials_quality.units import _unit

SCHEMA = "studyui-table-contract/1"
GRANULARITIES = {"point", "measurement", "peak", "curve", "sample", "experimental_unit", "group_summary"}
ROLES = {
    "curve_id",
    "sample_id",
    "experimental_unit",
    "group",
    "x",
    "response",
    "pair_id",
    "technical_replicate",
    "peak_id",
    "variable",
    "value",
}
MAX_BYTES = 65536
MAX_DEPTH = 16
FIELDS = {
    "schema_version",
    "granularity",
    "roles",
    "experimental_design",
    "aggregation",
    "derived_from",
    "units_state",
    "contract_sha256",
}


def _json(value):
    """Reject non-JSON objects before serialization and bound recursive work."""
    count = 0

    def visit(obj, depth):
        nonlocal count
        count += 1
        if depth > MAX_DEPTH or count > 10000:
            raise ValueError("contract JSON nesting/item limit exceeded")
        if obj is None or type(obj) in (str, bool, int):
            return
        if type(obj) is float and math.isfinite(obj):
            return
        if type(obj) is list:
            for item in obj:
                visit(item, depth + 1)
            return
        if type(obj) is dict and all(type(key) is str for key in obj):
            for item in obj.values():
                visit(item, depth + 1)
            return
        raise ValueError("contract must contain strict finite JSON values")

    visit(value, 0)
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError) as exc:
        raise ValueError("contract must contain finite JSON") from exc
    if len(encoded) > MAX_BYTES:
        raise ValueError("contract JSON byte limit exceeded")
    return encoded


def _hash(contract):
    return hashlib.sha256(
        _json({key: value for key, value in contract.items() if key != "contract_sha256"})
    ).hexdigest()


def _validate(table, contract):
    _json(contract)
    if not isinstance(table, pd.DataFrame):
        raise ValueError("contract requires a DataFrame")
    if type(contract) is not dict or contract.get("schema_version") != SCHEMA:
        raise ValueError("invalid table contract schema")
    if set(contract) != FIELDS:
        raise ValueError("invalid table contract fields")
    if contract.get("contract_sha256") != _hash(contract):
        raise ValueError("table contract sha256 mismatch")
    grain, roles, design = (contract[key] for key in ("granularity", "roles", "experimental_design"))
    if type(grain) is not str or grain not in GRANULARITIES:
        raise ValueError("unsupported contract granularity")
    if type(roles) is not dict or set(roles) - ROLES:
        raise ValueError("unsupported contract role")
    if any(type(column) is not str or column not in table.columns for column in roles.values()):
        raise ValueError("contract roles must name existing columns")
    if not table.columns.is_unique:
        raise ValueError("contract requires unique column names")
    compatible = ({"sample_id", "experimental_unit"}, {"response", "value"})
    if (
        type(design) is dict
        and design.get("confirmed") is True
        and design.get("kind") in ("independent", "paired")
    ):
        compatible += ({"curve_id", "sample_id", "experimental_unit"},)
    for column in set(roles.values()):
        sharing = {role for role, name in roles.items() if name == column}
        if len(sharing) > 1 and not any(sharing <= pair for pair in compatible):
            raise ValueError(f"incompatible contract roles share column {column!r}")
    if type(design) is not dict or set(design) - {"kind", "confirmed", "aggregation_unit", "provenance"}:
        raise ValueError("invalid experimental_design fields")
    if (
        type(design.get("kind")) is not str
        or design.get("kind") not in {"descriptive", "independent", "paired"}
        or type(design.get("confirmed")) is not bool
    ):
        raise ValueError("experimental_design requires kind and confirmed")
    if design["confirmed"] and design["kind"] != "descriptive" and "experimental_unit" not in roles:
        raise ValueError("confirmed experimental design requires experimental_unit role")
    if "aggregation_unit" in design and (
        type(design["aggregation_unit"]) is not str or design["aggregation_unit"] not in roles
    ):
        raise ValueError("experimental_design aggregation_unit must name a declared role")
    if type(contract["units_state"]) is not dict:
        raise ValueError("units_state must be a JSON mapping")
    for field in ("aggregation", "derived_from"):
        if type(contract[field]) is not list or any(type(record) is not dict for record in contract[field]):
            raise ValueError(f"{field} must be a JSON list of records")
    identity = {"curve": "curve_id", "sample": "sample_id", "experimental_unit": "experimental_unit"}.get(
        grain
    )
    for role in {"curve_id", "sample_id", "experimental_unit", "group", "pair_id"} & roles.keys():
        values = table[roles[role]]
        if values.isna().any():
            raise ValueError(f"contract identity role {role} contains missing values")
    if identity in roles:
        key = [roles[identity]]
        if grain == "experimental_unit":
            # Long result tables retain a unit's distinct measured variables.
            # A paired design also retains one observation per condition.
            for role in ("variable", "group" if design["kind"] == "paired" else None):
                if role in roles:
                    key.append(roles[role])
        if table[key].isna().any().any():
            raise ValueError(f"{grain} granularity identity contains missing values")
        if table.duplicated(subset=key).any():
            raise ValueError(f"{grain} granularity requires one record per identity and measured condition")
    # Paired observations may span conditions. Independent units cannot silently
    # occur in multiple treatment groups. Curve identities always name one curve.
    if "group" in roles:
        for role in ("curve_id", "sample_id", "experimental_unit"):
            if role not in roles or (role != "curve_id" and design["kind"] == "paired"):
                continue
            subset = table[[roles[role], roles["group"]]].drop_duplicates()
            if subset[roles[role]].duplicated().any():
                raise ValueError(f"contract {role} crosses group identities")
    return deepcopy(contract)


def make_contract(
    table,
    *,
    granularity,
    roles,
    experimental_design=None,
    aggregation=None,
    derived_from=None,
    units_state=None,
):
    """Create a declaration; no entity or independence is inferred from row count."""
    _json(
        {
            "granularity": granularity,
            "roles": roles,
            "experimental_design": experimental_design,
            "aggregation": aggregation,
            "derived_from": derived_from,
            "units_state": units_state,
        }
    )
    contract = {
        "schema_version": SCHEMA,
        "granularity": granularity,
        "roles": deepcopy(roles),
        "experimental_design": deepcopy(experimental_design)
        if experimental_design is not None
        else {"kind": "descriptive", "confirmed": False},
        "aggregation": deepcopy(aggregation) if aggregation is not None else [],
        "derived_from": deepcopy(derived_from) if derived_from is not None else [],
        "units_state": deepcopy(units_state)
        if units_state is not None
        else {"source": "table_attrs", "units": deepcopy(table.attrs.get("units", {}))},
    }
    contract["contract_sha256"] = _hash(contract)
    return _validate(table, contract)


def read_contract(table):
    """Return a defensive validated copy, or None for a legacy undeclared table."""
    if table is None or "contract" not in table.attrs:
        return None
    return _validate(table, table.attrs["contract"])


def attach_contract(table, contract):
    """Attach a validated declaration to a fresh table without changing the input."""
    validated = _validate(table, contract)
    result = table.copy(deep=True)
    result.attrs = deepcopy(table.attrs)
    result.attrs["contract"] = validated
    return result


def contract_identity(table):
    contract = read_contract(table)
    return None if contract is None else contract["contract_sha256"]


def _merge_unit_declarations(table, *mappings):
    units = {}
    for mapping in mappings:
        if not isinstance(mapping, dict):
            raise ValueError("table units must be a mapping")
        for column, label in mapping.items():
            if column not in table.columns or not isinstance(label, str) or not label.strip():
                raise ValueError("table units must map existing columns to nonempty labels")
            if column in units and label != units[column]:
                try:
                    equal = _unit(label) == _unit(units[column])
                except ValueError:
                    equal = False
                if not equal:
                    raise ValueError(f"conflicting units for {column}: {units[column]!r} and {label!r}")
            units[column] = label
    return units


def restore_contract_units(table, contract, declared_units=None):
    """Restore persistent unit declarations on a fresh table, rejecting conflicts."""
    result = attach_contract(table, contract)
    raw = contract["units_state"].get("units", {})
    if not isinstance(raw, dict):
        raise ValueError("contract units must be a mapping")
    unit_roles = {
        "x_unit": "x",
        "y_unit": "response",
        "strain_unit": "x",
        "stress_unit": "response",
        "value_unit": "response",
    }
    mapped = {}
    for field, label in raw.items():
        column = field if field in table.columns else contract["roles"].get(unit_roles.get(field))
        if column is not None:
            if column in mapped and mapped[column] != label:
                raise ValueError(f"conflicting contract units for {column}")
            mapped[column] = label
    units = _merge_unit_declarations(
        table, mapped, table.attrs.get("units", {}), {} if declared_units is None else declared_units
    )
    if units or "units" in table.attrs:
        result.attrs["units"] = units
    return result


def propagate_contract(source, target, operation, parameters=None):
    """Preserve declared meaning for known operations; clear unsafe inheritance."""
    contract = read_contract(source)
    result = target.copy(deep=True)
    result.attrs = deepcopy(target.attrs)
    result.attrs.pop("contract", None)
    if contract is None:
        return result
    source = restore_contract_units(source, contract)
    _json(parameters)
    parameters = {} if parameters is None else deepcopy(parameters)
    record = {"operation": operation, "contract_sha256": contract["contract_sha256"]}
    roles = deepcopy(contract["roles"])
    grain, design = contract["granularity"], contract["experimental_design"]
    aggregation = deepcopy(contract["aggregation"])
    known = {"rename", "filter", "normalize", "units", "identity", "concat"}
    identity_columns = {column for role, column in roles.items() if role not in {"x", "response", "value"}}
    if operation in {"normalize", "units"}:
        selected = (
            list(parameters.get("target_units", {})) if operation == "units" else parameters.get("columns")
        )
        if selected is None:
            selected = result.select_dtypes(include="number").columns.tolist()
        if identity_columns.intersection(selected):
            known.discard(operation)
    if operation in {"grouped", "aggregate", "group_summary"}:
        grain, design = "group_summary", {"kind": "descriptive", "confirmed": False}
        roles = {"group": roles["group"]} if roles.get("group") in result.columns else {}
        aggregation.append({"operation": operation, "parameters": parameters})
    elif operation in known:
        rename = parameters.get("rename", {})
        if operation in {"filter", "rename", "identity", "concat"}:
            inherited_units = {
                rename.get(column, column): label
                for column, label in source.attrs.get("units", {}).items()
                if rename.get(column, column) in result.columns
            }
            # Result metadata may include new derived columns but must agree on
            # columns whose numerical units the transformation did not change.
            target_units = result.attrs.get("units", {})
            if rename and target_units == source.attrs.get("units", {}):
                # pandas.rename copies attrs verbatim, including labels using
                # the preceding column names. Apply the same explicit rename.
                target_units = inherited_units
            merged_units = _merge_unit_declarations(result, inherited_units, target_units)
            if merged_units or "units" in result.attrs:
                result.attrs["units"] = merged_units
        roles = {
            role: rename.get(column, column)
            for role, column in roles.items()
            if rename.get(column, column) in result.columns
        }
        if "experimental_unit" not in roles and design["kind"] != "descriptive":
            design = {"kind": "descriptive", "confirmed": False}
    else:
        result.attrs["contract_provenance"] = [*source.attrs.get("contract_provenance", []), record]
        result.attrs["contract_warnings"] = [
            *source.attrs.get("contract_warnings", []),
            f"Contract cleared after unsupported transformation {operation}; independence is undeclared.",
        ]
        return result
    updated = make_contract(
        result,
        granularity=grain,
        roles=roles,
        experimental_design=design,
        aggregation=aggregation,
        derived_from=[*contract["derived_from"], record],
        units_state={"source": operation, "units": deepcopy(result.attrs.get("units", {}))},
    )
    return attach_contract(result, updated)

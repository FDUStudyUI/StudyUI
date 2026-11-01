"""Import algorithm parameters into native controls without losing explicit settings."""

import json
from copy import deepcopy

from .catalog import component_class
from .ui_schema import fields_for, form_config
from .ui_types import input_name

_ABSENT = object()


def _at(config, path):
    value = config
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _ABSENT
        value = value[part]
    return value


def _consume(config, path):
    parts = path.split(".")
    current = config
    parents = []
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        parents.append((current, part))
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
    for parent, part in reversed(parents):
        if parent[part] == {}:
            del parent[part]


def _task(key, config, override):
    if key == "stats.predict":
        return "prediction_task", override or (
            "saved" if config.get("model_path") or config.get("manifest_path") else "train"
        )
    if key == "stats.evaluate":
        selected = "train"
        if config.get("model_path") or config.get("manifest_path"):
            selected = "saved"
        if config.get("y_true") and config.get("y_pred"):
            selected = "predictions"
        return "evaluation_task", override or selected
    if override is not None:
        raise ValueError(f"{key} has no saved-model task selector")
    return None, None


def _native_value(spec, value, native):
    kind, converter = spec["kind"], spec.get("converter")
    if kind == "range":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("a range needs two bounds")
        return list(value)
    if kind == "table":
        if converter in {"pairs", "rectangles"}:
            columns = spec["pair_columns"] if converter == "pairs" else ["left", "top", "right", "bottom"]
            if any(not isinstance(row, (list, tuple)) or len(row) != len(columns) for row in value):
                raise ValueError("table coordinates do not match the native columns")
            return [dict(zip(columns, row, strict=True)) for row in value]
        rows = deepcopy(value)
        if converter == "filter_conditions":
            for row in rows:
                if "value" in row:
                    row["value"] = json.dumps(row["value"], ensure_ascii=False, allow_nan=False)
        return rows
    if kind == "list":
        if converter == "column_or_list" and isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("list controls need a list")
        return [str(item) for item in value]
    if kind == "json":
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    if kind == "dict" and converter == "list_mapping":
        if not isinstance(value, dict):
            raise ValueError("mapping controls need an object")
        return {
            key: ",".join(str(item) for item in items) if isinstance(items, list) else items
            for key, items in value.items()
        }
    if kind == "choice":
        if value not in spec["choices"]:
            raise ValueError("unsupported choice")
        return str(value)
    if kind == "bool":
        if type(value) is not bool:
            raise ValueError("boolean controls need a boolean")
        if getattr(native, "options", None) == ["否", "是"]:
            return "是" if value else "否"
        return value
    if converter == "nullable_int" and value is None:
        return "null"
    if kind == "str" and converter in {"nullable_int", "number_or_text", "histogram_bins"}:
        return str(value)
    return deepcopy(value)


def _same(spec, expected, actual):
    if actual is _ABSENT:
        return False
    if spec.get("converter") == "column_or_list":
        expected = expected if isinstance(expected, list) else [expected]
        actual = actual if isinstance(actual, list) else [actual]
    if spec["path"] == "grid":
        try:
            return [float(item) for item in expected] == [float(item) for item in actual]
        except (TypeError, ValueError):
            return False
    # Native integer/float conversion may change Python's numeric representation,
    # but may never equate an explicit boolean with a numeric zero or one.
    if type(expected) is bool and type(actual) is not bool:
        return False
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _same({"path": key}, value, actual[key]) for key, value in expected.items()
        )
    return expected == actual


def config_to_form(key, config, *, task=None):
    """Return native ``Component.set`` values, or exact legacy JSON on ambiguity.

    Additional active form defaults are allowed; every explicitly provided value
    must survive real SDK construction and composition. ``task='saved'`` selects
    manifest inference when the model arrives through a connected upstream report.
    Unknown keys, inactive settings and lossy control conversions retain JSON mode.
    This helper does not discard output directories or any other algorithm key.
    """
    original = deepcopy(config)
    encoded = json.dumps(original, ensure_ascii=False, allow_nan=False)
    fallback = {"ui_mode": "json", "config_json": encoded}
    if not isinstance(config, dict):
        return fallback
    try:
        node = component_class(key)()
        specs = fields_for(key)
        values = {"ui_mode": "form"}
        task_path, selected_task = _task(key, config, task)
        if task_path:
            task_spec = next(spec for spec in specs if spec["path"] == task_path)
            if selected_task not in task_spec["choices"]:
                raise ValueError("unsupported task")
            values[input_name(task_path)] = selected_task
        unconsumed = deepcopy(config)
        provided = []
        for spec in specs:
            if spec.get("ui_only"):
                continue
            value = _at(config, spec["path"])
            if value is _ABSENT:
                continue
            name = input_name(spec["path"])
            native = node._inputs.get(name)
            converted = _native_value(spec, value, native)
            if spec["kind"] == "range":
                values[name + "_min"], values[name + "_max"] = converted
            else:
                values[name] = converted
            if name + "_enabled" in node._inputs:
                values[name + "_enabled"] = "是"
            provided.append((spec, value))
            _consume(unconsumed, spec["path"])
        if unconsumed:
            return fallback
        result = form_config(node.set(**values), key, validate=False)
        if not all(_same(spec, value, _at(result, spec["path"])) for spec, value in provided):
            return fallback
        return values
    except (KeyError, TypeError, ValueError):
        return fallback

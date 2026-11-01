"""Import algorithm parameters into native controls without losing explicit settings."""

import json
from copy import deepcopy

from .catalog import component_class
from .ui_schema import fields_for, form_config
from .ui_types import input_name

_ABSENT = object()

# Reviewed against the algorithm implementations, not the catalog/UI examples.
# An unlisted addition is ambiguous and therefore remains JSON during migration.
_LEGACY_DEFAULTS = {
    "materials.mechanics": {
        "x": "strain",
        "y": "stress",
        "yield_offset": 0.002,
        "fracture_confirmed": False,
        "sort": False,
    },
    "materials.microstructure": {
        "segmentation": "threshold",
        "foreground": "bright",
        "connectivity": 1,
        "min_area_pixels": 1,
    },
    "preprocess.filter": {"logic": "and", "conditions": [], "drop_empty": False, "rename": {}},
    "preprocess.reshape": {"method": "types", "types": {}},
    "preprocess.missing": {"method": "keep"},
    "preprocess.units": {"source_units": {}, "target_units": {}},
    "preprocess.normalize": {"method": "minmax"},
    "preprocess.merge": {
        "method": "join",
        "how": "left",
        "validate": "one_to_one",
        "suffixes": ["_left", "_right"],
        "ignore_index": True,
        "direction": "nearest",
    },
    "io.table_import": {"encoding": "auto", "delimiter": "auto", "header": 0, "sheet": 0},
    "io.text_import": {
        "method": "lines",
        "encoding": "auto",
        "delimiter": "auto",
        "header": 0,
        "skiprows": 0,
    },
    "io.database_import": {"method": "sqlite"},
    "io.pdf_import": {"dpi": 150, "render_all": False, "overwrite": False},
    "io.instrument_import": {"encoding": "auto", "timeout": 60, "overwrite": False},
    "extract.pdf_text": {"dpi": 150, "overwrite": False},
    "extract.pdf_tables": {"dpi": 150, "header": True, "overwrite": False},
    "extract.image_ocr": {"text_score": 0.5, "box_thresh": 0.5},
    "extract.image_tables": {
        "header": True,
        "line_threshold": 180,
        "min_table_width": 40,
        "min_table_height": 30,
        "text_score": 0.5,
        "box_thresh": 0.5,
    },
    "extract.chart_digitize": {
        "calibration.x_scale": "linear",
        "calibration.y_scale": "linear",
        "color_tolerance": 40,
        "pixel_step": 1,
        "max_thickness": 10,
    },
    "extract.convert_file": {
        "encoding": "auto",
        "sheet": 0,
        "delimiter": "auto",
        "dpi": 150,
        "text_score": 0.5,
        "box_thresh": 0.5,
        "overwrite": False,
    },
    "stats.grouped": {"units": {}, "normalize_by_group": False, "output_format": "long"},
    "stats.distribution": {"bins": "auto", "units": {}, "overwrite": False},
    "stats.correlation": {"method": "pearson", "alpha": 0.05},
    "stats.significance": {"method": "welch", "alpha": 0.05, "incomplete_pairs": "error"},
    "stats.multiple": {"method": "holm", "alpha": 0.05, "correction": "holm"},
    "stats.regression": {
        "validation_split": "random",
        "residual_diagnostics": False,
        "linear_trend_ci": False,
        "method": "linear",
        "seed": 42,
        "test_size": 0.2,
        "degree": 2,
        "alpha": 1.0,
        "max_iter": 10000,
        "overwrite": False,
    },
    "stats.predict": {
        "validation_split": "random",
        "residual_diagnostics": False,
        "linear_trend_ci": False,
        "method": "random_forest",
        "seed": 42,
        "test_size": 0.2,
        "n_estimators": 100,
        "C": 10,
        "epsilon": 0.1,
        "kernel": "rbf",
        "overwrite": False,
    },
    "stats.evaluate": {
        "validation_split": "random",
        "residual_diagnostics": False,
        "linear_trend_ci": False,
        "method": "holdout",
        "model_method": "linear",
        "seed": 42,
        "test_size": 0.2,
        "folds": 5,
        "degree": 2,
        "alpha": 1.0,
        "max_iter": 10000,
        "n_estimators": 100,
        "C": 10,
        "epsilon": 0.1,
        "kernel": "rbf",
        "overwrite": False,
    },
    "viz.spectra": {"offset": 0},
    "lit.sources": {"overwrite": False},
}


def _safe_defaults(key, original, actual):
    defaults = _LEGACY_DEFAULTS.get(key, {})

    def additions(before, after, prefix=""):
        for name, value in after.items():
            path = prefix + name
            if name not in before:
                yield path, value
            elif isinstance(value, dict) and isinstance(before[name], dict):
                yield from additions(before[name], value, path + ".")

    for name, value in additions(original, actual):
        if name not in defaults or not _same({"path": name}, defaults[name], value):
            return False
    return True


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
    if (type(expected) is bool) != (type(actual) is bool):
        return False
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _same({"path": key}, value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(
                _same({"path": spec["path"] + "[]"}, first, second)
                for first, second in zip(expected, actual, strict=True)
            )
        )
    return expected == actual


def config_to_form(key, config, *, task=None, strict=False, diagnostics=None):
    """Return native ``Component.set`` values, or exact legacy JSON on ambiguity.

    Additional active form defaults are allowed; every explicitly provided value
    must survive real SDK construction and composition. ``task='saved'`` selects
    manifest inference when the model arrives through a connected upstream report.
    Unknown keys, inactive settings and lossy control conversions retain JSON mode.
    This helper does not discard output directories or any other algorithm key.
    ``strict=True`` additionally permits only reviewed algorithm-equivalent
    defaults, for opt-in legacy migration (UI defaults alone are insufficient).
    """
    original = deepcopy(config)
    encoded = json.dumps(original, ensure_ascii=False, allow_nan=False)
    fallback = {"ui_mode": "json", "config_json": encoded}

    def failed(reason, fields=(), detail=None):
        if diagnostics is not None:
            diagnostics.update(reason=reason, fields=list(fields))
            if detail:
                diagnostics["detail"] = detail
        return fallback

    if not isinstance(config, dict):
        return failed("config_not_object")
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
            return failed("unknown_parameters", unconsumed)
        result = form_config(node.set(**values), key, validate=False)
        lost = [spec["path"] for spec, value in provided if not _same(spec, value, _at(result, spec["path"]))]
        if lost:
            return failed("inactive_or_lossy_parameters", lost)
        if strict and not _safe_defaults(key, config, result):
            return failed(
                "changed_or_unverified_algorithm_defaults", [name for name in result if name not in config]
            )
        return values
    except (KeyError, OverflowError, TypeError, ValueError) as exc:
        return failed("invalid_native_parameter", detail=str(exc))

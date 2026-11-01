"""Build native scientific node forms and compose validated algorithm parameters."""

import json
import math
from copy import deepcopy
from importlib import import_module

import pandas as pd
from lfx.io import (
    BoolInput,
    DataFrameInput,
    DataInput,
    DictInput,
    DropdownInput,
    FileInput,
    FloatInput,
    HandleInput,
    IntInput,
    MultilineInput,
    MultiselectInput,
    Output,
    StrInput,
    TableInput,
)

from .catalog import entries
from .ui_types import input_name

MODULES = ("io", "preprocessing", "materials", "statistics", "visualization", "literature")
COLUMN_NAMES = [
    "sample_id",
    "specimen",
    "group",
    "condition",
    "replicate",
    "x",
    "y",
    "value",
    "strain",
    "stress",
    "temperature",
    "date",
    "time",
    "source_id",
    "text",
]
LOW_FREQUENCY = {
    "sort",
    "smooth_order",
    "peak_distance",
    "output_dir",
    "overwrite",
    "width_mm",
    "height_mm",
    "dpi",
    "formats",
    "color_map",
    "y_label",
}
COLUMN_FIELDS = {
    "x",
    "y",
    "sample",
    "group",
    "column",
    "target",
    "subject",
    "pair_id",
    "order_by",
    "element_column",
    "columns",
    "features",
    "id_columns",
    "index",
    "values",
    "on",
    "by",
    "keys",
    "continuous",
    "y_true",
    "y_pred",
    "id_column",
    "group_column",
}
# These operations combine distinct sources: multiple tables, saved model + new
# samples, reference + instrument, or measured + statistical evidence.
REPORT_COLLECTION_KEYS = {
    "export.report",
    "preprocess.merge",
    "stats.predict",
    "materials.xrd",
    "viz.performance",
    "viz.statistics",
}


def _boolean(value):
    if type(value) is bool:
        return value
    if value in ("true", "True", "是"):
        return True
    if value in ("false", "False", "否"):
        return False
    raise ValueError("请选择是或否")


def _metadata(key):
    for name in MODULES:
        try:
            module = import_module(f".ui_specs_{name}", __package__)
        except ModuleNotFoundError as exc:
            if exc.name == f"{__package__}.ui_specs_{name}":
                continue
            raise
        if key in module.SPECS:
            return module.SPECS[key], module.CONTRACTS[key]
    raise ValueError(f"No native UI specification for {key}")


def fields_for(key):
    return deepcopy(_metadata(key)[0])


def contract_for(key):
    return deepcopy(_metadata(key)[1])


def catalog_item(key):
    return next(item for item in entries() if item["key"] == key)


def _get(value, path, default=None):
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _put(value, path, item):
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in value or not isinstance(value[part], dict):
            value[part] = {}
        value = value[part]
    value[parts[-1]] = deepcopy(item)


def _parse_json(value, *, object_only=False):
    def invalid(token):
        raise ValueError(f"参数不接受非有限数值 {token}")

    try:
        parsed = (
            json.loads(value or "{}", parse_constant=invalid) if isinstance(value, str) else deepcopy(value)
        )
        json.dumps(parsed, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("高级参数需要有效 JSON；普通参数可切回表单模式填写。") from exc
    if object_only and not isinstance(parsed, dict):
        raise ValueError("高级 JSON 参数必须是对象。")
    return parsed


def effective_mode(component):
    params = getattr(component, "_parameters", {})
    if params.get("ui_mode") in {"form", "json"}:
        return params["ui_mode"]
    raw = params.get("config_json")
    if raw not in (None, "", "{}"):
        return "json"
    if any(name.startswith("cfg_") for name in params):
        return "form"
    return getattr(component, "ui_mode", "form")


def _active(spec, config):
    return all(_get(config, path) in allowed for path, allowed in spec.get("when", {}).items())


def _optional_numeric(spec, defaults):
    default = spec.get("default")
    if default is None:
        default = _get(defaults, spec["path"])
    return spec["kind"] in {"int", "float", "range"} and default is None and not spec.get("required")


def _enabled(component, name):
    parameters = getattr(component, "_parameters", {})
    if name + "_enabled" in parameters:
        return _boolean(parameters[name + "_enabled"])
    supplied = name in parameters or name + "_min" in parameters or name + "_max" in parameters
    return supplied or _boolean(getattr(component, name + "_enabled", False))


def _integer(value):
    if isinstance(value, bool):
        raise ValueError("整数参数不能是布尔值")
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError("请填写有限整数")
    return int(number)


def _number(value):
    if isinstance(value, bool):
        raise ValueError("数值参数不能是布尔值")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("请填写有限数值")
    return number


def _convert(value, spec):
    if spec["kind"] == "bool":
        return _boolean(value)
    converter = spec.get("converter")
    if converter == "pairs":
        columns = spec["pair_columns"]
        return [[_number(row[column]) for column in columns] for row in value]
    if converter == "rectangles":
        return [[_integer(row[c]) for c in ("left", "top", "right", "bottom")] for row in value]
    if converter == "int":
        return [_integer(x) for x in value] if isinstance(value, list) else _integer(value)
    if converter in {"int_list", "float_list"}:
        cast = _integer if converter == "int_list" else _number
        return [cast(x) for x in value]
    if converter == "nullable_int":
        return None if str(value).lower() in {"none", "null"} else _integer(value)
    if converter == "number_or_text":
        try:
            number = _number(value)
            return int(number) if number.is_integer() else number
        except ValueError:
            return value
    if converter == "column_or_list":
        values = value if isinstance(value, list) else [x.strip() for x in str(value).split(",") if x.strip()]
        return values[0] if len(values) == 1 else values
    if converter == "histogram_bins":
        if str(value).strip().isdigit():
            result = _integer(value)
            if result < 1:
                raise ValueError("直方图区间数必须大于 0")
            return result
        if value not in {"auto", "fd", "doane", "scott", "stone", "rice", "sturges", "sqrt"}:
            raise ValueError("请选择直方图分箱规则或填写正整数")
        return value
    if converter == "list_mapping":
        return {
            key: item if isinstance(item, list) else [x.strip() for x in str(item).split(",") if x.strip()]
            for key, item in value.items()
        }
    if converter == "filter_conditions":
        records = []
        for row in value:
            item = dict(row)
            raw = item.get("value")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except (ValueError, TypeError):
                    if item.get("op") in {"in", "not_in"}:
                        values = []
                        for token in raw.split(","):
                            token = token.strip()
                            try:
                                values.append(json.loads(token))
                            except ValueError:
                                values.append(token)
                        raw = values
            item["value"] = raw
            records.append(item)
        return records
    return value


def form_config(component, key, *, validate=True):
    defaults = deepcopy(catalog_item(key)["default_config"])
    if effective_mode(component) == "json":
        value = getattr(component, "config_json", None)
        raw = getattr(component, "_parameters", {}).get("config_json")
        if isinstance(raw, dict):
            value = raw
        return _parse_json(value, object_only=True)
    specs = fields_for(key)
    # Controllers are merged first, independent of descriptor display order.
    ordered = sorted(specs, key=lambda s: bool(s.get("when")))
    config = {}
    for spec in ordered:
        if not _active(spec, config):
            continue
        name, kind = input_name(spec["path"]), spec["kind"]
        if _optional_numeric(spec, defaults) and not _enabled(component, name):
            continue
        if kind == "range":
            lower = getattr(component, name + "_min", None)
            upper = getattr(component, name + "_max", None)
            if lower is None and upper is None:
                if validate and spec.get("required"):
                    raise ValueError(f"请填写{spec['label']}的下限和上限")
                continue
            if lower is None or upper is None:
                if validate:
                    raise ValueError(f"请同时填写{spec['label']}的下限和上限")
                continue
            value = [_number(lower), _number(upper)]
            if validate and lower >= upper:
                raise ValueError(f"{spec['label']}：下限必须小于上限")
        else:
            value = getattr(component, name, deepcopy(spec.get("default")))
            if isinstance(value, pd.DataFrame):
                value = value.to_dict("records")
            empty = value is None or isinstance(value, str) and value == ""
            empty = empty or isinstance(value, (list, dict)) and not value and spec.get("default") is None
            if empty:
                if validate and spec.get("required"):
                    raise ValueError(f"请填写{spec['label']}")
                continue
            try:
                if kind == "json":
                    value = _parse_json(value)
                elif kind == "int":
                    value = _integer(value)
                elif kind == "float":
                    value = _number(value)
                elif kind == "bool":
                    value = _boolean(value)
                elif (
                    kind == "str"
                    and isinstance(value, str)
                    and spec["path"] not in {"delimiter", "separator", "sep"}
                ):
                    value = value.strip()
                value = _convert(value, spec)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{spec['label']}：{exc}") from exc
        _put(config, spec["path"], value)
    for spec in specs:
        if spec.get("ui_only"):
            config.pop(spec["path"], None)
    return config


def _field_inputs(spec, default_config, controllers=()):
    name, kind = input_name(spec["path"]), spec["kind"]
    default = deepcopy(spec.get("default"))
    if default is None:
        default = deepcopy(_get(default_config, spec["path"]))
    common = {
        "name": name,
        "display_name": spec["label"],
        "required": False,
        "advanced": spec["advanced"] or spec["path"] in LOW_FREQUENCY,
        "show": _active(spec, default_config),
        "info": spec["info"],
        "input_types": [],
    }
    optional = _optional_numeric(spec, default_config)
    enable = []
    if optional:
        enable = [
            DropdownInput(
                name=name + "_enabled",
                display_name="自定义" + spec["label"],
                value="否",
                options=["否", "是"],
                real_time_refresh=True,
                advanced=common["advanced"],
                show=common["show"],
                input_types=[],
                info="关闭时使用方法的自动/默认设置；开启后填写数值。",
            )
        ]
        common["show"] = False
    if kind == "range":
        bounds = default if isinstance(default, (tuple, list)) and len(default) == 2 else [None, None]
        return enable + [
            FloatInput(
                **{**common, "name": name + suffix, "display_name": spec["label"] + label}, value=value
            )
            for suffix, label, value in [("_min", "下限", bounds[0]), ("_max", "上限", bounds[1])]
        ]
    if kind == "choice":
        options = [str(v) for v in spec["choices"]]
        return [
            DropdownInput(
                **common,
                options=options,
                value=str(default) if default is not None else None,
                real_time_refresh=True,
            )
        ]
    if kind == "list":
        values = [] if default is None else [str(v) for v in default]
        if spec.get("converter") in {"int_list", "float_list"} or spec["path"] in {
            "grid",
            "suffixes",
            "converter",
        }:
            return [StrInput(**common, is_list=True, value=values)]
        return [
            MultiselectInput(
                **common,
                options=spec.get("suggestions", COLUMN_NAMES if "column" in spec["path"] else []),
                combobox=True,
                value=values,
            )
        ]
    if kind == "dict":
        return [DictInput(**common, value={} if default is None else default)]
    if kind == "table":
        schema = [
            {**column, "edit_mode": column.get("edit_mode", "inline")}
            for column in spec.get("table_schema", [])
        ]
        return [
            TableInput(
                **common,
                value=[] if default is None else default,
                table_schema=schema,
                trigger_text="编辑" + spec["label"],
            )
        ]
    if kind == "json":
        return [
            MultilineInput(
                **{**common, "advanced": True},
                value="" if default is None else json.dumps(default, ensure_ascii=False),
            )
        ]
    if kind in {"int", "float", "bool"}:
        if kind == "bool" and spec["path"] in controllers:
            return [
                DropdownInput(
                    **common, options=["否", "是"], value="是" if default else "否", real_time_refresh=True
                )
            ]
        cls = {"int": IntInput, "float": FloatInput, "bool": BoolInput}[kind]
        return enable + [cls(**common, value=False if kind == "bool" and default is None else default)]
    column = spec["path"].split(".")[-1] in COLUMN_FIELDS
    if column:
        return [
            DropdownInput(
                **common, options=COLUMN_NAMES, combobox=True, value=default or "", real_time_refresh=True
            )
        ]
    return [StrInput(**common, value="" if default is None else default)]


def science_inputs(key, default):
    item, contract, specs = catalog_item(key), contract_for(key), fields_for(key)
    result = []
    if item["table_input"]:
        result.append(DataFrameInput(name="input_table", display_name="输入表格", required=False))
    if item["data_input"]:
        result.append(DataInput(name="input_data", display_name="输入数据 / 文件与证据", required=False))
    elif item["table_input"] or item["tables_input"]:
        result.append(
            DataInput(
                name="input_data",
                display_name="上游追溯（可选）",
                advanced=True,
                required=False,
                info="连接上游结果报告以保留来源和单位；算法的主输入是表格。",
            )
        )
    if item["tables_input"]:
        result.append(
            HandleInput(
                name="input_tables",
                display_name="待合并表格（可多接）",
                input_types=["DataFrame"],
                is_list=True,
            )
        )
    if key in REPORT_COLLECTION_KEYS:
        result.append(
            DataInput(
                name="reports",
                display_name="报告来源（可多接）",
                is_list=True,
                value=[],
                advanced=key != "export.report",
                info="连接各个上游结果报告以保留多来源追溯；不替代输入表格。",
            )
        )
    if contract["upload_types"]:
        result.append(
            FileInput(
                name="source_file",
                display_name="上传源文件",
                file_types=contract["upload_types"],
                required=False,
                info="上传一个文件即可；上传文件优先于本机路径。",
            )
        )
    controller_defaults = deepcopy(default)
    for spec in specs:
        if spec.get("default") is not None and not spec.get("when"):
            _put(controller_defaults, spec["path"], spec["default"])
    controllers = {path for spec in specs for path in spec.get("when", {})}
    for spec in specs:
        result.extend(_field_inputs(spec, controller_defaults, controllers))
    result.extend(
        [
            DropdownInput(
                name="ui_mode",
                display_name="参数配置方式",
                options=["form", "json"],
                value="form",
                advanced=True,
                info="form：使用界面表单；json：使用完整高级 JSON，兼容已有流程。",
                real_time_refresh=True,
                input_types=[],
            ),
            MultilineInput(
                name="config_json",
                display_name="高级 JSON（旧流程兼容）",
                value="{}",
                advanced=True,
                show=False,
                info="仅在 json 模式使用；普通任务直接填写表单。",
                input_types=[],
            ),
        ]
    )
    return result


def science_outputs(key, config=None):
    contract = contract_for(key)
    config = config or catalog_item(key)["default_config"]
    table = contract["table_output"]
    if contract.get("table_methods") is not None:
        table = table and _get(config, contract.get("method_path", "method")) in contract["table_methods"]
    definitions = [("report", "结果与追溯", "build_report"), ("summary", "运行摘要", "build_summary")]
    if table:
        definitions.insert(0, ("table", "结果表格", "build_table"))
    if contract["artifacts_output"]:
        definitions.append(("artifacts", "生成文件", "build_artifacts"))
    return [
        Output(name=name, display_name=label, method=method, group_outputs=True)
        for name, label, method in definitions
    ]


def refresh_config(component, key, build_config, field_value, field_name):
    fields = fields_for(key)
    config = deepcopy(catalog_item(key)["default_config"])
    for spec in fields:
        value = spec.get("default")
        saved = build_config.get(input_name(spec["path"]), {})
        value = saved.get("value", value)
        if input_name(spec["path"]) == field_name:
            value = field_value
        if value is not None:
            try:
                _put(config, spec["path"], _convert(value, spec))
            except (TypeError, ValueError):
                pass
    mode = field_value if field_name == "ui_mode" else build_config.get("ui_mode", {}).get("value", "form")
    for spec in fields:
        names = [input_name(spec["path"])]
        if spec["kind"] == "range":
            names = [names[0] + "_min", names[0] + "_max"]
        for name in names:
            if name in build_config:
                show = mode == "form" and _active(spec, config)
                if _optional_numeric(spec, catalog_item(key)["default_config"]):
                    enable_name = input_name(spec["path"]) + "_enabled"
                    if enable_name in build_config:
                        build_config[enable_name]["show"] = show
                    enabled = (
                        field_value
                        if field_name == enable_name
                        else build_config.get(enable_name, {}).get("value", False)
                    )
                    show = show and _boolean(enabled)
                build_config[name]["show"] = show
    if "config_json" in build_config:
        build_config["config_json"]["show"] = mode == "json"
    table = field_value if field_name == "input_table" else getattr(component, "input_table", None)
    if isinstance(table, pd.DataFrame):
        columns = [str(c) for c in table.columns]
        for spec in fields:
            name = input_name(spec["path"])
            if (
                spec["path"].split(".")[-1] in COLUMN_FIELDS
                and name in build_config
                and "options" in build_config[name]
                and build_config[name].get("combobox")
            ):
                build_config[name]["options"] = columns
    return build_config


class ScienceFormMixin:
    """Native SDK glue; the scientific functions never depend on GUI state."""

    def _process_connection_or_parameters(self, key, value):
        if isinstance(value, list) and not value and key in self._inputs:
            return self._process_connection_or_parameter(key, value)
        return super()._process_connection_or_parameters(key, value)

    def to_frontend_node(self, *args, **kwargs):
        mode = effective_mode(self)
        self._sync_conditional_outputs()
        result = super().to_frontend_node(*args, **kwargs)
        result["data"]["node"]["field_order"] = [field.name for field in self.inputs]
        template = result["data"]["node"]["template"]
        for spec in fields_for(self.ui_operation_key):
            name = input_name(spec["path"])
            if name + "_enabled" in template:
                template[name + "_enabled"]["value"] = "是" if _enabled(self, name) else "否"
        template["ui_mode"]["value"] = mode
        refresh_config(self, self.ui_operation_key, template, mode, "ui_mode")
        # Langflow's canvas hides advanced ports. A connected optional provenance
        # input must remain rendered or import can remove its incoming edge.
        for name in ("input_data", "reports"):
            value = self._parameters.get(name)
            present = value is not None and not (isinstance(value, (list, str)) and not value)
            present = present or any(
                edge.get("target") == self.get_id()
                and edge.get("data", {}).get("targetHandle", {}).get("fieldName") == name
                for edge in self._edges
            )
            if present and name in template:
                template[name]["advanced"] = False
        return result

    def _sync_conditional_outputs(self):
        key = getattr(self, "ui_operation_key", None)
        if key and contract_for(key).get("table_methods") is not None:
            outputs = science_outputs(key, form_config(self, key, validate=False))
            self._set_output_types(outputs)
            self.outputs = outputs
            self._outputs_map = {value.name: value for value in outputs}

    def set(self, *args, **kwargs):
        result = super().set(*args, **kwargs)
        self._sync_conditional_outputs()
        return result

    def update_outputs(self, frontend_node, field_name, field_value):
        key = self.ui_operation_key
        contract = contract_for(key)
        if contract.get("table_methods") is not None:
            template = frontend_node.get("template", {})
            path = contract.get("method_path", "method")
            name = input_name(path)
            value = field_value if field_name == name else template.get(name, {}).get("value")
            mode = template.get("ui_mode", {}).get("value", "form")
            if mode == "json":
                try:
                    value = _get(_parse_json(template.get("config_json", {}).get("value", "{}")), path)
                except ValueError:
                    pass
            config = deepcopy(catalog_item(key)["default_config"])
            if value is not None:
                _put(config, path, value)
            frontend_node["outputs"] = science_outputs(key, config)
        return frontend_node

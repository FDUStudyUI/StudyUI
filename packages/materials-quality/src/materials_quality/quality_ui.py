"""Native editors for the original quality nodes; no scientific extras required."""

from lfx.io import (
    BoolInput,
    DictInput,
    DropdownInput,
    FloatInput,
    MultilineInput,
    MultiselectInput,
    StrInput,
    TableInput,
)

FORM = "form"
JSON = "json"
CHECKS = ["schema", "missing", "types", "units", "duplicates", "outliers"]
LEGACY_FIELDS = {
    "context": ["rules_json"],
    "schema": ["required_columns_json", "aliases_json", "schema_template_json"],
    "missing": ["columns_json", "missing_tokens_json", "group_by_json"],
    "types": ["expectations_json"],
    "units": ["source_units_json", "expected_units_json", "columns_json"],
    "duplicates": ["columns_json", "numeric_tolerances_json"],
    "outliers": ["columns_json", "bounds_json", "group_by_json"],
}
CHECK_FIELDS = {
    "schema": {"required_columns", "alias_rules", "constraint_rules"},
    "missing": {"columns", "missing_tokens", "group_by"},
    "types": {"infer_types", "field_rules"},
    "units": {"unit_rules", "convert_values", "columns"},
    "duplicates": {"duplicate_keys", "match_similar", "similarity_threshold", "numeric_tolerances"},
    "outliers": {
        "outlier_columns",
        "detection_method",
        "constraint_rules",
        "iqr_multiplier",
        "mad_threshold",
        "group_by",
    },
}
JSON_COMMON_FIELDS = {
    "types": {"infer_types"},
    "units": {"convert_values"},
    "duplicates": {"match_similar", "similarity_threshold"},
    "outliers": {"detection_method", "iqr_multiplier", "mad_threshold"},
}


def config_mode(node):
    explicit = getattr(node, "_parameters", {})
    if "ui_mode" in explicit:
        mode = node.ui_mode
    elif any(name in explicit for name in LEGACY_FIELDS[node.quality_check]):
        mode = JSON
    else:
        mode = getattr(node, "ui_mode", FORM)
    if mode not in {FORM, JSON}:
        raise ValueError("ui_mode: 请选择 form（表单）或 json（高级 JSON）")
    return mode


class QualityFormMixin:
    """Persist effective legacy mode so graph serialization cannot activate defaults."""

    def _process_connection_or_parameters(self, key, value):
        # LFX 1.13 mistakes [] for a list of component connections and drops it.
        # Empty native lists/tables are meaningful explicit configuration values.
        if isinstance(value, list) and not value and key in self._inputs:
            return self._process_connection_or_parameter(key, value)
        return super()._process_connection_or_parameters(key, value)

    def to_frontend_node(self, *args, **kwargs):
        result = super().to_frontend_node(*args, **kwargs)
        result["data"]["node"]["field_order"] = [field.name for field in self.inputs]
        template = result["data"]["node"]["template"]
        self.update_build_config(template, config_mode(self), "ui_mode")
        return result

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name in build_config:
            build_config[field_name]["value"] = field_value

        def value(name):
            return build_config.get(name, {}).get("value", getattr(self, name, None))

        mode = value("ui_mode")
        checks = value("enabled_checks") if self.quality_check == "context" else [self.quality_check]
        visible = set().union(*(CHECK_FIELDS[c] for c in (checks or []) if c in CHECK_FIELDS))
        if self.quality_check == "context":
            # Missing markers and grouping apply across several shared checks.
            visible |= {"enabled_checks", "missing_tokens", "group_by"}
            if "missing" not in (checks or []):
                visible.discard("columns")
        if value("infer_types"):
            visible.discard("field_rules")
        if not value("match_similar"):
            visible -= {"similarity_threshold", "numeric_tolerances"}
        if "outliers" in (checks or []):
            method = value("detection_method")
            if method != "range" and "schema" not in (checks or []):
                visible.discard("constraint_rules")
            if method != "iqr":
                visible.discard("iqr_multiplier")
            if method != "mad":
                visible.discard("mad_threshold")
        form_fields = set().union(*CHECK_FIELDS.values()) | {"enabled_checks"}
        for name in form_fields & build_config.keys():
            common = JSON_COMMON_FIELDS.get(self.quality_check, set())
            build_config[name]["show"] = name in visible and (mode == FORM or name in common)
        for name in LEGACY_FIELDS[self.quality_check]:
            if name in build_config:
                build_config[name]["show"] = mode == JSON
                build_config[name]["advanced"] = mode != JSON
        return build_config


def _list(name, label, value=None, info=""):
    return StrInput(
        name=name, display_name=label, is_list=True, value=[] if value is None else value, info=info
    )


def _table(name, label, columns, value=None, info=""):
    schema = [
        {"name": key, "display_name": label, "type": kind, "edit_mode": "inline"}
        for key, label, kind in columns
    ]
    return TableInput(
        name=name,
        display_name=label,
        value=value or [],
        table_schema=schema,
        trigger_text="编辑规则表",
        info=info,
    )


def form_inputs(check):
    inputs = [
        DropdownInput(
            name="ui_mode",
            display_name="配置方式",
            options=[FORM, JSON],
            value=FORM,
            real_time_refresh=True,
            info="form：使用表单，忽略 JSON。json：只用高级 JSON，忽略表单规则。连接共享规则时以上均忽略。",
        )
    ]
    if check == "context":
        inputs += [
            MultiselectInput(
                name="enabled_checks",
                display_name="共享规则包含的检查",
                options=CHECKS,
                value=["missing"],
                real_time_refresh=True,
                info="这里只配置规则，不会自动添加或执行检查节点；需另加对应检查节点并连接共享规则端口。",
            )
        ]
    if check in {"context", "schema"}:
        inputs += [
            _list("required_columns", "必需字段", ["sample_id"], "逐项输入真实列名。"),
            _table("alias_rules", "字段别名", [("column", "标准字段", "str"), ("alias", "别名", "str")]),
        ]
    if check in {"context", "missing"}:
        inputs += [
            _list("columns", "缺失检查列", info="留空检查所有列。"),
            _list(
                "missing_tokens",
                "缺失标记",
                [""],
                "每项一个标记；空字符串表示空白文本。删除全部条目仅检查原生空值，不默认把 NA 当缺失。",
            ),
        ]
    if check in {"context", "missing", "outliers"}:
        inputs += [_list("group_by", "分组列", info="留空对全表检查；填写列名后分组统计。")]
    if check in {"context", "types"}:
        inputs += [
            BoolInput(
                name="infer_types",
                display_name="推断字段类型",
                value=False,
                real_time_refresh=True,
                info="只生成观察值类型建议；启用时忽略字段类型规则表。",
            ),
            _table(
                "field_rules",
                "字段类型规则",
                [
                    ("column", "字段", "str"),
                    ("type", "类型", "str"),
                    ("format", "日期格式", "str"),
                    ("allowed", "分类值（每行一个）", "str"),
                ],
                [{"column": "value", "type": "number"}],
                "类型：number/integer/string/boolean/datetime/category；日期填 %Y-%m-%d，分类值用换行分隔。",
            ),
        ]
    if check in {"context", "schema", "outliers"}:
        inputs += [
            _table(
                "constraint_rules",
                "数值约束与范围",
                [
                    ("column", "字段", "str"),
                    ("min", "下限（可空）", "float"),
                    ("max", "上限（可空）", "float"),
                ],
                info="每行一个字段；0 是有效边界。用于结构约束和 range 异常检查。",
            )
        ]
    if check in {"context", "units"}:
        inputs += [
            _table(
                "unit_rules",
                "单位规则",
                [
                    ("column", "字段", "str"),
                    ("source_unit", "原始单位（可空）", "str"),
                    ("expected_unit", "目标单位", "str"),
                ],
                [{"column": "stress", "source_unit": "", "expected_unit": "Pa"}],
                "如 MPa → Pa、degC → K；原始单位可留空以检查单元格声明。",
            ),
            BoolInput(
                name="convert_values",
                display_name="生成单位换算表",
                value=False,
                info="显式启用才生成换算副本。报告 metrics.converted=false 时换算端口为空，请先查看报告。",
            ),
        ]
        if check == "units":
            inputs += [_list("columns", "检查列", info="留空检查单位规则表中的所有字段。")]
    if check in {"context", "duplicates"}:
        inputs += [
            _list("duplicate_keys", "重复判定键", info="留空按整行判重；不会删除记录。"),
            BoolInput(name="match_similar", display_name="匹配相似记录", value=False, real_time_refresh=True),
            FloatInput(name="similarity_threshold", display_name="相似度阈值", value=0.9),
            DictInput(
                name="numeric_tolerances",
                display_name="各字段数值容差",
                value={},
                info="键为字段名，值为非负数；0 表示精确匹配。",
            ),
        ]
    if check in {"context", "outliers"}:
        inputs += [
            _list("outlier_columns", "异常检查数值列", ["value"], "必须明确指定数值字段。"),
            DropdownInput(
                name="detection_method",
                display_name="异常检查方法",
                options=["range", "iqr", "mad"],
                value="iqr",
                real_time_refresh=True,
            ),
            FloatInput(name="iqr_multiplier", display_name="IQR 倍数", value=1.5),
            FloatInput(name="mad_threshold", display_name="MAD 稳健 Z 阈值", value=3.5),
        ]
    return inputs


def legacy_inputs(check):
    defaults = {
        "rules_json": '{"missing_tokens":[""],"checks":{"missing":{}}}',
        "required_columns_json": '["sample_id"]',
        "expectations_json": '{"value":"number"}',
        "missing_tokens_json": '[""]',
        "expected_units_json": '{"stress":"Pa"}',
    }
    lists = {"columns_json", "group_by_json"}
    if check == "outliers":
        defaults["columns_json"] = '["value"]'
    return [
        MultilineInput(
            name=name,
            display_name=f"高级 {name}",
            advanced=True,
            value=defaults.get(name, "[]" if name in lists else "{}"),
            info="仅 json 配置方式生效；兼容旧流程字段。",
        )
        for name in LEGACY_FIELDS[check]
    ]


def _names(value, name, *, allow_empty=False):
    if not isinstance(value, list) or any(
        not isinstance(x, str) or (not allow_empty and not x.strip()) for x in value
    ):
        raise ValueError(f"{name}: 请逐项填写文本")
    return list(value)


def _rows(node, name):
    value = getattr(node, name)
    if not isinstance(value, list):
        raise ValueError(f"{name}: 请使用规则表，每行一个字段")
    result = {}
    for row in value:
        row = row.data if hasattr(row, "data") else row
        if not isinstance(row, dict) or not isinstance(row.get("column"), str) or not row["column"].strip():
            raise ValueError(f"{name}: 每行需要非空字段 column")
        column = row["column"]
        if column in result:
            raise ValueError(f"{name}: 字段 {column} 重复，请合并规则")
        result[column] = row
    return result


def _bounds(node):
    result = {}
    for column, row in _rows(node, "constraint_rules").items():
        bounds = {key: row[key] for key in ("min", "max") if row.get(key) is not None and row.get(key) != ""}
        if not bounds:
            raise ValueError(f"constraint_rules: {column} 至少填写一个边界")
        for key, value in bounds.items():
            if isinstance(value, bool):
                raise ValueError(f"constraint_rules: {column} 边界必须为数值")
            bounds[key] = float(value)
        result[column] = bounds
    return result


def _form_parameters(node, check):
    if check == "missing":
        return {
            "columns": _names(node.columns, "columns") or None,
            "missing_tokens": _names(node.missing_tokens, "missing_tokens", allow_empty=True),
            "group_by": _names(node.group_by, "group_by") or None,
        }
    if check == "schema":
        aliases = {}
        for row in node.alias_rules:
            if not isinstance(row, dict) or not row.get("column") or not row.get("alias"):
                raise ValueError("alias_rules: 每行需要标准字段和别名")
            aliases.setdefault(row["column"], []).append(row["alias"])
        bounds = _bounds(node)
        properties = {
            column: {
                "type": "number",
                **{("minimum" if k == "min" else "maximum"): v for k, v in rule.items()},
            }
            for column, rule in bounds.items()
        }
        return {
            "required_columns": _names(node.required_columns, "required_columns"),
            "aliases": aliases,
            "schema_template": {"type": "object", "properties": properties} if properties else None,
        }
    if check == "types":
        if node.infer_types:
            return {"infer": True}
        rules = {}
        for column, row in _rows(node, "field_rules").items():
            rule = {"type": row.get("type")}
            if rule["type"] == "datetime":
                rule["format"] = row.get("format", "")
            if rule["type"] == "category":
                value = row.get("allowed", "")
                rule["allowed"] = value.splitlines() if isinstance(value, str) else value
            rules[column] = rule
        return {"expectations": rules}
    if check == "units":
        rows = _rows(node, "unit_rules")
        return {
            "source_units": {c: r["source_unit"] for c, r in rows.items() if r.get("source_unit")},
            "expected_units": {c: r.get("expected_unit", "") for c, r in rows.items()},
            "columns": (_names(node.columns, "columns") or None) if node.quality_check != "context" else None,
            "convert_values": node.convert_values,
        }
    if check == "duplicates":
        return {
            "columns": _names(node.duplicate_keys, "duplicate_keys") or None,
            "similarity_threshold": node.similarity_threshold if node.match_similar else None,
            "numeric_tolerances": node.numeric_tolerances,
        }
    return {
        "columns": _names(node.outlier_columns, "outlier_columns"),
        "method": node.detection_method,
        "bounds": _bounds(node) if node.detection_method == "range" else {},
        "multiplier": node.iqr_multiplier if node.detection_method == "iqr" else 1.5,
        "mad_threshold": node.mad_threshold if node.detection_method == "mad" else 3.5,
        "group_by": _names(node.group_by, "group_by") or None,
    }


def quality_parameters(node, check):
    from materials_quality.langflow_support import column_list, parse_json

    if config_mode(node) == FORM:
        return _form_parameters(node, check)
    if check == "schema":
        return {
            "required_columns": parse_json(node.required_columns_json, "required_columns_json", list),
            "aliases": parse_json(node.aliases_json, "aliases_json", dict),
            "schema_template": parse_json(node.schema_template_json, "schema_template_json", dict) or None,
        }
    if check == "missing":
        return {
            "columns": column_list(node.columns_json),
            "missing_tokens": parse_json(node.missing_tokens_json, "missing_tokens_json", list),
            "group_by": column_list(node.group_by_json, "group_by_json"),
        }
    if check == "types":
        return (
            {"infer": True}
            if node.infer_types
            else {"expectations": parse_json(node.expectations_json, "expectations_json", dict)}
        )
    if check == "units":
        return {
            "source_units": parse_json(node.source_units_json, "source_units_json", dict),
            "expected_units": parse_json(node.expected_units_json, "expected_units_json", dict),
            "columns": column_list(node.columns_json),
            "convert_values": node.convert_values,
        }
    if check == "duplicates":
        return {
            "columns": column_list(node.columns_json),
            "similarity_threshold": node.similarity_threshold if node.match_similar else None,
            "numeric_tolerances": parse_json(node.numeric_tolerances_json, "numeric_tolerances_json", dict),
        }
    columns = column_list(node.columns_json)
    if columns is None:
        raise ValueError("columns_json: explicitly select numeric columns")
    return {
        "columns": columns,
        "method": node.detection_method,
        "bounds": parse_json(node.bounds_json, "bounds_json", dict),
        "multiplier": node.iqr_multiplier,
        "mad_threshold": node.mad_threshold,
        "group_by": column_list(node.group_by_json, "group_by_json"),
    }


def shared_rules(node):
    from materials_quality.langflow_support import parse_json

    if config_mode(node) == JSON:
        return parse_json(node.rules_json, "rules_json", dict)
    selected = _names(node.enabled_checks, "enabled_checks")
    if not selected or set(selected) - set(CHECKS):
        raise ValueError("enabled_checks: 请至少选择一种支持的检查，并添加对应检查节点")
    checks = {}
    for check in selected:
        parameters = _form_parameters(node, check)
        parameters.pop("group_by", None)
        parameters.pop("missing_tokens", None)
        checks[check] = parameters
    return {
        "missing_tokens": _names(node.missing_tokens, "missing_tokens", allow_empty=True),
        "group_by": _names(node.group_by, "group_by"),
        "checks": checks,
    }

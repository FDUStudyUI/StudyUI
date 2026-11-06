"""Read, summarize, validate, and stage safe Langflow workflow edits."""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import re
import uuid

MAX_ACTIONS = 24
MAX_CONFIG_BYTES = 32_000
NODE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
SECRET_HINTS = ("password", "secret", "api_key", "authorization", "credential")
SECRET_TOKEN_NAMES = {
    "token",
    "api_token",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "id_token",
    "credential_token",
}
ALLOWED_OPS = {"add_node", "remove_node", "set_node_config", "connect", "disconnect"}


def flow_digest(flow):
    payload = {key: flow.get(key) for key in ("name", "description", "data", "is_component")}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_secret(name, field):
    lowered = str(name).casefold()
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name)).casefold().replace("-", "_")
    field_type = str(field.get("type", "")).casefold() if isinstance(field, dict) else ""
    return (
        any(word in lowered for word in SECRET_HINTS)
        or normalized in SECRET_TOKEN_NAMES
        or normalized.endswith("_token")
        or field_type in {"password", "secret"}
    )


def is_secret_name(name):
    """Identify credential fields without hiding scientific fields like missing_tokens."""
    return _is_secret(name, {})


def _safe_value(name, field, value):
    if _is_secret(name, field):
        return "[已隐藏]"
    lowered = str(name).casefold()
    normalized_name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name)).casefold().replace("-", "_")
    data_hints = {
        "base64",
        "bundle",
        "file_path",
        "filepath",
        "dataset",
        "dataframe",
        "csv_data",
        "json_data",
        "raw_data",
        "record_data",
        "row_data",
        "content",
        "contents",
        "payload",
        "binary",
        "bytes",
        "records",
        "record",
        "rows",
        "row",
        "data",
        "csv",
        "json",
    }
    if normalized_name in data_hints or data_hints.intersection(normalized_name.split("_")) - {
        "data",
        "csv",
        "json",
    }:
        return "[数据或内嵌资源；未发送给模型]"
    if isinstance(value, str):
        if len(value) > 1200:
            return f"[长文本，{len(value)} 字符；未发送给模型]"
        if re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", value):
            return re.split(r"[\\/]", value.rstrip("\\/"))[-1]
        if any(token in lowered for token in ("path", "directory", "filename")) and value:
            return (
                re.split(r"[\\/]", value.rstrip("\\/"))[-1]
                if ":\\" in value or value.startswith("/")
                else value
            )
    if isinstance(value, dict):
        if len(value) > 40:
            return "[大型对象；未发送给模型]"
        return {str(key): _safe_value(key, {}, item) for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > 40:
            return f"[长列表，{len(value)} 项；未发送给模型]"
        return [_safe_value(name, field, item) for item in value]
    return value


def _node_map(flow):
    data = flow.get("data") if isinstance(flow, dict) else None
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        raise ValueError("Flow has no node list")
    result = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            raise ValueError("Flow contains a node without a valid id")
        if node["id"] in result:
            raise ValueError("Flow contains duplicate node ids")
        result[node["id"]] = node
    return result


def flow_summary(flow):
    nodes = _node_map(flow)
    data = flow.get("data", {})
    summaries = []
    for node_id, outer in nodes.items():
        node_data = outer.get("data", {})
        component = node_data.get("node", {})
        template = component.get("template", {})
        config = {}
        if isinstance(template, dict):
            for name, field in template.items():
                if (
                    name not in {"code", "config_json", "input_data"}
                    and isinstance(field, dict)
                    and "value" in field
                    and not _is_secret(name, field)
                ):
                    config[name] = _safe_value(name, field, field["value"])
        summaries.append(
            {
                "id": node_id,
                "component": node_data.get("type", "unknown"),
                "name": _safe_value("display_name", {}, component.get("display_name", node_id)),
                "description": _safe_value("description", {}, str(component.get("description", ""))[:240]),
                "config": config,
                "inputs": [
                    name for name in template if name not in {"code", "config_json", "input_data"}
                ]
                if isinstance(template, dict)
                else [],
                "outputs": [
                    {"name": item.get("name"), "display_name": item.get("display_name")}
                    for item in component.get("outputs", [])
                    if isinstance(item, dict)
                ],
            }
        )
    edges = data.get("edges", [])
    return {
        "id": flow.get("id"),
        "name": _safe_value("flow_name", {}, flow.get("name")),
        "description": _safe_value("description", {}, flow.get("description", "")),
        "node_count": len(summaries),
        "edge_count": len(edges) if isinstance(edges, list) else 0,
        "nodes": summaries,
        "edges": [
            {
                key: _safe_value(key, {}, edge[key])
                for key in ("id", "source", "target", "sourceHandle", "targetHandle")
                if key in edge
            }
            for edge in edges
            if isinstance(edge, dict)
        ]
        if isinstance(edges, list)
        else [],
        "digest": flow_digest(flow),
    }


def component_catalog_summary(catalog, query="", limit=40):
    """Return only project science components and basic data-import components."""
    query = str(query or "").casefold().strip()
    limit = max(1, min(int(limit), 80))
    query_tokens = []
    for token in re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", query):
        if len(token) > 1:
            query_tokens.append(token)
        if len(token) > 2 and all("\u4e00" <= char <= "\u9fff" for char in token):
            query_tokens.extend(token[index:index + 2] for index in range(min(len(token) - 1, 20)))
    query_tokens = list(dict.fromkeys(query_tokens))[:40]
    groups = {
        "materials_quality",
        "materials_sources",
        "materials_extraction",
        "materials_preprocessing",
        "materials_analysis",
        "materials_statistics",
        "materials_visualization",
        "materials_batch",
        "materials_skills",
        "data_source",
    }
    search_aliases = {
        "ScienceIoTableImport": "csv tsv xlsx excel raw table file delimiter header",
        "MaterialMissingCheck": "missingness missing values null blank empty cells quality",
        "ScienceVizSpectra": "line chart plot curve x y series",
        "ScienceVizPerformance": "scatter chart plot x y performance",
        "ScienceVizMechanics": "stress strain chart plot curve",
        "ScienceVizStatistics": "statistics chart plot distribution",
    }
    ranked = []
    if not isinstance(catalog, dict):
        return []
    for category, components in catalog.items():
        if category not in groups or not isinstance(components, dict):
            continue
        for type_name, component in components.items():
            if not isinstance(component, dict) or not isinstance(component.get("template"), dict):
                continue
            name = component.get("display_name", type_name)
            description = str(component.get("description", ""))
            fields = component["template"]
            field_rows = []
            for field_name, field in fields.items():
                if field_name in {"code", "_type", "config_json"} or not isinstance(field, dict):
                    continue
                if field.get("show", True) is False and not field_name.startswith("cfg_"):
                    continue
                row = {
                    "name": field_name,
                    "type": field.get("type"),
                    "required": bool(field.get("required", False)),
                    "display_name": field.get("display_name", field_name),
                }
                if field.get("list") is True:
                    row["is_list"] = True
                if isinstance(field.get("table_schema"), list):
                    row["table_schema"] = [
                        {key: column[key] for key in ("name", "type", "required", "options") if key in column}
                        for column in field["table_schema"][:16]
                        if isinstance(column, dict)
                    ]
                if isinstance(field.get("input_types"), list) and field["input_types"]:
                    row["input_types"] = field["input_types"][:8]
                if field.get("show", True) is False:
                    row["conditional"] = True
                if isinstance(field.get("info"), str) and field["info"].strip():
                    row["info"] = field["info"][:180]
                if "options" in field and isinstance(field["options"], list):
                    row["options"] = [str(option)[:80] for option in field["options"][:12]]
                if (
                    field_name != "code"
                    and "value" in field
                    and not _is_secret(field_name, field)
                    and isinstance(field["value"], (str, int, float, bool, type(None)))
                    and len(str(field["value"])) <= 120
                ):
                    row["default"] = _safe_value(field_name, field, field["value"])
                field_rows.append(row)
            outputs = [
                {
                    "name": output.get("name"),
                    "display_name": output.get("display_name"),
                    "types": output.get("types", output.get("selected_output_types", [])),
                }
                for output in component.get("outputs", [])
                if isinstance(output, dict)
            ]
            haystack = " ".join(
                [category, type_name, str(name), description, search_aliases.get(type_name, "")]
                + [
                    field["name"] + " " + field["display_name"] + " " + field.get("info", "")
                    for field in field_rows
                ]
            ).casefold()
            tokens_found = sum(token in haystack for token in query_tokens)
            if query and not tokens_found and query not in haystack:
                continue
            type_text = str(type_name).casefold()
            name_text = str(name).casefold()
            type_hits = sum(token in type_text for token in query_tokens)
            name_hits = sum(token in name_text for token in query_tokens)
            exact_query = query == type_text or query == name_text
            score = (
                (100 if exact_query else 0)
                + (30 if query and query in type_text else 0)
                + (20 if query and query in name_text else 0)
                + 25 * type_hits
                + 12 * name_hits
                + 3 * tokens_found
                + (12 if query_tokens and all(token in haystack for token in query_tokens) else 0)
            )
            ranked.append(
                (
                    score,
                {
                    "category": category,
                    "type": type_name,
                    "name": name,
                    "description": description[:240],
                    "inputs": field_rows[:48],
                    "outputs": outputs[:16],
                },
                )
            )
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [component for _, component in ranked[:limit]]


def _component_map(catalog):
    result = {}
    for category, components in (catalog or {}).items():
        if not isinstance(components, dict):
            continue
        for type_name, component in components.items():
            if category.startswith("materials_") or (
                category == "data_source" and type_name in {"CSVtoData", "JSONtoData"}
            ):
                if isinstance(component, dict) and isinstance(component.get("template"), dict):
                    result[type_name] = component
    return result


def sanitize_installed_components(flow, catalog):
    """Rebind workflow nodes to installed code while retaining only configured input values."""
    candidate = copy.deepcopy(flow)
    components = _component_map(catalog)
    from materials_quality.science.catalog import entries as science_entries

    operation_by_type = {item["class_name"]: item["key"] for item in science_entries()}
    for node in _node_map(candidate).values():
        data = node.get("data", {})
        type_name = data.get("type")
        installed = components.get(type_name)
        if installed is None:
            raise ValueError(f"Workflow node is not an installed StudyUI component: {type_name}")
        old_template = data.get("node", {}).get("template", {})
        bundle = copy.deepcopy(installed)
        new_template = bundle.get("template", {})
        if isinstance(old_template, dict) and isinstance(new_template, dict):
            for name, field in new_template.items():
                if name == "code" or not isinstance(field, dict):
                    continue
                old_field = old_template.get(name)
                if isinstance(old_field, dict) and "value" in old_field and "value" in field:
                    field["value"] = old_field["value"]
            operation = operation_by_type.get(type_name)
            if operation is not None:
                # The installed catalog template reflects default controller
                # values. Recompute conditional field visibility after restoring
                # saved values, otherwise LFX drops hidden form values while
                # loading (for example wide_to_long's id_vars/value_vars).
                from materials_quality.science.ui_schema import refresh_config

                mode = new_template.get("ui_mode", {}).get("value", "form")
                refresh_config(None, operation, new_template, mode, "ui_mode")
        data["node"] = bundle
    validate_flow_connections(candidate)
    return candidate


def _edge_handles(edge, side):
    data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
    key = side + "Handle"
    handles = []
    for container in (data, edge):
        value = container.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                value = None
        if not isinstance(value, dict):
            raise ValueError("Workflow connection has an invalid canvas port handle")
        handles.append(value)
    return handles


def validate_flow_connections(flow):
    data = flow.get("data", {})
    nodes = _node_map(flow)
    edges = data.get("edges", [])
    if not isinstance(edges, list):
        raise ValueError("Workflow connections must be a list")
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("Workflow contains an invalid connection")
        source_id, target_id = edge.get("source"), edge.get("target")
        if source_id not in nodes or target_id not in nodes or source_id == target_id:
            raise ValueError("Workflow connection references a missing or identical node")
        source_node = nodes[source_id].get("data", {}).get("node", {})
        target_node = nodes[target_id].get("data", {}).get("node", {})
        output_name, outputs = _saved_port(edge, "source", source_id, source_node, "name")
        input_name, inputs = _saved_port(edge, "target", target_id, target_node, "fieldName")
        if not _compatible_types(outputs, inputs):
            raise ValueError(
                f"Workflow connection {source_id}.{output_name} {outputs} -> "
                f"{target_id}.{input_name} {inputs} uses incompatible data types"
            )


def _saved_port(edge, side, node_id, component, key):
    handles = _edge_handles(edge, side)
    if not handles:
        raise ValueError("Workflow connection is missing canvas port handles")
    name = handles[0].get(key)
    if not isinstance(name, str) or not name:
        raise ValueError("Workflow connection is missing its output or input port")
    if any(handle.get(key) != name for handle in handles):
        raise ValueError("Workflow connection canvas handles must agree on the canonical port")
    if any(handle.get("id") not in (None, node_id) for handle in handles):
        raise ValueError("Workflow connection canvas handles reference the wrong nodes")
    return _port(component, name, side == "source", canonical_only=True)


def validate_installed_components(flow, catalog):
    """Compatibility alias for validation callers; unsupported node types fail closed."""
    sanitize_installed_components(flow, catalog)


def _set_config(node, config):
    component = node.get("data", {}).get("node", {})
    template = component.get("template")
    if not isinstance(template, dict) or not isinstance(config, dict) or not config:
        raise ValueError("set_node_config requires a nonempty config object")
    if len(json.dumps(config, ensure_ascii=False).encode("utf-8")) > MAX_CONFIG_BYTES:
        raise ValueError("Node configuration patch is too large")
    for name, value in config.items():
        field = template.get(name)
        if not isinstance(field, dict):
            raise ValueError(f"Unknown node input: {name}")
        if _is_secret(name, field) or name in {"code", "_type", "type"}:
            raise ValueError(f"Agent cannot change protected field: {name}")
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError(f"Node input {name} must be finite JSON data") from None
        field["value"] = value


def _add_node(data, action, components):
    type_name, node_id = action.get("component_type"), action.get("node_id")
    if not isinstance(type_name, str) or type_name not in components:
        raise ValueError("add_node must use a component from the approved project catalog")
    if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
        raise ValueError("add_node requires a simple node_id")
    nodes = data["nodes"]
    if any(node.get("id") == node_id for node in nodes):
        raise ValueError("add_node cannot reuse an existing node id")
    bundle = copy.deepcopy(components[type_name])
    config = action.get("config") or {}
    component = {
        "id": node_id,
        "type": type_name,
        "node": bundle,
    }
    holder = {"data": {"node": bundle}}
    _set_config(holder, config) if config else None
    index = len(nodes)
    x, y = action.get("x", 80 + (index % 3) * 380), action.get("y", 80 + (index // 3) * 280)
    if type(x) not in {int, float} or type(y) not in {int, float} or abs(x) > 100_000 or abs(y) > 100_000:
        raise ValueError("Node position must be finite and within the canvas bounds")
    nodes.append(
        {
            "id": node_id,
            "type": "genericNode",
            "position": {"x": x, "y": y},
            "data": {"id": node_id, "type": type_name, "node": component["node"]},
        }
    )


OUTPUT_PORT_ALIASES = {
    "output_table": "table",
    "result_table": "table",
    "table_output": "table",
    "df": "table",
    "dataframe": "table",
    "data_table": "table",
    "table_out": "table",
    "out_table": "table",
    "output_data": "data",
    "result_data": "data",
    "data_output": "data",
    "result_report": "report",
    "summary": "report",
    "summary_report": "report",
    "output_report": "report",
    "report_out": "report",
    "results": "result",
    "output": "result",
    "chart": "plot",
    "figure": "plot",
    "output_plot": "plot",
    "files": "artifacts",
    "output_files": "artifacts",
    "generated_files": "artifacts",
    "features_out": "features",
    "features_table": "features",
}

INPUT_PORT_ALIASES = {
    "table": "input_table",
    "df": "input_table",
    "dataframe": "input_table",
    "data_table": "input_table",
    "input_df": "input_table",
    "dataset": "input_table",
    "table_in": "input_table",
    "tables": "input_tables",
    "data": "input_data",
    "payload": "input_data",
    "input": "input_data",
    "data_in": "input_data",
    "report": "reports",
    "input_report": "reports",
    "reports_in": "reports",
    "reports_list": "reports",
    "context": "quality_context",
    "rules_context": "quality_context",
    "input_context": "quality_context",
    "path": "file_path",
    "filepath": "file_path",
    "file": "file_path",
}


def _port(component, name, output, *, canonical_only=False):
    raw_name = str(name or "")
    if not canonical_only:
        raw_name = raw_name.strip()
    node_name = component.get("display_name") or component.get("name") or "Component"
    direction = "output" if output else "input"
    if output:
        entries = component.get("outputs")
        ports = [
            (entry["name"], entry) for entry in entries if isinstance(entry, dict)
            and isinstance(entry.get("name"), str) and entry["name"]
        ] if isinstance(entries, list) else []
        aliases = OUTPUT_PORT_ALIASES
    else:
        template = component.get("template")
        ports = [
            (key, field) for key, field in template.items() if isinstance(field, dict)
            and (field.get("input_types") or field.get("inputTypes"))
        ] if isinstance(template, dict) else []
        aliases = INPUT_PORT_ALIASES

    matches = [(key, field) for key, field in ports if key == raw_name]
    if not matches and not canonical_only and raw_name:
        folded = raw_name.casefold()
        alias = aliases.get(folded)
        matches = [
            (key, field) for key, field in ports
            if folded in {key.casefold(), str(field.get("display_name", "")).casefold()}
            or key == alias
        ]
    if len(matches) > 1:
        candidates = sorted(key for key, _ in matches)
        raise ValueError(f"Ambiguous component {direction} '{raw_name}' on node '{node_name}': {candidates}")
    if not matches:
        valid_names = sorted({key for key, _ in ports})
        closest = difflib.get_close_matches(raw_name, valid_names, n=1, cutoff=0.4)
        hint = f" Did you mean '{closest[0]}'?" if closest else ""
        qualifier = "canonical " if canonical_only else ""
        raise ValueError(
            f"Unknown {qualifier}component {direction} '{raw_name}' on node '{node_name}'. "
            f"Valid {direction} ports are: {valid_names}.{hint}"
        )

    canonical_name, field = matches[0]
    types = (field.get("types", field.get("selected_output_types")) if output
             else field.get("input_types") or field.get("inputTypes"))
    if isinstance(types, str):
        types = [types]
    return canonical_name, [str(value) for value in (types or []) if value]


def _normalized_types(values):
    aliases = {
        "table": "dataframe",
        "dataframe": "dataframe",
        "dataset": "dataframe",
        "records": "dataframe",
        "json": "data",
        "dict": "data",
        "object": "data",
        "message": "message",
        "text": "message",
        "str": "message",
    }
    return {aliases.get(str(value).casefold(), str(value).casefold()) for value in values}


def _compatible_types(outputs, inputs):
    return (
        not outputs
        or not inputs
        or bool(_normalized_types(outputs) & _normalized_types(inputs))
        or any(str(value).casefold() in {"any", "*"} for value in inputs)
        or any(str(value).casefold() in {"any", "*"} for value in outputs)
    )


def _connect(data, action):
    nodes = {node["id"]: node for node in data["nodes"]}
    source_id, target_id = action.get("source"), action.get("target")
    if source_id not in nodes or target_id not in nodes or source_id == target_id:
        raise ValueError("connect must reference two distinct existing nodes")
    source_name, target_name = action.get("output"), action.get("input")
    source_node = nodes[source_id]["data"]["node"]
    target_node = nodes[target_id]["data"]["node"]
    source_name, output_types = _port(source_node, source_name, True)
    target_name, input_types = _port(target_node, target_name, False)
    if not _compatible_types(output_types, input_types):
        raise ValueError(
            f"Connected ports have incompatible declared data types: "
            f"'{source_id}.{source_name}' ({output_types}) -> '{target_id}.{target_name}' ({input_types})"
        )
    source_handle = {
        "dataType": output_types[0] if output_types else "Data",
        "id": source_id,
        "name": source_name,
        "output_types": output_types,
    }
    target_handle = {
        "fieldName": target_name,
        "id": target_id,
        "inputTypes": input_types,
        "type": "other",
    }
    edge_id = "reactflow__edge-" + str(uuid.uuid4())
    data["edges"].append(
        {
            "animated": False,
            "source": source_id,
            "target": target_id,
            "id": edge_id,
            "sourceHandle": json.dumps(source_handle, ensure_ascii=False),
            "targetHandle": json.dumps(target_handle, ensure_ascii=False),
            "data": {"sourceHandle": source_handle, "targetHandle": target_handle},
            "selected": False,
        }
    )
    return source_name, target_name


def apply_actions(flow, actions, catalog):
    """Apply a validated patch to a copy; never mutate a saved flow in place."""
    if not isinstance(actions, list) or not actions or len(actions) > MAX_ACTIONS:
        raise ValueError(f"A patch must contain 1 to {MAX_ACTIONS} actions")
    candidate = copy.deepcopy(flow)
    data = candidate.get("data")
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("nodes"), list)
        or not isinstance(data.get("edges"), list)
    ):
        raise ValueError("Flow graph data is malformed")
    components = _component_map(catalog)
    descriptions = []
    for action in actions:
        if not isinstance(action, dict) or action.get("op") not in ALLOWED_OPS:
            raise ValueError("Unsupported or malformed graph action")
        op = action["op"]
        nodes = _node_map(candidate)
        if op == "set_node_config":
            node_id = action.get("node_id")
            if node_id not in nodes:
                raise ValueError("Node configuration patch references an unknown node")
            _set_config(nodes[node_id], action.get("config"))
            descriptions.append(f"配置 {node_id}")
        elif op == "add_node":
            _add_node(data, action, components)
            descriptions.append(f"新增 {action.get('component_type')} ({action.get('node_id')})")
        elif op == "remove_node":
            node_id = action.get("node_id")
            if node_id not in nodes:
                raise ValueError("remove_node references an unknown node")
            data["nodes"] = [node for node in data["nodes"] if node.get("id") != node_id]
            data["edges"] = [
                edge
                for edge in data["edges"]
                if edge.get("source") != node_id and edge.get("target") != node_id
            ]
            descriptions.append(f"删除 {node_id} 及相关连线")
        elif op == "connect":
            source_canonical, target_canonical = _connect(data, action)
            description = (
                f"连接 {action.get('source')}.{source_canonical} → {action.get('target')}.{target_canonical}"
            )
            if (action.get("output"), action.get("input")) != (source_canonical, target_canonical):
                description += f"（请求端口 {action.get('output')} → {action.get('input')}）"
            descriptions.append(description)
        elif op == "disconnect":
            source, target = action.get("source"), action.get("target")
            old_count = len(data["edges"])
            data["edges"] = [
                edge
                for edge in data["edges"]
                if not (edge.get("source") == source and edge.get("target") == target)
            ]
            if old_count == len(data["edges"]):
                raise ValueError("disconnect did not match an existing connection")
            descriptions.append(f"断开 {source} → {target}")
    valid_ids = set(_node_map(candidate))
    for edge in data["edges"]:
        if edge.get("source") not in valid_ids or edge.get("target") not in valid_ids:
            raise ValueError("Candidate workflow contains an edge to a missing node")
    return candidate, descriptions

"""Conservative offline migration of canonical pre-native-control Langflow nodes.

Embedded Python is identified by a packaged source hash allowlist and is never
executed by this module. Only the installed, current component classes are loaded.
"""

import hashlib
import json
import sys
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from .catalog import component_class, entries

_QUALITY_FILES = {
    "MaterialQualityContext": "quality_context",
    "MaterialQualitySummary": "quality_summary",
    "MaterialSchemaCheck": "schema_check",
    "MaterialMissingCheck": "missing_check",
    "MaterialTypeCheck": "type_check",
    "MaterialUnitCheck": "unit_check",
    "MaterialDuplicateCheck": "duplicate_check",
    "MaterialOutlierCheck": "outlier_check",
}
_VISUAL_FIELDS = ("minimized", "pinned", "frozen", "tool_mode")
_MARKER = "materials_quality_ui_migration"


class MigrationError(ValueError):
    """An upgrade would leave an unsupported graph connection or invalid flow."""


def source_hash(source):
    """Normalize line endings/outer blank lines, preserving literal whitespace."""
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").strip("\n") + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _component_root():
    root = Path(__file__).resolve().parents[1] / "component_sources"
    return root if root.is_dir() else Path(__file__).resolve().parents[3] / "components"


def _current_class(name, catalog):
    if name in catalog:
        return component_class(catalog[name]["key"])
    path = _component_root() / "materials_quality" / (_QUALITY_FILES[name] + ".py")
    module_name = "materials_quality._ui_migrate_" + _QUALITY_FILES[name]
    if module_name not in sys.modules:
        spec = spec_from_file_location(module_name, path)
        module = module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return getattr(sys.modules[module_name], name)


def _current_hash(name, catalog):
    if name in catalog:
        item = catalog[name]
        path = _component_root() / item["directory"] / (item["filename"] + ".py")
    else:
        path = _component_root() / "materials_quality" / (_QUALITY_FILES[name] + ".py")
    return source_hash(path.read_text(encoding="utf-8"))


def _graph(payload):
    if not isinstance(payload, dict):
        raise MigrationError("Expected a Langflow JSON object containing nodes and edges.")
    graph = payload.get("data", payload)
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        raise MigrationError("Expected a Langflow nodes list under data.nodes or nodes.")
    if not isinstance(graph.get("edges", []), list):
        raise MigrationError("Expected a Langflow edges list.")
    return graph


def _nonempty(value):
    # False and zero are meaningful. An empty retired input has no data to lose.
    return value is not None and value != "" and value != "__UNDEFINED__" and value != [] and value != {}


def _handle(edge, which):
    key = which + "Handle"
    nested = edge.get("data", {}).get(key)
    value = nested if nested is not None else edge.get(key)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise MigrationError(
                f"Malformed {key} for edge {edge.get('source')} -> {edge.get('target')}."
            ) from exc
    if not isinstance(value, dict):
        raise MigrationError(f"Missing {key} for edge {edge.get('source')} -> {edge.get('target')}.")
    return value


def _write_handle(edge, which, value):
    key = which + "Handle"
    # Preserve the serializer's dict/string shape; both variants are native.
    for container in (edge, edge.get("data", {})):
        if key in container:
            previous = container[key]
            container[key] = (
                json.dumps(value, ensure_ascii=False) if isinstance(previous, str) else deepcopy(value)
            )


def _validate_edges(graph, upgraded_ids):
    nodes = {}
    for vertex in graph["nodes"]:
        node_id = vertex.get("id") if isinstance(vertex, dict) else None
        if not isinstance(node_id, str) or not node_id or node_id in nodes:
            raise MigrationError(f"Missing or duplicate node ID: {node_id!r}.")
        nodes[node_id] = vertex
    for edge in graph.get("edges", []):
        source_id, target_id = edge.get("source"), edge.get("target")
        if source_id not in nodes or target_id not in nodes:
            raise MigrationError(f"Edge references an unknown node: {source_id} -> {target_id}.")
        source_handle, target_handle = _handle(edge, "source"), _handle(edge, "target")
        output_name = source_handle.get("name")
        input_name = target_handle.get("fieldName")
        source = nodes[source_id]["data"].get("node", {})
        target = nodes[target_id]["data"].get("node", {})
        outputs = {item.get("name"): item for item in source.get("outputs", [])}
        if output_name not in outputs:
            raise MigrationError(
                f"Unsupported source output {source_id}.{output_name}: the migrated node has no such output. "
                "For PDF/image imports use report/file metadata, or add a real extraction node; "
                "a missing table cannot be replaced with an empty table."
            )
        target_input = target.get("template", {}).get(input_name)
        if not isinstance(target_input, dict):
            raise MigrationError(
                f"Unsupported target input {target_id}.{input_name}: the migrated node has no such input."
            )
        if source_handle.get("id", source_id) != source_id or target_handle.get("id", target_id) != target_id:
            raise MigrationError(f"Handle IDs do not match edge endpoints: {source_id} -> {target_id}.")
        # The edge itself is retained. Refresh only endpoints we actually upgraded;
        # custom-node metadata and code are never interpreted or executed.
        if source_id in upgraded_ids:
            source_handle.update(
                id=source_id,
                dataType=nodes[source_id]["data"]["type"],
                output_types=deepcopy(outputs[output_name].get("types", [])),
            )
            _write_handle(edge, "source", source_handle)
        if target_id in upgraded_ids:
            # Langflow removes connections to hidden advanced handles on import.
            # Nodes were regenerated before edges were attached, so preserve the
            # visibility of provenance ports that the saved graph actually uses.
            if input_name in {"input_data", "reports"}:
                target_input["advanced"] = False
            target_handle.update(
                id=target_id,
                inputTypes=deepcopy(target_input.get("input_types", [])),
                type=target_input.get("type", "other"),
            )
            if "display_name" in target_handle:
                target_handle["display_name"] = target_input.get("display_name", input_name)
            _write_handle(edge, "target", target_handle)
    return len(graph.get("edges", []))


def migrate(payload):
    """Return ``(deep_copied_payload, report)``; never mutate or run the old flow.

    Known class names with modified Python or unknown nonempty parameters are
    preserved verbatim and listed under ``skipped``. Unsupported connections raise
    MigrationError before callers can write a misleading partially migrated file.
    """
    updated = deepcopy(payload)
    graph = _graph(updated)
    registry = json.loads(
        Path(__file__).with_name("legacy_component_hashes.json").read_text(encoding="utf-8")
    )
    catalog = {item["class_name"]: item for item in entries()}
    report = {
        "version": 1,
        "baseline": registry["baseline"],
        "upgraded": [],
        "skipped": [],
        "unchanged": [],
        "edges_validated": 0,
    }
    upgraded_ids = set()
    for vertex in graph["nodes"]:
        if not isinstance(vertex, dict) or not isinstance(vertex.get("data"), dict):
            raise MigrationError("Every flow node must contain an id and data object.")
        data = vertex["data"]
        name = data.get("type")
        identity = {"id": vertex.get("id"), "class_name": name}
        if name not in registry["classes"]:
            report["unchanged"].append({**identity, "reason": "unknown_node"})
            continue
        old_node = data.get("node", {})
        old_template = old_node.get("template", {})
        code = old_template.get("code", {}).get("value")
        if not isinstance(code, str) or not code.strip():
            report["skipped"].append({**identity, "reason": "missing_source"})
            continue
        digest = source_hash(code)
        is_current = digest == _current_hash(name, catalog)
        if is_current and ("ui_mode" in old_template or _MARKER in data):
            report["unchanged"].append({**identity, "reason": "already_current"})
            continue
        if digest not in registry["classes"][name]:
            report["skipped"].append({**identity, "reason": "custom_code", "source_sha256": digest})
            continue
        component = _current_class(name, catalog)()
        component.set_id(vertex["id"])
        if "ui_mode" in component._inputs:
            values = {"ui_mode": "json"}
            if "config_json" in old_template:
                values["config_json"] = deepcopy(old_template["config_json"].get("value"))
            component.set(**values)
        new_node = component.to_frontend_node()["data"]["node"]
        new_template = new_node["template"]
        unsupported = [
            key
            for key, descriptor in old_template.items()
            if key not in new_template and isinstance(descriptor, dict) and _nonempty(descriptor.get("value"))
        ]
        if unsupported:
            report["skipped"].append({**identity, "reason": "unsupported_parameter", "fields": unsupported})
            continue
        preserved = []
        for key, descriptor in old_template.items():
            if (
                key != "code"
                and key in new_template
                and isinstance(descriptor, dict)
                and "value" in descriptor
            ):
                new_template[key]["value"] = deepcopy(descriptor["value"])
                preserved.append(key)
        if "ui_mode" in new_template:
            new_template["ui_mode"]["value"] = "json"
            component.update_build_config(new_template, "json", "ui_mode")
        for key in _VISUAL_FIELDS:
            if key in old_node:
                new_node[key] = deepcopy(old_node[key])
        data["node"] = new_node
        data[_MARKER] = {"version": 1, "source_sha256": digest, "baseline": registry["baseline"]}
        upgraded_ids.add(vertex["id"])
        report["upgraded"].append({**identity, "preserved_fields": preserved})
    report["edges_validated"] = _validate_edges(graph, upgraded_ids)
    return updated, report

"""Execute StudyUI workflow files directly using the LFX graph runtime."""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

from .workflow_files import WorkflowFileStore

_WORKFLOW_RUN_GATE = threading.BoundedSemaphore(1)


def _serialize_output(value):
    import numpy as np
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        return json.loads(value.to_json(orient="records", date_format="iso"))
    if isinstance(value, (np.ndarray, np.generic)):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported workflow output type: {type(value).__name__}")


def _prepare_runtime_outputs(flow):
    """Return an in-memory-only graph copy with meaningful result nodes exposed."""
    runtime_flow = copy.deepcopy(flow)
    data = runtime_flow.get("data") if isinstance(runtime_flow, dict) else None
    nodes = data.get("nodes") if isinstance(data, dict) else None
    edges = data.get("edges") if isinstance(data, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return runtime_flow

    typed = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data")
        if not isinstance(node_data, dict):
            continue
        component_type = str(node_data.get("type") or "").casefold()
        if component_type in {"scienceexportreport", "scienceexporttable"}:
            typed.append((node, component_type))

    reports = [node for node, kind in typed if kind == "scienceexportreport"]
    tables = [node for node, kind in typed if kind == "scienceexporttable"]
    preferred = reports or tables
    if preferred:
        selected = {str(node.get("id")) for node in preferred if node.get("id")}
    else:
        source_ids = {
            str(edge.get("source"))
            for edge in edges or []
            if isinstance(edge, dict) and edge.get("source") is not None
        }
        selected = {
            str(node.get("id"))
            for node in nodes
            if isinstance(node, dict) and node.get("id") and str(node.get("id")) not in source_ids
        }

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data")
        config = node_data.get("node") if isinstance(node_data, dict) else None
        if isinstance(config, dict):
            # The original file stays untouched; this flag only tells LFX which
            # completed vertices StudyUI should return to its agent.
            config["is_output"] = str(node.get("id")) in selected
    return runtime_flow


def _bounded_result_value(value, *, port_name="", depth=0):
    """Keep runtime results small while preserving report text and artifact paths."""
    if depth > 12:
        return "[nested result omitted]"
    try:
        import numpy as np
        import pandas as pd
    except ImportError:  # pragma: no cover - these are runtime dependencies
        np = None
        pd = None

    if pd is not None and isinstance(value, pd.DataFrame):
        if port_name.casefold() in {"table", "artifacts", "artifact_files"}:
            rows = value.head(100).to_dict(orient="records")
            if len(value) > len(rows):
                rows.append({"_omitted_rows": len(value) - len(rows)})
            return _bounded_result_value(rows, depth=depth + 1)
        return {
            "rows": int(len(value)),
            "columns": [str(column)[:120] for column in list(value.columns)[:100]],
            "_studyui_table_summary": True,
        }
    if np is not None and isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "dtype": str(value.dtype), "_studyui_array_summary": True}
    if np is not None and isinstance(value, np.generic):
        return _bounded_result_value(value.item(), port_name=port_name, depth=depth + 1)
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value[:20_000] if isinstance(value, str) else value
    if isinstance(value, dict):
        result = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 200:
                result["_omitted_fields"] = len(value) - index
                break
            result[str(key)[:160]] = _bounded_result_value(item, port_name=str(key), depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        result = [_bounded_result_value(item, port_name=port_name, depth=depth + 1) for item in value[:100]]
        if len(value) > len(result):
            result.append({"_omitted_items": len(value) - len(result)})
        return result
    # LFX Data and Message wrappers carry useful payload in these attributes.
    payload = getattr(value, "data", None)
    if isinstance(payload, dict):
        return _bounded_result_value(payload, port_name=port_name, depth=depth + 1)
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return {"text": text[:20_000]}
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _bounded_result_value(dump(mode="python"), port_name=port_name, depth=depth + 1)
    shape = getattr(value, "shape", None)
    if shape is not None:
        return {"shape": list(shape), "type": type(value).__name__}
    return str(value)[:500]


def _serialize_run_outputs(run_outputs):
    if not any(hasattr(run_outputs, name) for name in ("component_id", "results", "outputs", "artifacts")):
        return _bounded_result_value(run_outputs)
    entries = []
    for entry in getattr(run_outputs, "outputs", ()) or ():
        if entry is None:
            continue
        if isinstance(entry, dict) or not any(
            hasattr(entry, name) for name in ("component_id", "results", "outputs", "artifacts")
        ):
            entries.append(_bounded_result_value(entry))
            continue
        raw_results = getattr(entry, "results", None)
        row = {
            "component_id": getattr(entry, "component_id", None),
            "component_display_name": getattr(entry, "component_display_name", None),
        }
        if raw_results:
            row["results"] = _bounded_result_value(raw_results)
        else:
            projection = getattr(entry, "outputs", None)
            if projection:
                row["outputs"] = _bounded_result_value(projection)
        artifacts = getattr(entry, "artifacts", None)
        if artifacts:
            row["artifacts"] = _bounded_result_value(artifacts, port_name="artifacts")
        entries.append(row)
    return {"outputs": entries}


class FileWorkflowExecutor:
    def __init__(self, store: WorkflowFileStore, validator=None):
        self.store = store
        self.validator = validator

    def run(
        self,
        flow_id: str,
        *,
        input_value: str = "",
        tweaks: dict | None = None,
        output_type: str = "any",
        external_data_approved: bool = False,
        expected_digest: str | None = None,
        expected_project_id: str | None = None,
    ):
        from lfx.load import run_flow_from_json

        if not isinstance(input_value, str):
            raise ValueError("input_value must be a string")
        if tweaks is not None and not isinstance(tweaks, dict):
            raise ValueError("tweaks must be an object")
        flow, revision = self.store.read(flow_id)
        if self.validator:
            flow = self.validator(flow) or flow
        if expected_digest is not None or external_data_approved:
            from .workflow import flow_digest

            if not expected_digest or (
                flow_digest(flow) != expected_digest or flow.get("folder_id") != expected_project_id
            ):
                raise ValueError("运行授权后工作流内容或所属项目已变化；请重新确认运行或数据传输审批。")
        from .execution_context import (
            begin_upstream_image_scope,
            external_data_approval,
            reset_external_data_approval,
            reset_upstream_image_scope,
        )

        token = external_data_approval(external_data_approved)
        image_scope = begin_upstream_image_scope()
        try:
            runtime_flow = _prepare_runtime_outputs(flow)
            with _WORKFLOW_RUN_GATE:
                outputs = run_flow_from_json(
                    runtime_flow,
                    input_value=input_value,
                    input_type="text",
                    output_type="any" if output_type == "debug" else output_type,
                    tweaks=copy.deepcopy(tweaks or {}),
                )
        finally:
            reset_external_data_approval(token)
            reset_upstream_image_scope(image_scope)
        return {
            "flow_id": flow_id,
            "revision": revision,
            "outputs": [_serialize_run_outputs(value) for value in outputs],
        }

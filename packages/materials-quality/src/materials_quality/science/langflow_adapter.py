"""Native ports, content-aware execution cache and auditable result envelopes."""

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from lfx.io import DataFrameInput, DataInput, FileInput, HandleInput, MultilineInput, Output
from lfx.schema import Data, DataFrame, Message

from materials_quality.common import json_value
from materials_quality.context import table_fingerprint

from .catalog import get
from .contracts import NodeResult

SECRET = re.compile(r"password|passwd|secret|token|api.?key|authorization|cookie|credential", re.I)


def node_inputs(default):
    return [
        DataFrameInput(name="input_table", display_name="输入表格", required=False),
        DataInput(name="input_data", display_name="上游结果 / 文件与证据", required=False),
        HandleInput(
            name="input_tables",
            display_name="其他表格（可多接）",
            input_types=["DataFrame"],
            is_list=True,
            required=False,
            advanced=False,
        ),
        DataInput(
            name="reports", display_name="报告来源（可多接）", is_list=True, required=False, advanced=False
        ),
        FileInput(
            name="source_file",
            display_name="上传源文件",
            required=False,
            advanced=True,
            file_types=[
                "csv",
                "tsv",
                "txt",
                "xlsx",
                "xls",
                "pdf",
                "png",
                "jpg",
                "jpeg",
                "tif",
                "tiff",
                "bmp",
                "json",
                "xy",
                "xrdml",
                "brml",
                "jdx",
                "sqlite",
            ],
        ),
        MultilineInput(
            name="config_json",
            display_name="方法与参数 JSON",
            value=json.dumps(default, ensure_ascii=False, indent=2),
            info="方法参数见随仓库提供的节点手册；示例可直接导入。原始数据不会被覆盖。",
        ),
    ]


def node_outputs():
    return [
        Output(name=name, display_name=label, method=method, group_outputs=True)
        for name, label, method in [
            ("table", "结果表格", "build_table"),
            ("report", "结果与追溯", "build_report"),
            ("artifacts", "生成文件", "build_artifacts"),
            ("summary", "运行摘要", "build_summary"),
        ]
    ]


def _strict_json(value):
    def bad(token):
        raise ValueError(f"Invalid JSON constant: {token}")

    try:
        # LFX's serialized graph loader decodes object-shaped multiline fields.
        # Validate these with the same finite-JSON contract as editor strings.
        if isinstance(value, dict):
            value = json.dumps(value, allow_nan=False)
        parsed = json.loads(value, parse_constant=bad)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"config_json must be valid finite JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("config_json must be a JSON object")
    return parsed


def _object(value):
    if isinstance(value, Data):
        return value.data
    return value if isinstance(value, dict) else {}


def _unwrap(value):
    obj = _object(value)
    return obj.get("data", {}) if obj.get("schema_version") == "science-result/1" else obj


def _resolve_assets(value, assets):
    if isinstance(value, str) and value.startswith("@asset:"):
        key = value[7:]
        if key not in assets:
            raise ValueError(f"Unknown asset: {key}")
        return assets[key]
    if isinstance(value, dict):
        return {k: _resolve_assets(v, assets) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_assets(v, assets) for v in value]
    return value


def _input_paths(key, config, data, reports):
    # Structural capabilities, not recursive key-name guessing: text, table cells,
    # previews, document metadata and arbitrary parameter dictionaries are inert.
    path_keys = {
        "path",
        "file_path",
        "model_path",
        "manifest_path",
        "ocr_config_path",
        "labels_path",
        "label_path",
        "annotation_path",
        "mask_path",
        "reference_path",
    }
    values = [v for k, v in config.items() if k in path_keys]
    values += [data[k] for k in ("file_path", "model_path", "manifest_path") if k in data]
    assets = data.get("asset_paths", {})
    if isinstance(assets, dict):
        values.extend(assets.values())
    for report in reports:
        if report.get("schema_version") == "science-result/1":
            values.extend(report.get("artifacts", []))
    if key == "export.report":
        for figure in data.get("figures", []):
            values.append(figure.get("path") if isinstance(figure, dict) else figure)
    if key in {"stats.predict", "stats.evaluate"}:
        for field in ("manifest_path", "model_path"):
            manifest_path = config.get(field) or data.get(field)
            if isinstance(manifest_path, str) and Path(manifest_path).suffix.lower() == ".json":
                try:
                    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                    if isinstance(manifest, dict):
                        values.append(manifest.get("model_path"))
                except (OSError, ValueError):
                    pass  # The operation itself provides the actionable model error.
    return values


def _file_hashes(value, *, paths=False):
    found = {}

    def visit(obj, admitted=False):
        if isinstance(obj, (tuple, list)):
            for v in obj:
                visit(v, admitted)
        elif admitted and isinstance(obj, str) and len(obj) < 4096:
            try:
                path = Path(obj)
                if path.is_file():
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    found[str(path.resolve())] = digest.hexdigest()
            except (ValueError, OSError):
                pass

    visit(value, paths)
    return found


def _redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET.search(str(k)) else _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and "://" in value:
        try:
            parts = urlsplit(value)
            host = parts.netloc.split("@")[-1]
            query = urlencode(
                [
                    (k, "[REDACTED]" if SECRET.search(k) else v)
                    for k, v in parse_qsl(parts.query, keep_blank_values=True)
                ]
            )
            return urlunsplit((parts.scheme, host, parts.path, query, parts.fragment))
        except ValueError:
            pass
    return value


def _frame_value(table):
    if table is None:
        return None
    if not isinstance(table, pd.DataFrame):
        raise ValueError("Connect a DataFrame output to the table input")
    return table_fingerprint(table)


def _digest(value):
    return hashlib.sha256(
        json.dumps(json_value(value), sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _lineage(envelopes):
    records, seen = [], set()
    for envelope in envelopes:
        for record in envelope.get("provenance", {}).get("lineage", []):
            key = _digest(record)
            if key not in seen:
                seen.add(key)
                records.append(record)
    return records


def execute(component, key):
    value = component.config_json
    raw_value = component._parameters.get("config_json")
    if not value and isinstance(raw_value, dict):
        value = raw_value
    config = _strict_json(value)
    upstream = _object(getattr(component, "input_data", None))
    data = dict(_unwrap(upstream))
    assets = data.get("asset_paths", {})
    config = _resolve_assets(config, assets)
    upload = getattr(component, "source_file", None)
    if upload:
        if isinstance(upload, list):
            if len(upload) != 1:
                raise ValueError("Upload exactly one source file")
            upload = upload[0]
        config["path"] = component.resolve_path(upload)
    table = getattr(component, "input_table", None)
    if isinstance(table, str) and not table:
        table = None
    tables = getattr(component, "input_tables", None) or []
    if isinstance(tables, pd.DataFrame):
        tables = [tables]
    reports = [_object(x) for x in (getattr(component, "reports", None) or [])]
    envelopes = [upstream, *reports]
    files = _file_hashes(_input_paths(key, config, data, reports), paths=True)
    signature = _digest(
        [key, config, upstream, data, _frame_value(table), [_frame_value(t) for t in tables], reports, files]
    )
    # Component.ctx is graph-global and returns a fresh {} for standalone calls.
    # Keep this transient cache per component, never in the serialized graph.
    cached = component._ctx.get("science_execution")
    if cached and cached["signature"] == signature:
        # Missing or changed generated files require a fresh execution.
        if _file_hashes(cached["envelope"]["artifacts"], paths=True) == cached["artifact_hashes"]:
            return cached["result"], cached["envelope"]
    if key == "export.report" and reports:
        data = {
            **data,
            "sources": [e.get("provenance", {}) for e in reports],
            "parameters": [e.get("provenance", {}).get("parameters", {}) for e in reports],
            "results": [
                {"operation": e.get("operation"), "data": e.get("data", e), "table": e.get("table_preview")}
                for e in reports
            ],
            "warnings": [w for e in reports for w in e.get("warnings", [])],
            "figures": [
                {"path": p, "caption": e.get("operation", "Figure")}
                for e in reports
                for p in e.get("artifacts", [])
                if Path(p).suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
            ],
        }
    operation = get(key)["callable"]
    try:
        result = operation(table, config=config, data=data, tables=tables)
    except ImportError as exc:
        raise ValueError(
            "This method needs the science dependencies: pip install '.[science]' — " + str(exc)
        ) from exc
    if not isinstance(result, NodeResult):
        raise TypeError(f"{key} returned an invalid operation result")
    result_data = dict(result.data)
    if assets:
        result_data["asset_paths"] = assets
    current = {
        "operation": key,
        "parameters": _redact(config),
        "input_sha256": signature,
        "source_files": files,
        "utc": datetime.now(timezone.utc).isoformat(),
    }
    envelope = _redact(
        json_value(
            {
                "schema_version": "science-result/1",
                "operation": key,
                "execution_status": "completed",
                "data": result_data,
                "warnings": result.warnings,
                "artifacts": result.artifacts,
                "table_summary": None
                if result.table is None
                else {"rows": len(result.table), "columns": list(result.table.columns)},
                "table_preview": None
                if result.table is None
                else {
                    "total_rows": len(result.table),
                    "included_rows": min(100, len(result.table)),
                    "truncated": len(result.table) > 100,
                    "columns": list(result.table.columns),
                    "records": result.table.head(100).to_dict("records"),
                    "units": result.table.attrs.get("units", result_data.get("units", {})),
                },
                "provenance": {**current, "lineage": [*_lineage(envelopes), current]},
            }
        )
    )
    component._ctx["science_execution"] = {
        "signature": signature,
        "result": result,
        "envelope": envelope,
        "artifact_hashes": _file_hashes(result.artifacts, paths=True),
    }
    component.status = f"{get(key)['title']}：完成；{len(result.warnings)} 条提示"
    return result, envelope


def output_table(component, key):
    result, _ = execute(component, key)
    if result.table is None:
        return DataFrame()
    table = DataFrame(result.table.copy(deep=True))
    table.attrs = deepcopy(result.table.attrs)
    return table


def output_report(component, key):
    return Data(data=execute(component, key)[1])


def output_artifacts(component, key):
    _, envelope = execute(component, key)
    return DataFrame(
        [
            {"path": p, "sha256": _file_hashes([p], paths=True).get(str(Path(p).resolve()))}
            for p in envelope["artifacts"]
        ],
        columns=["path", "sha256"],
    )


def output_summary(component, key):
    _, envelope = execute(component, key)
    return Message(
        text=f"{get(key)['title']}已完成。结果表：{envelope['table_summary']}；"
        f"生成文件 {len(envelope['artifacts'])} 个。\n" + "\n".join(envelope["warnings"])
    )

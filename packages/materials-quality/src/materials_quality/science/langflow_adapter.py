"""Native ports, content-aware execution cache and auditable result envelopes."""

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
from lfx.io import DataFrameInput, DataInput, FileInput, HandleInput, MultilineInput, Output
from lfx.schema import Data, DataFrame, Message

from materials_quality.common import json_value
from materials_quality.context import table_fingerprint

from .catalog import get
from .contracts import NodeResult
from .table_contract import (
    contract_identity,
    propagate_contract,
    read_contract,
    restore_contract_units,
)

SECRET = re.compile(r"password|passwd|secret|token|api.?key|authorization|cookie|credential", re.I)


def node_inputs(default, operation_defaults=None):
    if isinstance(default, str):
        from .ui_schema import science_inputs

        return science_inputs(default, operation_defaults or {})
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


def node_outputs(key=None, config=None):
    if key is not None:
        from .ui_schema import science_outputs

        return science_outputs(key, config)
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


def _asset_paths(data, reports):
    """Collect only explicit asset paths from the input envelope and report ports."""
    result = {}
    direct = data.get("asset_paths", {}) if isinstance(data, dict) else {}
    if isinstance(direct, dict):
        result.update({key: value for key, value in direct.items() if isinstance(key, str)})
    for report in reports:
        report_data = _unwrap(report)
        candidate = report_data.get("asset_paths", {}) if isinstance(report_data, dict) else {}
        if isinstance(candidate, dict):
            for key, value in candidate.items():
                if isinstance(key, str):
                    result.setdefault(key, value)
    return result


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


class _SourceLimitError(ValueError):
    pass


def _zarr_fingerprint(path, max_entries, max_bytes):
    if type(max_entries) is not int or max_entries <= 0 or type(max_bytes) is not int or max_bytes <= 0:
        raise _SourceLimitError("Zarr fingerprint limits must be positive integers")
    if path.is_symlink():
        raise _SourceLimitError("Zarr source contains a symbolic link")
    manifest, entries, size = [], 0, 0
    pending = [path]
    while pending:
        with os.scandir(pending.pop()) as children:
            for entry in children:
                entries += 1
                if entries > max_entries:
                    raise _SourceLimitError("Zarr max_store_entries limit exceeded before hashing")
                member = Path(entry.path)
                if entry.is_symlink():
                    raise _SourceLimitError("Zarr source contains a symbolic link")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(member)
                elif entry.is_file(follow_symlinks=False):
                    count = entry.stat(follow_symlinks=False).st_size
                    size += count
                    if size > max_bytes:
                        raise _SourceLimitError("Zarr source byte limit exceeded before hashing")
                    manifest.append((member.relative_to(path).as_posix(), member, count))
    digest = hashlib.sha256()
    for relative, member, count in sorted(manifest):
        name = relative.encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(count.to_bytes(8, "big"))
        with member.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _file_hashes(value, *, paths=False, max_store_entries=100_000, max_store_bytes=1024**3):
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
                elif path.is_dir() and any(
                    (path / marker).is_file() for marker in (".zgroup", ".zarray", "zarr.json")
                ):
                    try:
                        found[str(path.resolve())] = _zarr_fingerprint(
                            path, max_store_entries, max_store_bytes
                        )
                    except OSError as error:
                        raise _SourceLimitError(
                            f"Zarr source changed or could not be read: {error}"
                        ) from error
            except _SourceLimitError:
                raise
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


def _frame_value(table, *, include_source=False):
    if table is None:
        return None
    if not isinstance(table, pd.DataFrame):
        raise ValueError("Connect a DataFrame output to the table input")
    value = {"table_sha256": table_fingerprint(table), "contract_sha256": contract_identity(table)}
    if include_source:
        value.update({name: table.attrs.get(name) for name in ("source_name", "source_sha256")})
    return value


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


def _form_task_data(component, key, config, data):
    """Honor explicit native task controls without changing legacy auto-dispatch."""
    if key not in {"stats.predict", "stats.evaluate"} or getattr(component, "ui_contract_version", 1) < 2:
        return data, None
    from .ui_schema import effective_mode

    if effective_mode(component) != "form":
        return data, None
    selector = "prediction_task" if key == "stats.predict" else "evaluation_task"
    task = getattr(component, "cfg_" + selector, "train")
    selected = dict(data)
    if task == "train":
        for field in ("model_path", "manifest_path", "y_true", "y_pred"):
            selected.pop(field, None)
    elif task == "saved":
        if not any(config.get(field) or selected.get(field) for field in ("model_path", "manifest_path")):
            raise ValueError("已有模型模式需要填写模型/清单路径，或连接包含模型路径的上游结果。")
        selected.pop("y_true", None)
        selected.pop("y_pred", None)
    elif task == "predictions" and key == "stats.evaluate":
        if bool(config.get("y_true")) != bool(config.get("y_pred")):
            raise ValueError("请同时选择已有真实值列和预测值列。")
        if config.get("y_true") and config.get("y_pred"):
            # Explicit table columns take precedence over unrelated upstream arrays.
            selected.pop("y_true", None)
            selected.pop("y_pred", None)
        elif not all(field in selected for field in ("y_true", "y_pred")):
            raise ValueError("已有预测值模式需要选择两列，或连接同时包含 y_true/y_pred 数组的数据。")
        selected.pop("model_path", None)
        selected.pop("manifest_path", None)
    else:
        raise ValueError("请选择支持的模型任务。")
    return selected, task


def _operation_config(component, key):
    if getattr(component, "ui_contract_version", 1) >= 2:
        from .ui_schema import form_config

        config = form_config(component, key)
    else:
        value = component.config_json
        raw_value = component._parameters.get("config_json")
        if not value and isinstance(raw_value, dict):
            value = raw_value
        config = _strict_json(value)
    return config


def _restore_contract(table, upstream):
    """Match a connected table to an explicit persistent result declaration."""
    if table is None:
        return table
    cached = read_contract(table)
    candidates = []
    for field, preview_field in (
        ("table_contract", "table_preview"),
        ("features_contract", "features_preview"),
    ):
        if upstream.get(field) is not None:
            metadata = upstream.get(preview_field) or {}
            binding_field = "table_fingerprint" if field == "table_contract" else "features_fingerprint"
            binding = upstream.get(binding_field)
            candidates.append((upstream[field], metadata.get("columns"), metadata.get("units", {}), binding))
    if upstream.get("schema_version") == "research-result/1":
        for item in upstream.get("tables", {}).values():
            if isinstance(item, dict) and item.get("contract") is not None:
                candidates.append(
                    (item["contract"], item.get("columns"), item.get("units", {}), item.get("fingerprint"))
                )
    if not candidates:
        return table if cached is None else restore_contract_units(table, cached)
    if cached is not None:
        candidates = [
            (contract, columns, units, binding)
            for contract, columns, units, binding in candidates
            if cached == contract and (columns is None or columns == list(table.columns))
        ]
        if not candidates:
            raise ValueError("input table contract mismatch with upstream result envelope")
    matched = {}
    errors = []
    invalid_bindings = {}
    for contract, columns, units, binding in candidates:
        if columns is not None and list(table.columns) != columns:
            continue
        if not isinstance(binding, str) or re.fullmatch(r"[0-9a-f]{64}", binding) is None:
            raise ValueError(
                "upstream contract is missing its output fingerprint binding; "
                "rerun the source node and reconnect its table and report outputs"
            )
        identity = contract.get("contract_sha256") if isinstance(contract, dict) else None
        candidate_key = (identity, binding)
        try:
            restored = restore_contract_units(table, contract, units)
            if table_fingerprint(restored) != binding:
                raise ValueError("table fingerprint mismatch with upstream output binding")
        except ValueError as exc:
            errors.append(exc)
            invalid_bindings[candidate_key] = exc
            continue
        matched[candidate_key] = restored
    if len(matched) != 1:
        if not matched and errors:
            raise ValueError(f"upstream table contract mismatch: {errors[0]}") from errors[0]
        raise ValueError(
            "upstream table contracts are ambiguous or do not match this table; "
            "connect its declared table output"
        )
    candidate_key, restored = next(iter(matched.items()))
    if candidate_key in invalid_bindings:
        raise ValueError(f"conflicting output unit/binding metadata: {invalid_bindings[candidate_key]}")
    return restored


def execute(component, key):
    from materials_quality.batch.packet import is_batch

    upstream = _object(getattr(component, "input_data", None))
    if is_batch(upstream):
        from materials_quality.batch.execution import execute_batch

        return execute_batch(component, key, upstream, _operation_config(component, key), _execute_single)
    return _execute_single(component, key)


def _execute_single(component, key, config_override=None):
    started = perf_counter()
    config = _operation_config(component, key) if config_override is None else deepcopy(config_override)
    upstream = _object(getattr(component, "input_data", None))
    data = dict(_unwrap(upstream))
    reports = [_object(x) for x in (getattr(component, "reports", None) or [])]
    assets = _asset_paths(data, reports)
    config = _resolve_assets(config, assets)
    upload = getattr(component, "source_file", None)
    if upload:
        if isinstance(upload, list):
            if len(upload) != 1:
                raise ValueError("Upload exactly one source file")
            upload = upload[0]
        config["path"] = component.resolve_path(upload)
    data, ui_task = _form_task_data(component, key, config, data)
    table = getattr(component, "input_table", None)
    if isinstance(table, str) and not table:
        table = None
    table = _restore_contract(table, upstream)
    tables = getattr(component, "input_tables", None)
    if tables is None:
        tables = []
    if isinstance(tables, pd.DataFrame):
        tables = [tables]
    envelopes = [upstream, *reports]
    files = _file_hashes(
        _input_paths(key, config, data, reports),
        paths=True,
        max_store_entries=config.get("max_store_entries", 100_000),
        max_store_bytes=config.get("max_file_bytes", 1024**3),
    )
    include_source = key == "preprocess.merge"
    signature = _digest(
        [
            key,
            config,
            upstream,
            data,
            _frame_value(table, include_source=include_source),
            [_frame_value(t, include_source=include_source) for t in tables],
            reports,
            files,
            ui_task,
        ]
    )
    # Component.ctx is graph-global and returns a fresh {} for standalone calls.
    # Keep this transient cache per component, never in the serialized graph.
    cached = component._ctx.get("science_execution")
    if key != "materials.analysis_plan" and cached and cached["signature"] == signature:
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
                for p in e.get("data", {}).get("figure_previews", e.get("artifacts", []))
                if Path(p).suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
            ],
        }
    operation = get(key)["callable"]
    if key == "lit.result_evidence" and upstream.get("schema_version") == "science-result/1":
        current_table = table_fingerprint(table) if table is not None else None
        if current_table not in {upstream.get("table_fingerprint"), upstream.get("features_fingerprint")}:
            raise ValueError("结果表与接入的上游报告不一致，请连接产生该表的节点报告。")
        data = {
            **data,
            "upstream_execution": {
                "operation": upstream.get("operation"),
                "provenance": upstream.get("provenance", {}),
                "execution_status": upstream.get("execution_status"),
                "warnings": upstream.get("warnings", []),
                "table_fingerprint": current_table,
            },
        }
    try:
        if key == "materials.analysis_plan":
            from .research_plan import run_research_plan

            result, run = run_research_plan(table, config, component._ctx.get("analysis_plan_previous"))
            component._ctx["analysis_plan_previous"] = run
        else:
            result = operation(table, config=config, data=data, tables=tables)
    except ImportError as exc:
        raise ValueError(
            "This method needs the science dependencies: pip install '.[science]' — " + str(exc)
        ) from exc
    if not isinstance(result, NodeResult):
        raise TypeError(f"{key} returned an invalid operation result")
    if result.table is not None and read_contract(table) is not None:
        preserving = {
            "preprocess.filter": "filter",
            "preprocess.normalize": "normalize",
            "preprocess.units": "units",
            "stats.grouped": "grouped",
            "export.table": "identity",
        }
        # Explicit declarations made by the operation take precedence. Stale
        # pandas attrs copied from its input must instead be transformed.
        carried = result.table.attrs.get("contract")
        if carried is None or carried == read_contract(table):
            result.table = propagate_contract(table, result.table, preserving.get(key, key), config)
            for warning in result.table.attrs.get("contract_warnings", []):
                if warning not in result.warnings:
                    result.warnings.append(warning)
    if key in {"materials.spectra", "materials.xrd"}:
        from .features import features_for

        result.features = features_for(
            key, result, getattr(component, "batch_item_id", None), getattr(component, "batch_group", None)
        )
    for field in ("table", "features"):
        frame = getattr(result, field)
        contract = read_contract(frame)
        if contract is not None:
            setattr(result, field, restore_contract_units(frame, contract))
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
    if ui_task is not None:
        current["ui_task"] = ui_task
    envelope = _redact(
        json_value(
            {
                "schema_version": "science-result/1",
                "operation": key,
                "execution_status": result_data.get("execution_status", "completed"),
                "data": result_data,
                "table_contract": read_contract(result.table),
                "features_contract": read_contract(result.features),
                "table_fingerprint": None if result.table is None else table_fingerprint(result.table),
                "features_fingerprint": None
                if result.features is None
                else table_fingerprint(result.features),
                "warnings": result.warnings,
                "artifacts": result.artifacts,
                "elapsed_seconds": perf_counter() - started,
                "features_preview": None
                if result.features is None
                else {
                    "total_rows": len(result.features),
                    "columns": list(result.features.columns),
                    "records": result.features.head(20).to_dict("records"),
                    "units": result.features.attrs.get("units", {}),
                },
                "table_available": result.table is not None,
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
    state = "完成" if result_data.get("execution_status", "completed") == "completed" else "未全部完成"
    component.status = f"{get(key)['title']}：{state}；{len(result.warnings)} 条提示"
    return result, envelope


def output_table(component, key):
    result, envelope = execute(component, key)
    if result.table is None:
        if getattr(component, "ui_contract_version", 1) >= 2:
            raise ValueError(f"{get(key)['title']} 当前方法不提供表格；请使用结果与追溯或生成文件输出。")
        legacy = DataFrame()
        legacy.attrs["table_available"] = False
        legacy.attrs["absence_reason"] = "旧版兼容端口；该操作未产生表格，并非空数据集。"
        return legacy
    table = DataFrame(result.table.copy(deep=True))
    table.attrs = deepcopy(result.table.attrs)
    asset_paths = envelope.get("data", {}).get("asset_paths")
    if isinstance(asset_paths, dict):
        table.attrs["asset_paths"] = deepcopy(asset_paths)
    return table


def output_report(component, key):
    return Data(data=execute(component, key)[1])


def output_features(component, key):
    result, envelope = execute(component, key)
    frame = result.features
    if envelope.get("schema_version") == "materials-batch/1":
        from materials_quality.batch.packet import unpack_table

        frames = [
            unpack_table(item["features"])
            for item in envelope["items"]
            if item["status"] == "completed" and item.get("features") is not None
        ]
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if frame is None:
        raise ValueError("该操作未提供特征表。")
    output = DataFrame(frame.copy(deep=True))
    output.attrs = deepcopy(frame.attrs)
    return output


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
    if envelope.get("schema_version") == "materials-batch/1":
        counts = envelope["counts"]
        return Message(
            text=f"{get(key)['title']}：共 {counts['total']} 项，完成 {counts['completed']} 项，"
            f"失败 {counts['failed']} 项，跳过 {counts['skipped']} 项。"
        )
    table = envelope["table_summary"]
    table_text = (
        "未产生表格（请查看结构化结果或文件）"
        if table is None
        else f"{table['rows']} 行，{len(table['columns'])} 列"
    )
    status_text = (
        "已完成" if envelope.get("execution_status") == "completed" else "未全部完成，请查看步骤诊断"
    )
    return Message(
        text=f"{get(key)['title']}{status_text}。结果表：{table_text}；"
        f"生成文件 {len(envelope['artifacts'])} 个。\n" + "\n".join(envelope["warnings"])
    )

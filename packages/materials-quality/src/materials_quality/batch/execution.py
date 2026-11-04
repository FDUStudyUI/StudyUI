"""Execute an unchanged scientific operation independently for each batch item."""

import hashlib
import tempfile
from copy import deepcopy
from pathlib import Path

from lfx.schema import Data

from materials_quality.common import json_value
from materials_quality.context import table_fingerprint
from materials_quality.science.contracts import NodeResult
from materials_quality.science.table_contract import propagate_contract, read_contract

from .packet import combined_table, make_batch, pack_table, unpack_table, validate_batch


class _ItemView:
    """Isolate data/cache while reusing the parent's validated native controls."""

    def __init__(self, parent, item, table):
        self.parent = parent
        self.batch_item_id = item["id"]
        self.batch_group = item["source"].get("group")
        self.input_table = table
        self.input_data = Data(data=deepcopy(item["report"] or {}))
        self.source_file = None
        self.reports = getattr(parent, "reports", None) or []
        self.input_tables = getattr(parent, "input_tables", None)
        if self.input_tables is None:
            self.input_tables = []
        self._ctx = parent._ctx.setdefault("batch_item_cache", {}).setdefault(item["id"], {})

    def __getattr__(self, name):
        return getattr(self.parent, name)


def _identity(frame, item):
    if frame is None:
        return None
    frame = frame.copy(deep=True)
    for column, value in (("batch_item_id", item["id"]), ("batch_label", item["label"])):
        if (
            column in frame
            and not frame[column].map(lambda x, expected=value: isinstance(x, str) and x == expected).all()
        ):
            raise ValueError(f"批次标识列与当前样品冲突：{column}")
        frame[column] = value
    if "group" in item["source"]:
        value = item["source"]["group"]
        if "group" in frame and not frame["group"].eq(value).all():
            raise ValueError("文件条件与已有 group 列冲突")
        frame["group"] = value
    return frame


def _rename(frame, mapping):
    if frame is None or not mapping:
        return frame
    from .source import validate_rename_columns

    mapping = validate_rename_columns(mapping)
    if set(mapping) - set(frame):
        raise ValueError("列映射的源列不存在：" + ", ".join(sorted(set(mapping) - set(frame))))
    columns = [mapping.get(name, name) for name in frame.columns]
    if len(set(columns)) != len(columns):
        raise ValueError("列映射会产生重名列")
    renamed = frame.rename(columns=mapping).copy(deep=True)
    renamed.attrs = deepcopy(frame.attrs)
    if "units" in renamed.attrs:
        renamed.attrs["units"] = {mapping.get(k, k): v for k, v in renamed.attrs["units"].items()}
    return propagate_contract(frame, renamed, "rename", {"rename": mapping})


def _check_source(item, checked):
    path = item["source"].get("file_path")
    expected = item["source"].get("source_sha256")
    if not path or not expected:
        return
    if path in checked:
        if checked[path] != expected:
            raise ValueError("同一源文件具有不一致的来源指纹")
        return
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError("源文件已变化，请重新运行批量入口")
    checked[path] = expected


def execute_batch(component, key, packet, config, single_executor):
    validate_batch(packet)
    if getattr(component, "source_file", None):
        raise ValueError("批量输入已指定各项文件，请清空本节点的单文件上传")
    if key.startswith(("io.", "extract.")) and (config.get("path") or config.get("file_path")):
        raise ValueError("批量文件由入口提供，请清空本节点的固定路径")
    roots = component._ctx.setdefault("batch_output_roots", {})
    root_key = str(config.get("output_dir") or "") + ":" + packet["batch_id"]
    if root_key not in roots:
        roots[root_key] = str(
            Path(config["output_dir"]).resolve()
            if config.get("output_dir")
            else Path(tempfile.mkdtemp(prefix="studyui-batch-"))
        )
    items, checked = [], {}
    for original in packet["items"]:
        item = deepcopy(original)
        if item["status"] != "completed":
            items.append(item)
            continue
        try:
            _check_source(item, checked)
            table = unpack_table(item["table"]) if item["table"] is not None else None
            table = _identity(table, item)
            item_config = deepcopy(config)
            token = hashlib.sha256(item["id"].encode()).hexdigest()[:16]
            item_config["output_dir"] = str(Path(roots[root_key]) / token / key.replace(".", "-"))
            view = _ItemView(component, item, table)
            result, report = single_executor(view, key, config_override=item_config)
            result_table = result.table
            if original["table"] is None:
                result_table = _rename(result_table, packet.get("rename_columns", {}))
            result_table = _identity(result_table, item)
            features = _identity(result.features, item)
            report = deepcopy(report)
            report["table_contract"] = read_contract(result_table)
            report["features_contract"] = read_contract(features)
            report["table_fingerprint"] = None if result_table is None else table_fingerprint(result_table)
            report["features_fingerprint"] = None if features is None else table_fingerprint(features)
            for frame, preview_field, limit in (
                (result_table, "table_preview", 100),
                (features, "features_preview", 20),
            ):
                if frame is not None and isinstance(report.get(preview_field), dict):
                    report[preview_field].update(
                        json_value(
                            {
                                "columns": list(frame.columns),
                                "units": frame.attrs.get("units", {}),
                                "records": frame.head(limit).to_dict("records"),
                            }
                        )
                    )
            if result_table is not None:
                report["table_summary"] = {"rows": len(result_table), "columns": list(result_table.columns)}
            item["table"] = pack_table(result_table) if result_table is not None else None
            if features is not None:
                item["features"] = pack_table(features)
            if item["report"]:
                item["history"].append(item["report"])
            item["report"] = deepcopy(report)
            item["error"] = None
        except Exception as error:
            if packet["on_error"] == "stop":
                raise ValueError(f"{item['label']} ({item['id']})：{error}") from error
            item["status"] = "failed"
            item["error"] = {"stage": key, "message": str(error), "type": type(error).__name__}
            item["table"] = None
            item.pop("features", None)
        items.append(item)
    output = make_batch(items, batch_id=packet["batch_id"], on_error=packet["on_error"])
    output["rename_columns"] = deepcopy(packet.get("rename_columns", {}))
    files = []
    for item in items:
        for report in [*item["history"], item["report"]]:
            if isinstance(report, dict):
                files.extend(report.get("artifacts", []))
    output["artifacts"] = list(dict.fromkeys(files))
    component.status = (
        f"{output['counts']['completed']}/{output['counts']['total']} 完成；{output['counts']['failed']} 失败"
    )
    return NodeResult(table=combined_table(output), data=output, artifacts=output["artifacts"]), output

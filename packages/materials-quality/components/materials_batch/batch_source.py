"""Native multi-upload and grouped-specimen source for reusable batch flows."""

from copy import deepcopy
from pathlib import Path

from lfx.base.data.storage_utils import parse_storage_path
from lfx.custom import Component
from lfx.io import DataFrameInput, DictInput, DropdownInput, FileInput, IntInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message
from lfx.utils.file_path_security import (
    StorageNamespaceError,
    component_file_access_scopes,
    enforce_local_file_access,
)

from materials_quality.batch.source import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ITEMS,
    _hash_file,
    _paths,
    source_batch,
    source_fingerprint,
)
from materials_quality.science.io_nodes import table_import


class MaterialBatchInput(Component):
    display_name = "材料批量·文件与样品入口"
    description = "多选文件或按样品列拆分完整数据；一份文件或一组样品作为独立任务。"
    name = "MaterialBatchInput"
    icon = "Files"
    inputs = [
        DropdownInput(
            name="source_mode",
            display_name="输入方式",
            options=["files", "grouped"],
            value="files",
            real_time_refresh=True,
        ),
        FileInput(
            name="source_files",
            display_name="选择文件（可多选）",
            is_list=True,
            value=[],
            file_types=[
                "csv",
                "tsv",
                "txt",
                "xlsx",
                "xls",
                "xlsm",
                "ods",
                "xy",
                "json",
                "pdf",
                "png",
                "jpg",
                "jpeg",
                "tif",
                "tiff",
                "jdx",
                "xrdml",
                "brml",
            ],
            real_time_refresh=True,
            required=False,
        ),
        StrInput(
            name="file_paths",
            display_name="服务器路径或 glob",
            is_list=True,
            value=[],
            advanced=True,
            info="逐项填写服务器上的路径或通配符，如 data/*SERS map.csv。",
        ),
        DropdownInput(
            name="group_from",
            display_name="文件条件来源",
            options=["none", "parent", "filename_prefix"],
            value="none",
            advanced=True,
        ),
        StrInput(name="group_separator", display_name="文件名前缀分隔符", value="_", advanced=True),
        DataFrameInput(name="input_table", display_name="待分组表格", required=False),
        DropdownInput(
            name="sample_column",
            display_name="样品列",
            options=[],
            value="",
            combobox=True,
            required=False,
            info="上传表格后显示实际列名；上游连接表格可手动填写列名。",
        ),
        DictInput(name="rename_columns", display_name="列名统一（原名 → 标准名）", value={}, advanced=True),
        DropdownInput(
            name="on_error", display_name="单项出错时", options=["continue", "stop"], value="continue"
        ),
        IntInput(name="max_items", display_name="最多任务数", value=DEFAULT_MAX_ITEMS, advanced=True),
        IntInput(name="max_bytes", display_name="单文件最大字节数", value=DEFAULT_MAX_BYTES, advanced=True),
    ]
    outputs = [
        Output(name="batch", display_name="批次数据", method="build_batch", group_outputs=True),
        Output(name="manifest", display_name="样品与文件清单", method="build_manifest", group_outputs=True),
        Output(name="summary", display_name="运行摘要", method="build_summary", group_outputs=True),
    ]

    def to_frontend_node(self, *args, **kwargs):
        from materials_quality.batch.native import prepare_form

        result = super().to_frontend_node(*args, **kwargs)
        template = result["data"]["node"]["template"]
        self.update_build_config(template, self.source_mode, "source_mode")
        return prepare_form(result)

    def _packet(self):
        names = (
            "source_mode",
            "source_files",
            "file_paths",
            "input_table",
            "sample_column",
            "rename_columns",
            "on_error",
            "max_items",
            "max_bytes",
            "group_from",
            "group_separator",
        )
        parameters = {name: getattr(self, name) for name in names}
        if isinstance(parameters["input_table"], str) and not parameters["input_table"]:
            parameters["input_table"] = None
        # UI upload values are Langflow storage-relative; resolve them through SDK.
        uploads = self.source_files or []
        if isinstance(uploads, str):
            uploads = [uploads]
        # LFX multi-upload callbacks can append the same selected storage key
        # twice. A selection is a set of files, not duplicated experiments.
        parameters["source_files"] = list(dict.fromkeys(self._resolve_source_path(p) for p in uploads))
        parameters["file_paths"] = [self._resolve_source_path(str(p)) for p in _paths(self.file_paths)]
        signature = source_fingerprint(parameters)
        cached = getattr(self, "_batch_source_cache", None)
        if cached is None or cached[0] != signature:
            self._batch_source_cache = (signature, source_batch(**parameters))
        return deepcopy(self._batch_source_cache[1])

    def _resolve_source_path(self, value):
        if parse_storage_path(str(value)):
            try:
                value = self.get_full_path(str(value))
            except StorageNamespaceError:
                raise
            except (ValueError, AttributeError):
                value = self.resolve_path(str(value))
        else:
            value = self.resolve_path(str(value))
        return str(enforce_local_file_access(Path(value), scope_ids=component_file_access_scopes(self)))

    def build_batch(self) -> Data:
        return Data(data=self._packet())

    def build_manifest(self) -> DataFrame:
        packet = self._packet()
        return DataFrame(
            [
                {
                    "batch_id": packet["batch_id"],
                    "item_id": item["id"],
                    "label": item["label"],
                    "status": item["status"],
                    "file_path": item["source"].get("file_path"),
                    "source_sha256": item["source"].get("source_sha256"),
                    "error": None if item["error"] is None else item["error"]["message"],
                }
                for item in packet["items"]
            ]
        )

    def build_summary(self) -> Message:
        packet = self._packet()
        counts = packet["counts"]
        return Message(
            text=f"批次 {packet['batch_id']}：{counts['total']} 项，"
            f"可处理 {counts['completed']}，失败 {counts['failed']}，"
            f"跳过 {counts['skipped']}；状态 {packet['execution_status']}。"
        )

    def update_build_config(self, build_config, field_value, field_name=None):
        mode = (
            field_value if field_name == "source_mode" else build_config["source_mode"].get("value", "files")
        )
        for name in ("input_table", "sample_column"):
            build_config[name]["show"] = mode == "grouped"
        if field_name in {"source_files", "input_table", "source_mode"} and mode == "grouped":
            try:
                frame = field_value if field_name == "input_table" else None
                if frame is None:
                    selected = (
                        field_value
                        if field_name == "source_files"
                        else build_config["source_files"].get("value")
                    )
                    if isinstance(selected, str):
                        selected = [selected]
                    if not isinstance(selected, list) or len(selected) != 1:
                        raise ValueError("choose one table file")
                    path = self._resolve_source_path(selected[0])
                    _hash_file(_paths(path)[0], DEFAULT_MAX_BYTES)
                    frame = table_import(config={"path": str(path)}).table
                build_config["sample_column"]["options"] = frame.columns.tolist()
            except (OSError, ValueError, TypeError, AttributeError):
                selected_column = build_config["sample_column"].get("value")
                build_config["sample_column"]["options"] = [selected_column] if selected_column else []
        return build_config

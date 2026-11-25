"""Native window and unit controls for electrical curve analysis."""

from copy import deepcopy

from lfx.custom import Component
from lfx.io import DataFrameInput, DropdownInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.native import native_frame, prepare_form
from materials_quality.common import json_value
from materials_quality.context import table_fingerprint
from materials_quality.science.electrical import OPERATION, PHOTO_TIMES, analyze_electrical
from materials_quality.science.table_contract import contract_identity, read_contract


class ElectricalAnalysis(Component):
    display_name = "材料批量·I–V 与光响应分析"
    description = "逐曲线拟合指定电压窗，或按显式光照时刻测量幅度与 10%–90% 响应时间。"
    name = "ElectricalAnalysis"
    icon = "Zap"

    inputs = [
        DataFrameInput(name="input_table", display_name="完整测量点表（按采集顺序）", required=True),
        DropdownInput(
            name="mode",
            display_name="分析方式",
            options=["iv", "photoresponse"],
            value="iv",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="curve_id",
            display_name="曲线 ID 列",
            options=["curve_id"],
            value="curve_id",
            combobox=True,
        ),
        DropdownInput(
            name="sample_id",
            display_name="试样 ID 列（可选）",
            options=["", "sample_id"],
            value="",
            combobox=True,
            info="留空时沿用上游明确声明的试样列。",
        ),
        DropdownInput(
            name="current",
            display_name="电流列",
            options=["current"],
            value="current",
            combobox=True,
        ),
        DropdownInput(
            name="current_unit",
            display_name="电流单位（必须声明）",
            options=["A", "mA", "uA", "nA", "pA"],
            value="",
            combobox=True,
        ),
        DropdownInput(
            name="voltage",
            display_name="电压列",
            options=["voltage"],
            value="voltage",
            combobox=True,
        ),
        DropdownInput(
            name="voltage_unit",
            display_name="电压单位（必须声明）",
            options=["V", "mV", "uV"],
            value="",
            combobox=True,
        ),
        DropdownInput(
            name="sweep",
            display_name="扫描分支列（可选）",
            options=["", "sweep"],
            value="",
            combobox=True,
            info="每个分支的电压须严格单调。往返扫描须提供分支标签。",
        ),
        StrInput(name="voltage_min", display_name="拟合电压下限（含端点）", value=""),
        StrInput(name="voltage_max", display_name="拟合电压上限（含端点）", value=""),
        DropdownInput(
            name="time",
            display_name="时间列",
            options=["time"],
            value="time",
            combobox=True,
            show=False,
        ),
        DropdownInput(
            name="time_unit",
            display_name="时间单位（必须声明）",
            options=["ms", "s", "min", "h"],
            value="",
            combobox=True,
            show=False,
        ),
        StrInput(name="baseline_start", display_name="暗态基线窗口开始", value="", show=False),
        StrInput(name="baseline_end", display_name="暗态基线窗口结束", value="", show=False),
        StrInput(name="light_on", display_name="开光时刻", value="", show=False),
        StrInput(name="on_plateau_start", display_name="亮态平台窗口开始", value="", show=False),
        StrInput(name="on_plateau_end", display_name="亮态平台窗口结束", value="", show=False),
        StrInput(name="light_off", display_name="关光时刻", value="", show=False),
        StrInput(name="recovery_end", display_name="恢复搜索窗口结束", value="", show=False),
    ]
    outputs = [
        Output(name=name, display_name=label, method=f"build_{name}", group_outputs=True, cache=False)
        for name, label in (
            ("features", "逐曲线特征与状态"),
            ("curves", "原始测量与派生曲线"),
            ("report", "分析报告与追溯"),
            ("summary", "运行摘要"),
        )
    ]

    def to_frontend_node(self, *args, **kwargs):
        node = super().to_frontend_node(*args, **kwargs)
        self.update_build_config(node["data"]["node"]["template"], self.mode, "mode")
        return prepare_form(node)

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name == "mode":
            build_config["mode"]["value"] = field_value
        iv = build_config["mode"]["value"] == "iv"
        for key in ("voltage", "voltage_unit", "sweep", "voltage_min", "voltage_max"):
            build_config[key]["show"] = iv
        for key in ("time", "time_unit", *PHOTO_TIMES):
            build_config[key]["show"] = not iv
        frame = field_value if field_name == "input_table" else getattr(self, "input_table", None)
        if hasattr(frame, "columns"):
            columns = list(frame.columns)
            for key in ("curve_id", "sample_id", "current", "voltage", "sweep", "time"):
                field = build_config[key]
                field["options"] = list(
                    dict.fromkeys(
                        [
                            *([""] if key in {"sample_id", "sweep"} else []),
                            *columns,
                            *([field["value"]] if field["value"] else []),
                        ]
                    )
                )
        return build_config

    def _config(self):
        iv = self.mode == "iv"
        mode_fields = ("voltage", "voltage_unit", "sweep") if iv else ("time", "time_unit")
        fields = ("mode", "curve_id", "sample_id", "current", "current_unit", *mode_fields)
        config = {key: getattr(self, key) for key in fields}
        for key in ("voltage_min", "voltage_max") if iv else PHOTO_TIMES:
            value = getattr(self, key)
            try:
                config[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} requires an explicit numeric coordinate") from exc
        return config

    def _result(self):
        config = self._config()
        signature = (table_fingerprint(self.input_table), contract_identity(self.input_table), config)
        cached = self._ctx.get(OPERATION)
        if cached is None or cached[0] != signature:
            cached = (signature, analyze_electrical(self.input_table, config))
            self._ctx[OPERATION] = cached
        return cached

    def build_features(self) -> DataFrame:
        return native_frame(self._result()[1].features)

    def build_curves(self) -> DataFrame:
        return native_frame(self._result()[1].table)

    def build_report(self) -> Data:
        (table_hash, contract_hash, config), result = self._result()
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": OPERATION,
                "data": deepcopy(result.data),
                "warnings": list(result.warnings),
                "artifacts": [],
                "table_contract": read_contract(result.table),
                "table_fingerprint": table_fingerprint(result.table),
                "features_contract": read_contract(result.features),
                "features_fingerprint": table_fingerprint(result.features),
                "features_preview": json_value(
                    {
                        "total_rows": len(result.features),
                        "records": result.features.head(20).to_dict("records"),
                        "units": result.features.attrs["units"],
                    }
                ),
                "provenance": {
                    "input_table_fingerprint": table_hash,
                    "input_contract_sha256": contract_hash,
                    "parameters": deepcopy(config),
                    "raw_preserved": True,
                },
            }
        )

    def build_summary(self) -> Message:
        result = self._result()[1].data
        counts = result["status_counts"]
        return Message(
            text=(
                f"分析 {result['curve_count']} 个曲线或扫描分支。完整 {counts.get('ok', 0)}，"
                f"部分 {counts.get('partial', 0)}，无效 {counts.get('invalid', 0)}。"
            )
        )

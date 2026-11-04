"""Native SDK forms for observed time-series analysis."""

import hashlib
import json
from copy import deepcopy

import pandas as pd
from lfx.custom import Component
from lfx.io import BoolInput, DataFrameInput, DropdownInput, FloatInput, IntInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.native import native_frame, prepare_form
from materials_quality.context import table_fingerprint
from materials_quality.science.series_dynamics import analyze_series


class SeriesDynamics(Component):
    display_name = "材料批量·时间序列动态分析"
    description = "每条完整曲线独立平滑、异常点/持续增长/窗口变化检测及 HAC 线性趋势区间。"
    name = "SeriesDynamics"
    icon = "ChartLine"
    inputs = [
        DataFrameInput(name="input_table", display_name="完整时间序列表", required=True),
        DropdownInput(
            name="curve_column",
            display_name="曲线 ID 列",
            options=["curve_id"],
            value="curve_id",
            combobox=True,
        ),
        DropdownInput(
            name="time_column",
            display_name="时间列（数值经过时间）",
            options=["time"],
            value="time",
            combobox=True,
        ),
        DropdownInput(
            name="value_column", display_name="数值列", options=["value"], value="value", combobox=True
        ),
        DropdownInput(
            name="group_column", display_name="分组列（可选）", options=["", "group"], value="", combobox=True
        ),
        DropdownInput(
            name="time_unit",
            display_name="经过时间单位（必须声明）",
            options=["ms", "s", "min", "h", "day"],
            value="",
        ),
        StrInput(name="value_unit", display_name="数值单位", value="unspecified"),
        DropdownInput(
            name="smoothing", display_name="平滑方法", options=["none", "moving", "savgol"], value="none"
        ),
        IntInput(name="smooth_window", display_name="平滑窗口（奇数点）", value=5),
        IntInput(name="smooth_order", display_name="SG 多项式阶数", value=2, advanced=True),
        FloatInput(name="spike_threshold", display_name="局部中位残差 MAD 异常阈值", value=3.5),
        IntInput(name="growth_min_points", display_name="持续增长最少点数", value=3),
        FloatInput(name="growth_min_duration", display_name="持续增长最短经过时间", value=0.0),
        FloatInput(name="growth_min_slope", display_name="持续增长最低斜率", value=0.0),
        DropdownInput(
            name="change_method", display_name="变化检测", options=["none", "window"], value="window"
        ),
        IntInput(name="change_window", display_name="变化检测单侧窗口点数", value=5),
        FloatInput(name="change_threshold", display_name="窗口均值差/标准误阈值", value=3.0),
        IntInput(name="hac_lags", display_name="HAC 最大滞后点数", value=1, advanced=True),
        FloatInput(name="alpha", display_name="置信区间显著性 α", value=0.05, advanced=True),
        BoolInput(name="sort", display_name="按时间排序（重复时间仍拒绝）", value=False),
    ]
    outputs = [
        Output(name=n, display_name=d, method=m, group_outputs=True)
        for n, d, m in [
            ("features", "逐曲线趋势特征", "build_features"),
            ("curves", "完整处理曲线", "build_curves"),
            ("events", "异常与增长/变化事件", "build_events"),
            ("report", "结果与追溯", "build_report"),
            ("summary", "运行摘要", "build_summary"),
        ]
    ]

    def _config(self):
        c = {
            key: getattr(self, key)
            for key in (
                "time_unit",
                "value_unit",
                "smoothing",
                "smooth_window",
                "smooth_order",
                "spike_threshold",
                "growth_min_points",
                "growth_min_duration",
                "growth_min_slope",
                "change_method",
                "change_window",
                "change_threshold",
                "hac_lags",
                "alpha",
                "sort",
            )
        }
        c.update(curve_id=self.curve_column, time=self.time_column, value=self.value_column)
        if self.group_column:
            c["group"] = self.group_column
        return c

    def _result(self):
        c = self._config()
        signature = hashlib.sha256(
            (table_fingerprint(self.input_table) + json.dumps(c, sort_keys=True)).encode()
        ).hexdigest()
        cached = self._ctx.get("series_dynamics")
        if cached is None or cached[0] != signature:
            cached = (signature, analyze_series(self.input_table, c))
            self._ctx["series_dynamics"] = cached
        return cached

    def build_features(self) -> DataFrame:
        return native_frame(self._result()[1].features)

    def build_curves(self) -> DataFrame:
        return native_frame(self._result()[1].table)

    def to_frontend_node(self, *args, **kwargs):
        return prepare_form(super().to_frontend_node(*args, **kwargs))

    def build_events(self) -> DataFrame:
        return DataFrame(deepcopy(self._result()[1].data["events"]))

    def build_report(self) -> Data:
        signature, r = self._result()
        result_data = deepcopy(r.data)
        input_table = getattr(self, "input_table", None)
        asset_paths = getattr(input_table, "attrs", {}).get("asset_paths")
        if isinstance(asset_paths, dict):
            result_data["asset_paths"] = deepcopy(asset_paths)
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": "materials.series_dynamics",
                "data": result_data,
                "warnings": list(r.warnings),
                "artifacts": [],
                "provenance": {
                    "input_sha256": signature,
                    "parameters": self._config(),
                    "raw_preserved": True,
                },
            }
        )

    def build_summary(self) -> Message:
        r = self._result()[1]
        return Message(
            text=f"完成 {r.data['curve_count']} 条完整时间曲线，{len(r.data['events'])} 个描述性事件；"
            "趋势区间使用 HAC 协方差。"
        )

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name == "input_table" and isinstance(field_value, pd.DataFrame):
            for key in ("curve_column", "time_column", "value_column", "group_column"):
                build_config[key]["options"] = ([""] if key == "group_column" else []) + list(
                    field_value.columns
                )
        return build_config

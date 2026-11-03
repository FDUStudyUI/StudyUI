"""Native forms for many independent dark-field, Raman or other spectral curves."""

import hashlib
import json
from copy import deepcopy

import pandas as pd
from lfx.custom import Component
from lfx.io import (
    BoolInput,
    DataFrameInput,
    DropdownInput,
    FloatInput,
    IntInput,
    Output,
    StrInput,
    TableInput,
)
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.native import native_frame, prepare_form
from materials_quality.context import table_fingerprint
from materials_quality.science.spectrum_batch import analyze_spectra


class BatchSpectrumAnalyzer(Component):
    display_name = "材料批量·逐曲线光谱分析"
    description = "按曲线 ID 独立扣基线、平滑、寻峰和积分；输出结构化特征、完整曲线及分组统计。"
    name = "BatchSpectrumAnalyzer"
    icon = "ChartNoAxesCombined"
    inputs = [
        DataFrameInput(
            name="input_table",
            display_name="完整光谱表",
            required=True,
            info="每行一个测量点，含 curve_id、x、y，可选 group；同一曲线不可跨组。",
        ),
        DropdownInput(
            name="curve_column",
            display_name="曲线 ID 列",
            options=["curve_id"],
            value="curve_id",
            combobox=True,
        ),
        DropdownInput(name="x_column", display_name="光谱坐标列", options=["x"], value="x", combobox=True),
        DropdownInput(name="y_column", display_name="强度列", options=["y"], value="y", combobox=True),
        DropdownInput(
            name="group_column",
            display_name="分组列（留空自动识别 group）",
            options=["", "group"],
            value="",
            combobox=True,
            required=False,
        ),
        DropdownInput(
            name="x_unit",
            display_name="坐标单位",
            options=["nm", "um", "cm^-1", "eV", "deg"],
            value="",
            combobox=True,
            info="必须声明；λ10 仅适用于长度单位，不自动反演波数或能量。",
        ),
        StrInput(
            name="intensity_unit",
            display_name="强度单位",
            value="",
            info="填写仪器实际单位，如 counts、a.u. 或 absorbance；不自动猜测。",
        ),
        DropdownInput(
            name="baseline_method",
            display_name="基线方法",
            options=["none", "constant", "linear"],
            value="none",
            real_time_refresh=True,
        ),
        FloatInput(name="baseline_value", display_name="常数基线值", value=0.0, advanced=True),
        BoolInput(name="smooth", display_name="Savitzky–Golay 平滑", value=False, real_time_refresh=True),
        IntInput(name="smooth_window", display_name="平滑窗口（奇数点数）", value=7),
        IntInput(name="smooth_order", display_name="平滑多项式阶数", value=2),
        BoolInput(
            name="auto_prominence",
            display_name="自动峰突出度（每条曲线振幅的 5%）",
            value=True,
            real_time_refresh=True,
        ),
        FloatInput(name="prominence", display_name="最小峰突出度（强度单位）", value=0.1),
        IntInput(name="peak_distance", display_name="峰最小间距（测量点数）", value=1, advanced=True),
        TableInput(
            name="area_ranges",
            display_name="定量积分区间",
            value=[],
            trigger_text="编辑积分区间",
            info="坐标单位与输入相同；留空积分全测量区间。峰基底面积可能重叠。",
            table_schema=[
                {"name": "lower", "display_name": "下限", "type": "float", "edit_mode": "inline"},
                {"name": "upper", "display_name": "上限", "type": "float", "edit_mode": "inline"},
            ],
        ),
        DropdownInput(
            name="normalization",
            display_name="曲线归一化",
            options=["none", "max", "l2", "area"],
            value="none",
            info="寻峰和定量积分使用归一化前的扣基线平滑信号。",
        ),
        BoolInput(
            name="lambda10_enabled",
            display_name="提取耦合模式 λ₁₀ 候选峰",
            value=False,
            real_time_refresh=True,
            info="λ₁₀ 是耦合等离激元模式共振波长；必须按实验提供搜索窗口。",
        ),
        FloatInput(name="lambda10_min_nm", display_name="λ₁₀ 搜索窗口下限（nm）", value=0.0),
        FloatInput(name="lambda10_max_nm", display_name="λ₁₀ 搜索窗口上限（nm）", value=0.0),
        DropdownInput(
            name="lambda10_selection",
            display_name="λ₁₀ 候选峰选择",
            options=["highest_prominence", "redmost"],
            value="highest_prominence",
            info="按最大突出度或最长波长选择；多候选会标记歧义，需结合实验复核。",
        ),
        BoolInput(name="sort", display_name="按坐标排序（不合并重复点）", value=False, advanced=True),
        DropdownInput(
            name="on_error", display_name="单曲线出错时", options=["continue", "stop"], value="continue"
        ),
        IntInput(
            name="bootstrap_samples", display_name="分组均值 bootstrap 次数（0 关闭）", value=0, advanced=True
        ),
        IntInput(name="bootstrap_seed", display_name="Bootstrap 固定随机种子", value=0, advanced=True),
    ]
    outputs = [
        Output(name="features", display_name="逐峰结构化特征", method="build_features", group_outputs=True),
        Output(name="curves", display_name="完整处理曲线", method="build_curves", group_outputs=True),
        Output(name="groups", display_name="独立曲线分组统计", method="build_groups", group_outputs=True),
        Output(name="report", display_name="结果与追溯", method="build_report", group_outputs=True),
        Output(name="summary", display_name="运行摘要", method="build_summary", group_outputs=True),
    ]

    def _config(self):
        config = {
            "curve_id": self.curve_column,
            "x": self.x_column,
            "y": self.y_column,
            "x_unit": self.x_unit,
            "intensity_unit": self.intensity_unit,
            "baseline": {"method": self.baseline_method, "value": self.baseline_value},
            "smooth_window": self.smooth_window if self.smooth else 0,
            "smooth_order": self.smooth_order,
            "peak_distance": self.peak_distance,
            "normalization": self.normalization,
            "sort": self.sort,
            "on_error": self.on_error,
            "bootstrap_samples": self.bootstrap_samples,
            "bootstrap_seed": self.bootstrap_seed,
        }
        if self.lambda10_enabled:
            config["lambda10_window_nm"] = [self.lambda10_min_nm, self.lambda10_max_nm]
            config["lambda10_selection"] = self.lambda10_selection
        if self.group_column:
            config["group"] = self.group_column
        if not self.auto_prominence:
            config["prominence"] = self.prominence
        ranges = self.area_ranges
        if isinstance(ranges, pd.DataFrame):
            ranges = ranges.to_dict("records")
        if ranges:
            config["area_ranges"] = [[row["lower"], row["upper"]] for row in ranges]
        return config

    def _result(self):
        config = self._config()
        signature = hashlib.sha256(
            (
                table_fingerprint(self.input_table)
                + json.dumps(config, sort_keys=True, ensure_ascii=False, allow_nan=False)
            ).encode("utf-8")
        ).hexdigest()
        cached = self._ctx.get("batch_spectrum_analysis")
        if cached is None or cached[0] != signature:
            result = analyze_spectra(self.input_table, config)
            self._ctx["batch_spectrum_analysis"] = (signature, result)
        return self._ctx["batch_spectrum_analysis"]

    def build_features(self) -> DataFrame:
        return native_frame(self._result()[1].features)

    def build_curves(self) -> DataFrame:
        return native_frame(self._result()[1].table)

    def to_frontend_node(self, *args, **kwargs):
        result = super().to_frontend_node(*args, **kwargs)
        self.update_build_config(result["data"]["node"]["template"], None)
        return prepare_form(result)

    def build_groups(self) -> DataFrame:
        data = self._result()[1].data
        frame = DataFrame(deepcopy(data["group_summary"]))
        frame.attrs["units"] = deepcopy(data["group_summary_units"])
        return frame

    def build_report(self) -> Data:
        signature, result = self._result()
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": "materials.batch_spectra",
                "data": deepcopy(result.data),
                "warnings": list(result.warnings),
                "artifacts": [],
                "table_shape": list(result.table.shape),
                "provenance": {
                    "input_sha256": signature,
                    "parameters": self._config(),
                    "raw_preserved": True,
                },
            }
        )

    def build_summary(self) -> Message:
        result = self._result()[1]
        count = result.data["counts"]
        return Message(
            text=f"逐曲线光谱：{count['total']} 条，完成 {count['completed']}，"
            f"失败 {count['failed']}，跳过 {count['skipped']}；"
            f"状态 {result.data['execution_status']}；λ10 定义 {result.data['lambda10_definition']}。"
        )

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name in build_config:
            build_config[field_name]["value"] = field_value

        def selected(name):
            return build_config[name].get("value", getattr(self, name))

        conditions = {
            "baseline_value": selected("baseline_method") == "constant",
            "smooth_window": bool(selected("smooth")),
            "smooth_order": bool(selected("smooth")),
            "prominence": not bool(selected("auto_prominence")),
            **dict.fromkeys(
                ("lambda10_min_nm", "lambda10_max_nm", "lambda10_selection"),
                bool(selected("lambda10_enabled")),
            ),
        }
        for name, visible in conditions.items():
            build_config[name]["show"] = visible
        if field_name == "input_table" and isinstance(field_value, pd.DataFrame):
            for field in ("curve_column", "x_column", "y_column", "group_column"):
                build_config[field]["options"] = (
                    [""] if field == "group_column" else []
                ) + field_value.columns.tolist()
        return build_config

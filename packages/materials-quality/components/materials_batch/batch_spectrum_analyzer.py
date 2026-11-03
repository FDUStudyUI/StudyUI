"""Native forms for dark-field, Raman and other curve-level spectral descriptions."""

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
from materials_quality.science.spectrum_batch import (
    analyze_spectra,
    contract_spectral_output,
    validate_spectral_contract,
)
from materials_quality.science.table_contract import (
    contract_identity,
    read_contract,
)


class BatchSpectrumAnalyzer(Component):
    display_name = "材料批量·逐曲线光谱分析"
    description = "逐条曲线扣基线、平滑、寻峰和积分；输出候选特征和描述统计，曲线数不代表独立单位数。"
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
            info="必须声明；窗口波长候选仅适用于长度单位，不自动反演波数或能量。",
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
            display_name="旧版自动突出度（全谱极差的 5%）",
            value=True,
            real_time_refresh=True,
            info="兼容旧开关模式下生效；窗口外强峰可抬高阈值。关闭后使用显式突出度。",
        ),
        DropdownInput(
            name="prominence_mode",
            display_name="寻峰阈值策略",
            options=["兼容旧开关", "显式阈值", "旧版全谱相对阈值", "噪声参考"],
            value="兼容旧开关",
            real_time_refresh=True,
            info="显式阈值不随全谱振幅改变；噪声参考使用明确声明的背景区间，不自动猜测。",
        ),
        FloatInput(name="prominence", display_name="最小峰突出度（强度单位）", value=0.1),
        FloatInput(name="noise_window_low", display_name="噪声窗口下限（原始坐标单位）", value=0.0),
        FloatInput(name="noise_window_high", display_name="噪声窗口上限（原始坐标单位）", value=0.0),
        FloatInput(
            name="noise_multiplier",
            display_name="噪声 MAD 倍数",
            value=3.0,
            info="窗口至少五个实测点；正态缩放 MAD，背景漂移、强峰污染和相关性须另行验证。",
        ),
        IntInput(name="peak_distance", display_name="峰最小间距（测量点数）", value=1, advanced=True),
        BoolInput(
            name="peak_distance_x_enabled",
            display_name="启用坐标单位峰间距",
            value=False,
            real_time_refresh=True,
        ),
        FloatInput(
            name="peak_distance_x",
            display_name="峰最小间距（原始坐标单位）",
            value=1.0,
            info="对非均匀采样直接在坐标域抑制过近峰；同时保留测量点数间距约束。",
        ),
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
            display_name="提取窗口候选峰",
            value=False,
            real_time_refresh=True,
            info="仅报告窗口候选；原 λ10 字段保留为兼容别名，候选规则不能证明物理模式归属。",
        ),
        FloatInput(name="lambda10_min_nm", display_name="窗口候选下限（nm）", value=0.0),
        FloatInput(name="lambda10_max_nm", display_name="窗口候选上限（nm）", value=0.0),
        DropdownInput(
            name="lambda10_selection",
            display_name="窗口候选选择规则",
            options=["突出度最大候选", "最红端候选"],
            value="突出度最大候选",
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
        BoolInput(
            name="bootstrap_independence_confirmed",
            display_name="已验证每条曲线代表独立试验单位",
            value=False,
            advanced=True,
            info="仅在试验设计支持时确认；同一样品内多条曲线不会自动构成独立重复。n<3 默认只描述。",
        ),
    ]
    outputs = [
        Output(
            name="features",
            display_name="逐峰结构化特征",
            method="build_features",
            group_outputs=True,
            cache=False,
        ),
        Output(
            name="curves", display_name="完整处理曲线", method="build_curves", group_outputs=True, cache=False
        ),
        Output(
            name="groups",
            display_name="曲线分组描述统计",
            method="build_groups",
            group_outputs=True,
            cache=False,
        ),
        Output(
            name="report", display_name="结果与追溯", method="build_report", group_outputs=True, cache=False
        ),
        Output(
            name="summary", display_name="运行摘要", method="build_summary", group_outputs=True, cache=False
        ),
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
            "bootstrap_independence_confirmed": self.bootstrap_independence_confirmed,
        }
        if self.lambda10_enabled:
            config["lambda10_window_nm"] = [self.lambda10_min_nm, self.lambda10_max_nm]
            config["lambda10_selection"] = {
                "突出度最大候选": "highest_prominence",
                "最红端候选": "redmost",
            }.get(self.lambda10_selection, self.lambda10_selection)
        if self.group_column:
            config["group"] = self.group_column
        mode = self._threshold_mode()
        if mode != "legacy_auto":
            config["prominence_mode"] = mode
        if mode == "absolute" or (mode == "legacy_auto" and not self.auto_prominence):
            config["prominence"] = self.prominence
        if mode == "noise_reference":
            config["noise_window"] = [self.noise_window_low, self.noise_window_high]
            config["noise_multiplier"] = self.noise_multiplier
        if self.peak_distance_x_enabled:
            config["peak_distance_x"] = self.peak_distance_x
        ranges = self.area_ranges
        if isinstance(ranges, pd.DataFrame):
            ranges = ranges.to_dict("records")
        if ranges:
            config["area_ranges"] = [[row["lower"], row["upper"]] for row in ranges]
        return config

    def _threshold_mode(self, value=None):
        value = self.prominence_mode if value is None else value
        mode = {
            "兼容旧开关": "legacy_auto",
            "显式阈值": "absolute",
            "旧版全谱相对阈值": "legacy_relative",
            "噪声参考": "noise_reference",
        }.get(value, value)
        if mode not in {"legacy_auto", "absolute", "legacy_relative", "noise_reference"}:
            raise ValueError("请选择有效的寻峰阈值策略")
        return mode

    def _result(self):
        config = self._config()
        validate_spectral_contract(self.input_table, config)
        signature = hashlib.sha256(
            (
                table_fingerprint(self.input_table)
                + (contract_identity(self.input_table) or "")
                + json.dumps(config, sort_keys=True, ensure_ascii=False, allow_nan=False)
            ).encode("utf-8")
        ).hexdigest()
        cached = self._ctx.get("batch_spectrum_analysis")
        if cached is None or cached[0] != signature:
            result = analyze_spectra(self.input_table, config)
            self._ctx["batch_spectrum_analysis"] = (signature, result)
        return self._ctx["batch_spectrum_analysis"]

    def _contracted_output(self, frame, grain, roles, source_contract):
        return contract_spectral_output(
            self.input_table, frame, grain, roles, source_contract, self.curve_column
        )

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
        source_contract = read_contract(self.input_table)
        if source_contract is not None:
            frame = self._contracted_output(frame, "group_summary", {"group": "group"}, source_contract)
        return frame

    def build_report(self) -> Data:
        signature, result = self._result()
        contracts = {}
        if read_contract(self.input_table) is not None:
            contracts = {
                "table_contract": read_contract(result.table),
                "features_contract": read_contract(result.features),
                "groups_contract": read_contract(self.build_groups()),
            }
        return Data(
            data={
                **contracts,
                "schema_version": "science-result/1",
                "operation": "materials.batch_spectra",
                "data": deepcopy(result.data),
                "warnings": list(result.warnings),
                "artifacts": [],
                "table_shape": list(result.table.shape),
                "table_fingerprint": table_fingerprint(result.table) if len(result.table.columns) else None,
                "features_fingerprint": table_fingerprint(result.features)
                if len(result.features.columns)
                else None,
                "provenance": {
                    "input_sha256": signature,
                    "input_contract_sha256": contract_identity(self.input_table),
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
            f"状态 {result.data['execution_status']}；窗口候选不自动证明物理模式或试验独立性。"
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
            "auto_prominence": self._threshold_mode(selected("prominence_mode")) == "legacy_auto",
            "prominence": self._threshold_mode(selected("prominence_mode")) == "absolute"
            or (
                self._threshold_mode(selected("prominence_mode")) == "legacy_auto"
                and not bool(selected("auto_prominence"))
            ),
            **dict.fromkeys(
                ("noise_window_low", "noise_window_high", "noise_multiplier"),
                self._threshold_mode(selected("prominence_mode")) == "noise_reference",
            ),
            "peak_distance_x": bool(selected("peak_distance_x_enabled")),
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

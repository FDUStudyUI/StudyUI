"""Native form for per-cell battery cycling summaries."""

from copy import deepcopy

import pandas as pd
from lfx.custom import Component
from lfx.io import BoolInput, DataFrameInput, DropdownInput, FloatInput, IntInput, Output
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.native import native_frame, prepare_form
from materials_quality.common import json_value
from materials_quality.context import table_fingerprint
from materials_quality.science.battery import analyze_battery_cycles
from materials_quality.science.table_contract import contract_identity, read_contract

COLUMNS = {
    "cell_id": "cell",
    "cycle": "cycle",
    "discharge_capacity": "discharge_capacity",
    "charge_capacity": "charge_capacity",
    "time": "time",
    "current": "current",
    "phase": "phase",
}


class BatteryCycles(Component):
    display_name = "材料批量·电池循环与容量保持率"
    description = "从逐循环容量表或相位电流曲线得到逐电芯放电容量、保持率与可选库仑效率，保留异常循环。"
    name = "BatteryCycles"
    icon = "BatteryCharging"
    inputs = [
        DataFrameInput(name="input_table", display_name="电池循环数据表", required=True),
        DropdownInput(
            name="mode",
            display_name="输入数据类型",
            options=["summary", "raw"],
            value="summary",
            real_time_refresh=True,
            info="summary 为逐循环容量表，raw 为带相位的时间与电流采样。",
        ),
        *[
            DropdownInput(
                name=f"{COLUMNS[column]}_column",
                display_name=label,
                options=[column],
                value="" if column == "charge_capacity" else column,
                combobox=True,
            )
            for column, label in (
                ("cell_id", "电芯标识列"),
                ("cycle", "循环序号列（正整数）"),
                ("discharge_capacity", "放电容量列"),
                ("charge_capacity", "充电容量列"),
                ("time", "相位时间列"),
                ("current", "电流列"),
                ("phase", "相位列（charge / discharge / rest）"),
            )
        ],
        DropdownInput(name="capacity_unit", display_name="输入容量单位", options=["Ah", "mAh"], value=""),
        DropdownInput(
            name="time_unit", display_name="输入时间单位", options=["ms", "s", "min", "h"], value=""
        ),
        DropdownInput(name="current_unit", display_name="输入电流单位", options=["A", "mA"], value=""),
        DropdownInput(
            name="current_sign",
            display_name="电流符号约定",
            options=["discharge_negative", "discharge_positive"],
            value="",
        ),
        FloatInput(
            name="sign_tolerance_a",
            display_name="反号电流容差（A）",
            value=0,
            info="默认严格检查电流符号。容差内的实测电流仍按净值积分。",
            advanced=True,
        ),
        IntInput(name="baseline_cycle", display_name="基准循环（0 为每个电芯首个有效循环）", value=0),
        BoolInput(
            name="calculate_efficiency",
            display_name="已确认同一循环的充放电可比，计算库仑效率",
            value=False,
            real_time_refresh=True,
            info="需确认充放电窗口和协议可比。原始数据还要求同一循环内全部充电相位先于放电。",
        ),
    ]
    outputs = [
        Output(name=name, display_name=label, method=f"build_{name}", group_outputs=True, cache=False)
        for name, label in (
            ("features", "逐电芯循环结果"),
            ("report", "结果与追溯"),
            ("summary", "运行摘要"),
        )
    ]

    def _config(self):
        config = {
            "mode": self.mode,
            "cell_id": self.cell_column,
            "cycle": self.cycle_column,
            "baseline_cycle": self.baseline_cycle,
            "calculate_efficiency": self.calculate_efficiency,
        }
        if self.mode == "summary":
            config.update(discharge_capacity=self.discharge_capacity_column, capacity_unit=self.capacity_unit)
            if self.calculate_efficiency:
                config["charge_capacity"] = self.charge_capacity_column
        else:
            config.update(
                time=self.time_column,
                current=self.current_column,
                phase=self.phase_column,
                time_unit=self.time_unit,
                current_unit=self.current_unit,
                current_sign=self.current_sign,
                sign_tolerance_a=self.sign_tolerance_a,
            )
        return config

    def _result(self):
        fingerprint = table_fingerprint(self.input_table)
        contract = contract_identity(self.input_table)
        config = self._config()
        key = (fingerprint, contract, config)
        cached = self._ctx.get("battery_cycles")
        if cached is None or cached[0] != key:
            cached = (key, analyze_battery_cycles(self.input_table, config))
            self._ctx["battery_cycles"] = cached
        return cached

    def build_features(self) -> DataFrame:
        return native_frame(self._result()[1].features)

    def build_report(self) -> Data:
        (fingerprint, contract, config), result = self._result()
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": "materials.battery_cycles",
                "data": deepcopy(result.data),
                "warnings": list(result.warnings),
                "artifacts": [],
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
                    "input_sha256": fingerprint,
                    "input_contract_sha256": contract,
                    "parameters": config,
                    "raw_preserved": True,
                },
            }
        )

    def build_summary(self) -> Message:
        counts = self._result()[1].data["counts"]
        return Message(
            text=f"共 {counts['total']} 个电芯循环，有效 {counts['valid']}，"
            f"部分有效 {counts['partial']}，无效 {counts['invalid']}。"
        )

    def to_frontend_node(self, *args, **kwargs):
        result = super().to_frontend_node(*args, **kwargs)
        self.update_build_config(result["data"]["node"]["template"], None)
        return prepare_form(result)

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name in {"mode", "calculate_efficiency"}:
            build_config[field_name]["value"] = field_value
        raw = build_config["mode"].get("value", self.mode) == "raw"
        efficiency = build_config["calculate_efficiency"].get("value", self.calculate_efficiency)
        for field in (
            "time_column",
            "current_column",
            "phase_column",
            "time_unit",
            "current_unit",
            "current_sign",
            "sign_tolerance_a",
        ):
            build_config[field]["show"] = raw
        for field in ("discharge_capacity_column", "capacity_unit"):
            build_config[field]["show"] = not raw
        build_config["charge_capacity_column"]["show"] = not raw and bool(efficiency)
        if field_name == "input_table" and isinstance(field_value, pd.DataFrame):
            for prefix in COLUMNS.values():
                build_config[f"{prefix}_column"]["options"] = field_value.columns.tolist()
        return build_config

"""Native canvas component for optional PyBaMM-backed single-cell discharge simulation."""

from copy import deepcopy

from lfx.custom import Component
from lfx.io import DropdownInput, FloatInput, IntInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message

from materials_quality.common import json_value
from materials_quality.context import table_fingerprint
from materials_quality.science.canvas_adapter import pybamm_battery_sim
from materials_quality.science.table_contract import read_contract


class PybammBatterySim(Component):
    display_name = "材料仿真·单电芯放电曲线仿真 (PyBaMM)"
    description = (
        "基于 PyBaMM 的单电芯恒倍率放电仿真（SPM/SPMe/DFN），声明参数集溯源与温度/倍率适用边界"
        "（缺少 pybamm 时优雅降级）。"
    )
    name = "PybammBatterySim"
    icon = "BatteryCharging"
    ui_operation_key = "materials.pybamm_battery_sim"
    inputs = [
        DropdownInput(
            name="model_name",
            display_name="电化学模型",
            options=["SPM", "SPMe", "DFN"],
            value="SPM",
        ),
        StrInput(
            name="parameter_set",
            display_name="参数集",
            value="Chen2020",
            info="PyBaMM 内置或已标定参数集名称（如 Chen2020）。",
        ),
        FloatInput(name="c_rate", display_name="放电倍率 (C-rate)", value=1.0),
        FloatInput(name="ambient_temp_C", display_name="环境温度 (°C)", value=25.0),
        FloatInput(name="cutoff_voltage_V", display_name="截止电压 (V)", value=2.5),
        IntInput(
            name="t_points",
            display_name="输出采样点数",
            value=100,
            advanced=True,
        ),
    ]
    outputs = [
        Output(name=name, display_name=label, method=f"build_{name}", group_outputs=True, cache=False)
        for name, label in (
            ("table", "放电曲线表"),
            ("report", "结果与追溯"),
            ("summary", "运行摘要"),
        )
    ]

    def _config(self):
        return {
            "model_name": getattr(self, "model_name", "SPM") or "SPM",
            "parameter_set": getattr(self, "parameter_set", "Chen2020") or "Chen2020",
            "c_rate": float(getattr(self, "c_rate", 1.0)),
            "ambient_temp_C": float(getattr(self, "ambient_temp_C", 25.0)),
            "cutoff_voltage_V": float(getattr(self, "cutoff_voltage_V", 2.5)),
            "t_points": int(getattr(self, "t_points", 100)),
        }

    def _result(self):
        config = self._config()
        backend = getattr(self, "_backend", None)
        key = (config, id(backend))
        cached = self._ctx.get("pybamm_battery_sim")
        if cached is None or cached[0] != key:
            result = pybamm_battery_sim(config=config, backend=backend)
            cached = (key, result)
            self._ctx["pybamm_battery_sim"] = cached
        return config, cached[1]

    def build_table(self) -> DataFrame:
        _, result = self._result()
        frame = DataFrame(result.table.copy(deep=True))
        frame.attrs = deepcopy(result.table.attrs)
        return frame

    def build_report(self) -> Data:
        config, result = self._result()
        table = result.table
        status = result.data.get("execution_status", "completed")
        return Data(
            data=json_value(
                {
                    "schema_version": "science-result/1",
                    "operation": "materials.pybamm_battery_sim",
                    "execution_status": status,
                    "data": deepcopy(result.data),
                    "warnings": list(result.warnings),
                    "artifacts": [],
                    "table_available": table is not None,
                    "table_contract": read_contract(table),
                    "table_fingerprint": None if table is None else table_fingerprint(table),
                    "table_preview": None
                    if table is None
                    else {
                        "total_rows": len(table),
                        "included_rows": min(100, len(table)),
                        "truncated": len(table) > 100,
                        "columns": list(table.columns),
                        "records": table.head(100).to_dict("records"),
                        "units": table.attrs.get("units", {}),
                    },
                    "provenance": {
                        "operation": "materials.pybamm_battery_sim",
                        "parameters": config,
                    },
                }
            )
        )

    def build_summary(self) -> Message:
        _, result = self._result()
        if result.data.get("status") == "unavailable":
            warnings = result.data.get("boundary_warnings") or []
            warn_text = f"；边界提示：{len(warnings)} 条" if warnings else ""
            return Message(
                text=f"PyBaMM 单电芯放电仿真未执行（缺少可选依赖 {result.data.get('missing_dependency')}）。"
                f"安装提示：{result.data.get('install_hint')}{warn_text}"
            )
        summary = result.data.get("summary") or {}
        prov = result.data.get("provenance") or {}
        return Message(
            text=f"PyBaMM 单电芯放电仿真完成（{prov.get('model_name')} / {prov.get('parameter_set')} / "
            f"{prov.get('c_rate')}C）：放电容量 {summary.get('discharge_capacity_Ah')} Ah，"
            f"能量 {summary.get('discharge_energy_Wh')} Wh。"
        )

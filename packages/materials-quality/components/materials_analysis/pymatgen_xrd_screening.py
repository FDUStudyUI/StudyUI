"""Native canvas component for optional pymatgen-backed CIF XRD screening."""

from copy import deepcopy

import pandas as pd
from lfx.custom import Component
from lfx.io import (
    DataFrameInput,
    DropdownInput,
    FileInput,
    FloatInput,
    MultilineInput,
    Output,
)
from lfx.schema import Data, DataFrame, Message

from materials_quality.common import json_value
from materials_quality.context import table_fingerprint
from materials_quality.science.langflow_adapter import xrd_cif_screening
from materials_quality.science.table_contract import contract_identity, read_contract


class PymatgenXrdScreening(Component):
    display_name = "材料分析·CIF 理论 XRD 候选筛查 (pymatgen)"
    description = (
        "基于晶体结构 CIF 计算理论粉晶衍射峰位，并与可选实测 XRD 峰表进行候选比对"
        "（仅作候选筛查，不替代 Rietveld 精修；缺少 pymatgen 时优雅降级）。"
    )
    name = "PymatgenXrdScreening"
    icon = "Atom"
    ui_operation_key = "materials.xrd_cif_screening"
    inputs = [
        DataFrameInput(
            name="measured_peaks_table",
            display_name="实测 XRD 峰表（可选）",
            required=False,
            info="可选：包含 two_theta_deg/x 与 intensity_rel/y 列的实测峰表，用于候选峰比对。",
        ),
        MultilineInput(
            name="cif_text",
            display_name="晶体结构 CIF 文本",
            value="",
            required=False,
            info="粘贴标准 CIF 文本；也可通过 source_cif 上传文件。",
        ),
        FileInput(
            name="source_cif",
            display_name="上传 CIF 文件",
            required=False,
            file_types=["cif", "txt"],
            advanced=True,
        ),
        DropdownInput(
            name="wavelength",
            display_name="X 射线靶材波长",
            options=["CuKa", "CoKa", "MoKa", "CrKa", "FeKa", "AgKa"],
            value="CuKa",
        ),
        FloatInput(name="two_theta_min", display_name="2θ 起始角 (°)", value=10.0),
        FloatInput(name="two_theta_max", display_name="2θ 终止角 (°)", value=90.0),
        FloatInput(
            name="min_intensity",
            display_name="理论峰最小相对强度 (%)",
            value=1.0,
            advanced=True,
        ),
        FloatInput(
            name="tol_deg",
            display_name="峰位匹配容差 Δ2θ (°)",
            value=0.35,
            advanced=True,
        ),
        FloatInput(
            name="min_rel_intensity",
            display_name="比对理论峰最小相对强度 (%)",
            value=5.0,
            advanced=True,
        ),
    ]
    outputs = [
        Output(name=name, display_name=label, method=f"build_{name}", group_outputs=True, cache=False)
        for name, label in (
            ("table", "理论衍射峰表"),
            ("report", "结果与追溯"),
            ("summary", "运行摘要"),
        )
    ]

    def _config(self):
        return {
            "cif_text": getattr(self, "cif_text", "") or "",
            "source_cif": getattr(self, "source_cif", None) or "",
            "wavelength": getattr(self, "wavelength", "CuKa") or "CuKa",
            "two_theta_min": float(getattr(self, "two_theta_min", 10.0)),
            "two_theta_max": float(getattr(self, "two_theta_max", 90.0)),
            "min_intensity": float(getattr(self, "min_intensity", 1.0)),
            "tol_deg": float(getattr(self, "tol_deg", 0.35)),
            "min_rel_intensity": float(getattr(self, "min_rel_intensity", 5.0)),
        }

    def _result(self):
        measured = getattr(self, "measured_peaks_table", None)
        if not isinstance(measured, pd.DataFrame):
            measured = None
        fingerprint = table_fingerprint(measured) if measured is not None else None
        contract = contract_identity(measured) if measured is not None else None
        config = self._config()
        calculator = getattr(self, "_calculator", None)
        key = (fingerprint, contract, config, id(calculator))
        cached = self._ctx.get("pymatgen_xrd_screening")
        if cached is None or cached[0] != key:
            result = xrd_cif_screening(measured, config=config, calculator=calculator)
            cached = (key, result)
            self._ctx["pymatgen_xrd_screening"] = cached
        return fingerprint, contract, config, cached[1]

    def build_table(self) -> DataFrame:
        _, _, _, result = self._result()
        frame = DataFrame(result.table.copy(deep=True))
        frame.attrs = deepcopy(result.table.attrs)
        return frame

    def build_report(self) -> Data:
        fingerprint, contract, config, result = self._result()
        table = result.table
        status = result.data.get("execution_status", "completed")
        return Data(
            data=json_value(
                {
                    "schema_version": "science-result/1",
                    "operation": "materials.xrd_cif_screening",
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
                        "operation": "materials.xrd_cif_screening",
                        "input_sha256": fingerprint,
                        "input_contract_sha256": contract,
                        "parameters": {k: v for k, v in config.items() if k != "cif_text"},
                    },
                }
            )
        )

    def build_summary(self) -> Message:
        _, _, _, result = self._result()
        if result.data.get("status") == "unavailable":
            return Message(
                text=f"CIF 理论 XRD 候选筛查未执行（缺少可选依赖 {result.data.get('missing_dependency')}）。"
                f"安装提示：{result.data.get('install_hint')}"
            )
        peak_count = result.data.get("peak_count", 0)
        match = result.data.get("match_result")
        match_text = (
            f"；实测峰匹配 {match['matched_count']}/{match['measured_count']}（候选得分 {match['candidate_score']}）"
            if isinstance(match, dict)
            else ""
        )
        return Message(
            text=f"CIF 理论 XRD 候选筛查完成（波长 {result.data.get('wavelength')}）："
            f"共 {peak_count} 个理论衍射峰{match_text}。"
        )

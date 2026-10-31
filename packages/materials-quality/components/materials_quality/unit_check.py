from lfx.custom import Component
from lfx.io import BoolInput, MultilineInput, Output
from lfx.schema import Data, DataFrame

from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    column_list,
    findings_table,
    original_table,
    parse_json,
    report_data,
)
from materials_quality.units import check_units


class MaterialUnitCheck(Component):
    display_name = "材料数据·单位检查"
    description = "检查声明/单元格单位、量纲兼容及混合单位；不猜测单位或自动换算。"
    icon = "Ruler"
    name = "MaterialUnitCheck"
    inputs = check_inputs(
        [
            BoolInput(
                name="convert_values",
                display_name="生成单位换算表",
                value=False,
                info="显式启用后输出换算副本及记录；原始表格端口保持原值。",
            ),
            MultilineInput(
                name="source_units_json",
                display_name="原始单位 JSON",
                value="{}",
                info='例如 {"stress": "MPa", "temperature": "degC"}。',
            ),
            MultilineInput(
                name="expected_units_json", display_name="目标量纲单位 JSON", value='{"stress": "Pa"}'
            ),
            MultilineInput(
                name="columns_json",
                display_name="检查列 JSON",
                value="[]",
                advanced=True,
                info="[] 表示目标量纲单位中列出的字段。",
            ),
        ]
    )
    outputs = [
        *check_outputs(),
        Output(
            name="converted_table",
            display_name="换算表（需启用）",
            method="build_converted_table",
            group_outputs=True,
        ),
    ]

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_units)
        return report_data(
            self,
            check_units,
            source_units=parse_json(self.source_units_json, "source_units_json", dict),
            expected_units=parse_json(self.expected_units_json, "expected_units_json", dict),
            columns=column_list(self.columns_json),
            convert_values=self.convert_values,
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

    def build_converted_table(self) -> DataFrame:
        from materials_quality.science.preprocessing import convert_units

        report = self.build_report().data
        if not report["metrics"]["converted"]:
            reason = report["metrics"].get("conversion_blocked", "Enable conversion for this output.")
            self.status = f"Unit conversion unavailable: {reason}; see diagnostic report."
            return DataFrame(columns=list(self.input_table.columns))
        parameters = report["parameters"]
        selected = parameters.get("columns") or list(parameters["expected_units"])
        converted = convert_units(
            self.input_table,
            config={
                "source_units": parameters["source_units"],
                "target_units": {c: parameters["expected_units"][c] for c in selected},
                "missing_tokens": parameters.get("missing_tokens"),
            },
        )
        from copy import deepcopy

        table = DataFrame(converted.table)
        table.attrs = deepcopy(converted.table.attrs)
        return table

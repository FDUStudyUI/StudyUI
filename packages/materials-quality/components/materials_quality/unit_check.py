from lfx.custom import Component
from lfx.io import MultilineInput
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
    outputs = check_outputs()

    def build_report(self) -> Data:
        return report_data(
            self,
            check_units,
            source_units=parse_json(self.source_units_json, "source_units_json", dict),
            expected_units=parse_json(self.expected_units_json, "expected_units_json", dict),
            columns=column_list(self.columns_json),
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

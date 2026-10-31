from lfx.custom import Component
from lfx.io import BoolInput, MultilineInput
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_types
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    parse_json,
    report_data,
)


class MaterialTypeCheck(Component):
    display_name = "材料数据·类型格式检查"
    description = "按显式数值、整数、日期、布尔和分类规则检查，不写回类型转换。"
    icon = "Braces"
    name = "MaterialTypeCheck"
    inputs = check_inputs(
        [
            BoolInput(
                name="infer_types",
                display_name="推断字段类型",
                value=False,
                info="启用后从观察值生成类型建议，忽略本节点手工规则，不写回数据。",
            ),
            MultilineInput(
                name="expectations_json",
                display_name="字段类型规则 JSON",
                value='{"value": "number"}',
                info="支持 number/integer/string/boolean；日期需要 format，分类需要 allowed。",
            ),
        ]
    )
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_types)
        if self.infer_types:
            return report_data(self, check_types, infer=True)
        return report_data(
            self, check_types, expectations=parse_json(self.expectations_json, "expectations_json", dict)
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

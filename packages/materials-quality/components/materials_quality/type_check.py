from lfx.custom import Component
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_types
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    report_data,
)
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, quality_parameters


class MaterialTypeCheck(QualityFormMixin, Component):
    display_name = "材料数据·类型格式检查"
    description = "按显式数值、整数、日期、布尔和分类规则检查，不写回类型转换。"
    icon = "Braces"
    name = "MaterialTypeCheck"
    quality_check = "types"
    inputs = check_inputs([*form_inputs("types"), *legacy_inputs("types")])
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_types)
        return report_data(self, check_types, **quality_parameters(self, "types"))

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

from lfx.custom import Component
from lfx.schema import Data, DataFrame

from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    report_data,
)
from materials_quality.outliers import check_outliers
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, quality_parameters


class MaterialOutlierCheck(QualityFormMixin, Component):
    display_name = "材料数据·异常值标记"
    description = "按明确范围、IQR或MAD标记可疑值；统计离群不等于实验错误。"
    icon = "ChartScatter"
    name = "MaterialOutlierCheck"
    quality_check = "outliers"
    inputs = check_inputs([*form_inputs("outliers"), *legacy_inputs("outliers")])
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_outliers)
        return report_data(self, check_outliers, **quality_parameters(self, "outliers"))

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

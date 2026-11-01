from lfx.custom import Component
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_schema
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    report_data,
)
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, quality_parameters


class MaterialSchemaCheck(QualityFormMixin, Component):
    display_name = "材料数据·结构检查"
    description = "检查必需字段及显式别名，报告缺失和歧义，不重命名原表。"
    icon = "ListChecks"
    name = "MaterialSchemaCheck"
    quality_check = "schema"
    inputs = check_inputs([*form_inputs("schema"), *legacy_inputs("schema")])
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_schema)
        return report_data(self, check_schema, **quality_parameters(self, "schema"))

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

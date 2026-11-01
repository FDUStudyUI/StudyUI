from lfx.custom import Component
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_duplicates
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    report_data,
)
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, quality_parameters


class MaterialDuplicateCheck(QualityFormMixin, Component):
    display_name = "材料数据·重复记录检查"
    description = "检查整行或指定键重复，标记所有成员；不删除可能有效的重复实验。"
    icon = "CopyCheck"
    name = "MaterialDuplicateCheck"
    quality_check = "duplicates"
    inputs = check_inputs([*form_inputs("duplicates"), *legacy_inputs("duplicates")])
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_duplicates)
        return report_data(self, check_duplicates, **quality_parameters(self, "duplicates"))

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

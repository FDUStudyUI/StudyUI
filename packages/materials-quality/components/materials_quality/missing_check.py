from lfx.custom import Component
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_missing
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    report_data,
)
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, quality_parameters


class MaterialMissingCheck(QualityFormMixin, Component):
    display_name = "材料数据·缺失检查"
    description = "统计缺失数量、比例、位置、分组及模式；不填补数据。"
    icon = "ScanSearch"
    name = "MaterialMissingCheck"
    quality_check = "missing"
    inputs = check_inputs([*form_inputs("missing"), *legacy_inputs("missing")])
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_missing)
        return report_data(self, check_missing, **quality_parameters(self, "missing"))

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

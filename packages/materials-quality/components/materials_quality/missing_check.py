from lfx.custom import Component
from lfx.io import MultilineInput
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_missing
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    column_list,
    findings_table,
    original_table,
    parse_json,
    report_data,
)


class MaterialMissingCheck(Component):
    display_name = "材料数据·缺失检查"
    description = "统计缺失数量、比例、位置、分组及模式；不填补数据。"
    icon = "ScanSearch"
    name = "MaterialMissingCheck"
    inputs = check_inputs(
        [
            MultilineInput(
                name="columns_json", display_name="检查列 JSON", value="[]", info="[] 表示所有列。"
            ),
            MultilineInput(
                name="missing_tokens_json",
                display_name="缺失标记 JSON",
                value='[""]',
                info='按数据说明填写，如 ["", "NA", "-200"]；不会默认把 NA 当缺失。',
            ),
            MultilineInput(name="group_by_json", display_name="分组列 JSON", value="[]", advanced=True),
        ]
    )
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_missing)
        return report_data(
            self,
            check_missing,
            columns=column_list(self.columns_json),
            missing_tokens=parse_json(self.missing_tokens_json, "missing_tokens_json", list),
            group_by=column_list(self.group_by_json, "group_by_json"),
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

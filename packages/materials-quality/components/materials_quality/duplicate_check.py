from lfx.custom import Component
from lfx.io import BoolInput, FloatInput, MultilineInput
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_duplicates
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    column_list,
    findings_table,
    original_table,
    parse_json,
    report_data,
)


class MaterialDuplicateCheck(Component):
    display_name = "材料数据·重复记录检查"
    description = "检查整行或指定键重复，标记所有成员；不删除可能有效的重复实验。"
    icon = "CopyCheck"
    name = "MaterialDuplicateCheck"
    inputs = check_inputs(
        [
            BoolInput(name="match_similar", display_name="匹配相似记录", value=False),
            FloatInput(name="similarity_threshold", display_name="相似度阈值", value=0.9, advanced=True),
            MultilineInput(
                name="numeric_tolerances_json", display_name="数值容差 JSON", value="{}", advanced=True
            ),
            MultilineInput(
                name="columns_json",
                display_name="重复判定键 JSON",
                value="[]",
                info='[] 为整行；如 ["sample_id", "measurement_id"]。',
            ),
        ]
    )
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_duplicates)
        return report_data(
            self,
            check_duplicates,
            columns=column_list(self.columns_json),
            similarity_threshold=self.similarity_threshold if self.match_similar else None,
            numeric_tolerances=parse_json(self.numeric_tolerances_json, "numeric_tolerances_json", dict),
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

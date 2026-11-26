"""Native shared-rule editor for independent batch checks."""

from lfx.custom import Component
from lfx.io import BoolInput, DataInput, IntInput, Output
from lfx.schema import Data, Message

from materials_quality.batch.quality import quality_batch
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, shared_rules


class MaterialBatchQuality(QualityFormMixin, Component):
    display_name = "批量·共享质量检查"
    description = "对每份完整样品执行所选规则，保留原始值，标记需要复核或跳过的样品。"
    name = "MaterialBatchQuality"
    icon = "ShieldCheck"
    quality_check = "context"
    inputs = [
        DataInput(name="input_data", display_name="批次", required=True),
        *form_inputs("context"),
        *legacy_inputs("context"),
        BoolInput(name="skip_on_issues", display_name="发现问题时跳过后续分析", value=False),
        IntInput(name="finding_limit", display_name="每份样品最多显示问题数", value=500, advanced=True),
    ]
    outputs = [
        Output(name="batch", display_name="检查后批次", method="build_batch", group_outputs=True),
        Output(name="summary", display_name="摘要", method="build_summary", group_outputs=True),
    ]

    def build_batch(self) -> Data:
        rules = shared_rules(self)
        output = quality_batch(
            self.input_data.data, rules, finding_limit=self.finding_limit, skip_on_issues=self.skip_on_issues
        )
        self.status = (
            f"{output['counts']['total']} 份样品；{output['counts'].get('needs_review', 0)} 份需复核"
        )
        return Data(data=output)

    def build_summary(self) -> Message:
        self.build_batch()
        return Message(text=str(self.status))

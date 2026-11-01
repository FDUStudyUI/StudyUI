from lfx.custom import Component
from lfx.io import DataFrameInput, Output, StrInput
from lfx.schema import Data, DataFrame

from materials_quality.context import make_context
from materials_quality.quality_ui import QualityFormMixin, form_inputs, legacy_inputs, shared_rules


class MaterialQualityContext(QualityFormMixin, Component):
    display_name = "材料数据·共享规则与追溯"
    description = "绑定原始表格指纹、来源声明和共享规则；各检查连接同一规则端口。"
    name = "MaterialQualityContext"
    icon = "Fingerprint"
    quality_check = "context"
    inputs = [
        DataFrameInput(name="input_table", display_name="原始表格", required=True),
        *form_inputs("context"),
        *legacy_inputs("context"),
        StrInput(name="rule_set_id", display_name="规则集名称", value="custom"),
        StrInput(name="rule_set_version", display_name="规则集版本", value="1"),
        StrInput(name="dataset_id", display_name="数据集编号", value="", advanced=True),
        StrInput(name="source_name", display_name="来源文件名", value="", advanced=True),
        StrInput(
            name="source_sha256",
            display_name="声明的原文件 SHA-256",
            value="",
            advanced=True,
            info="可选来源声明；节点绑定内存表格指纹，不验证原文件真实性。",
        ),
    ]
    outputs = [
        Output(name="context", display_name="共享规则与来源", method="build_context", group_outputs=True),
        Output(name="table_out", display_name="原始表格", method="pass_table", group_outputs=True),
    ]

    def build_context(self) -> Data:
        source = {
            key: getattr(self, key)
            for key in ("dataset_id", "source_name", "source_sha256")
            if getattr(self, key)
        }
        context = make_context(
            self.input_table,
            shared_rules(self),
            source,
            self.rule_set_id,
            self.rule_set_version,
        )
        fingerprint = context["dataset"]["fingerprint"][:12]
        self.status = f"规则 {self.rule_set_id}@{self.rule_set_version}；指纹 {fingerprint}"
        return Data(data=context)

    def pass_table(self) -> DataFrame:
        return DataFrame(self.input_table.copy(deep=True))

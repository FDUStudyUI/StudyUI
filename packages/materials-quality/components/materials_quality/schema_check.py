from lfx.custom import Component
from lfx.io import MultilineInput
from lfx.schema import Data, DataFrame

from materials_quality.checks import check_schema
from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    parse_json,
    report_data,
)


class MaterialSchemaCheck(Component):
    display_name = "材料数据·结构检查"
    description = "检查必需字段及显式别名，报告缺失和歧义，不重命名原表。"
    icon = "ListChecks"
    name = "MaterialSchemaCheck"
    inputs = check_inputs(
        [
            MultilineInput(
                name="schema_template_json",
                display_name="结构模板 JSON Schema",
                value="{}",
                advanced=True,
                info="可选：逐行校验字段类型、范围、必需属性和额外字段。",
            ),
            MultilineInput(name="required_columns_json", display_name="必需字段 JSON", value='["sample_id"]'),
            MultilineInput(
                name="aliases_json",
                display_name="字段别名 JSON",
                value="{}",
                info='例如 {"sample_id": ["样品编号"]}；不自动猜测同义字段。',
            ),
        ]
    )
    outputs = check_outputs()

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_schema)
        return report_data(
            self,
            check_schema,
            required_columns=parse_json(self.required_columns_json, "required_columns_json", list),
            aliases=parse_json(self.aliases_json, "aliases_json", dict),
            schema_template=parse_json(self.schema_template_json, "schema_template_json", dict) or None,
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

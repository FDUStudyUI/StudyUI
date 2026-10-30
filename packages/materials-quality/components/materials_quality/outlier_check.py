from lfx.custom import Component
from lfx.io import DropdownInput, FloatInput, MultilineInput
from lfx.schema import Data, DataFrame

from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    column_list,
    findings_table,
    original_table,
    parse_json,
    report_data,
)
from materials_quality.outliers import check_outliers


class MaterialOutlierCheck(Component):
    display_name = "材料数据·异常值标记"
    description = "按明确范围、IQR或MAD标记可疑值；统计离群不等于实验错误。"
    icon = "ChartScatter"
    name = "MaterialOutlierCheck"
    inputs = check_inputs(
        [
            MultilineInput(name="columns_json", display_name="数值列 JSON", value='["value"]'),
            DropdownInput(
                name="detection_method", display_name="检查方法", options=["range", "iqr", "mad"], value="iqr"
            ),
            MultilineInput(
                name="bounds_json",
                display_name="明确范围 JSON",
                value="{}",
                info='range 方法必填，例如 {"temperature": {"min": 0, "max": 100}}。',
            ),
            FloatInput(name="iqr_multiplier", display_name="IQR倍数", value=1.5, advanced=True),
            FloatInput(name="mad_threshold", display_name="MAD稳健Z阈值", value=3.5, advanced=True),
            MultilineInput(name="group_by_json", display_name="分组列 JSON", value="[]", advanced=True),
        ]
    )
    outputs = check_outputs()

    def build_report(self) -> Data:
        columns = column_list(self.columns_json)
        if columns is None:
            raise ValueError("columns_json: explicitly select numeric columns")
        return report_data(
            self,
            check_outliers,
            columns=columns,
            method=self.detection_method,
            bounds=parse_json(self.bounds_json, "bounds_json", dict),
            multiplier=self.iqr_multiplier,
            mad_threshold=self.mad_threshold,
            group_by=column_list(self.group_by_json, "group_by_json"),
        )

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

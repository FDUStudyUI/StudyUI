import json

from lfx.custom import Component
from lfx.io import MultilineInput, Output
from lfx.schema import DataFrame


class MaterialDemoTable(Component):
    display_name = "演示数据（人工样例）"
    description = "仅用于演示与测试；JSON记录为人工构造，不是真实实验数据。"
    name = "MaterialDemoTable"
    icon = "FlaskConical"
    inputs = [MultilineInput(name="records_json", display_name="人工样例 JSON", value="[]")]
    outputs = [Output(name="table", display_name="表格", method="build_table")]

    def build_table(self) -> DataFrame:
        def reject_constant(value):
            raise ValueError(f"Invalid JSON constant {value}")

        records = json.loads(self.records_json, parse_constant=reject_constant)
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise ValueError("records_json must be a list of record objects")
        self.status = f"人工演示数据：{len(records)}行；非真实实验数据"
        return DataFrame(records)

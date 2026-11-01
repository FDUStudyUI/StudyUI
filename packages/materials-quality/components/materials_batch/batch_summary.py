"""Collect results from a batch without losing failures or traceability."""

from lfx.custom import Component
from lfx.io import DataInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.summary import summarize_batch
from materials_quality.science.langflow_adapter import _digest


class MaterialBatchSummary(Component):
    display_name = "批量·结果汇总"
    description = "每份样品一行，保留质量发现、分析指标、失败原因和完整追溯；生成独立 HTML 报告。"
    name = "MaterialBatchSummary"
    icon = "Files"
    inputs = [
        DataInput(name="input_data", display_name="批次", required=True),
        StrInput(name="output_dir", display_name="报告输出目录", value="", advanced=True),
    ]
    outputs = [
        Output(name="table", display_name="样品汇总表", method="build_table", group_outputs=True),
        Output(name="report", display_name="结果与追溯", method="build_report", group_outputs=True),
        Output(name="artifacts", display_name="报告文件", method="build_artifacts", group_outputs=True),
        Output(name="summary", display_name="摘要", method="build_summary", group_outputs=True),
    ]

    def _result(self):
        from pathlib import Path

        signature = _digest([self.input_data.data, self.output_dir])
        cached = self._ctx.get("batch_summary")
        if cached and cached[0] == signature and all(Path(p).is_file() for p in cached[1].artifacts):
            return cached[1]
        result = summarize_batch(self.input_data.data, {"output_dir": self.output_dir})
        self._ctx["batch_summary"] = (signature, result)
        self.status = f"{len(result.table)} 份样品；失败 {result.data['counts']['failed']} 份"
        return result

    def build_table(self) -> DataFrame:
        return DataFrame(self._result().table.copy(deep=True))

    def build_report(self) -> Data:
        return Data(data=self._result().data)

    def build_artifacts(self) -> DataFrame:
        return DataFrame([{"path": path} for path in self._result().artifacts])

    def build_summary(self) -> Message:
        self._result()
        return Message(text=str(self.status))

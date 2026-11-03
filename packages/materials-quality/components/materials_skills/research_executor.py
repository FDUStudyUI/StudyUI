"""Run an input-bound research plan with scientific outputs and provenance."""

from lfx.custom import Component
from lfx.io import DataFrameInput, DataInput, Output, StrInput
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.native import native_frame
from materials_quality.skills.execution import execute_plan
from materials_quality.skills.planning import input_identity, validate_plan
from materials_quality.skills.registry import digest


class ResearchSkillExecutor(Component):
    display_name = "科研技能·分析执行"
    description = "执行与输入绑定的计划，输出表格、特征、曲线、分组、图件和追溯；过期或未确认计划停止执行。"
    name = "ResearchSkillExecutor"
    icon = "FlaskConical"
    inputs = [
        DataFrameInput(name="input_table", display_name="同一输入数据表", required=True),
        DataInput(name="plan", display_name="分析计划", required=True),
        StrInput(
            name="output_directory", display_name="输出目录（服务器路径，可选）", value="", advanced=True
        ),
    ]
    outputs = [
        Output(name=n, display_name=d, method=m, group_outputs=True, cache=False)
        for n, d, m in [
            ("table", "逐样品/试验单位结果", "build_table"),
            ("features", "结构化特征/两两比较", "build_features"),
            ("curves", "处理后完整曲线", "build_curves"),
            ("groups", "分组描述统计", "build_groups"),
            ("report", "分析报告与追溯", "build_report"),
            ("artifacts", "图件与导出文件", "build_artifacts"),
            ("summary", "结果摘要", "build_summary"),
        ]
    ]

    def _result(self):
        plan = self.plan.data if isinstance(self.plan, Data) else self.plan
        validate_plan(self.input_table, plan)
        signature = digest([input_identity(self.input_table), plan, self.output_directory])
        cached = self._ctx.get("research_execution")
        if cached is None or cached[0] != signature:
            cached = (
                signature,
                execute_plan(self.input_table, plan, output_dir=self.output_directory or None),
            )
            self._ctx["research_execution"] = cached
        return cached[1]

    def build_table(self) -> DataFrame:
        return native_frame(self._result().table)

    def build_features(self) -> DataFrame:
        return native_frame(self._result().features)

    def build_curves(self) -> DataFrame:
        return native_frame(self._result().curves)

    def build_groups(self) -> DataFrame:
        return native_frame(self._result().groups)

    def build_report(self) -> Data:
        from copy import deepcopy

        r = self._result()
        return Data(data={**deepcopy(r.report), "artifacts": list(r.artifacts)})

    def build_artifacts(self) -> list[Data]:
        from pathlib import Path

        return [Data(data={"file_path": p, "file_name": Path(p).name}) for p in self._result().artifacts]

    def build_summary(self) -> Message:
        return Message(text=self._result().summary)

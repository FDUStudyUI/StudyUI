from lfx.custom import Component
from lfx.io import DataInput, IntInput, Output
from lfx.schema import Data, DataFrame, Message

from materials_quality.aggregate import aggregate_reports
from materials_quality.langflow_support import findings_table


class MaterialQualitySummary(Component):
    display_name = "材料数据·检查报告汇总"
    description = "汇总已完成的检查报告；无检查或有问题时不会给出全部通过。"
    icon = "ClipboardList"
    name = "MaterialQualitySummary"
    inputs = [
        DataInput(
            name="reports",
            display_name="检查报告",
            is_list=True,
            value=[],
            info="连接各检查节点的报告端口；只汇总已接入且成功完成的检查。",
        ),
        IntInput(name="finding_limit", display_name="汇总问题明细上限", value=500, advanced=True),
    ]
    outputs = [
        Output(name="report", display_name="汇总报告", method="build_report", group_outputs=True),
        Output(name="findings", display_name="汇总问题明细", method="build_findings", group_outputs=True),
        Output(name="summary", display_name="摘要", method="build_summary", group_outputs=True),
    ]

    def build_report(self) -> Data:
        reports = self.reports or []
        reports = reports if isinstance(reports, list) else [reports]
        if any(not isinstance(r, Data) for r in reports):
            raise ValueError("reports must contain native Langflow Data objects")
        result = aggregate_reports([r.data for r in reports], finding_limit=self.finding_limit)
        self.status = f"已汇总 {len(reports)} 项检查；问题数 {result['total_findings']}"
        return Data(data=result)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

    def build_summary(self) -> Message:
        report = self.build_report().data
        metrics = report["metrics"]
        verdict = "接入的检查均未发现所检查的问题" if report["passed"] else "需要复核（或未接入检查）"
        return Message(
            text=(
                f"数据质量检查：{verdict}。已完成 {metrics['completed_checks']} 项，"
                f"其中 {metrics['failed_checks']} 项有问题，共 {report['total_findings']} 条发现。"
                "原始数据未修改；未接入的检查不在本报告覆盖范围内。"
            )
        )

"""Evidence cards use column selection and plain-language text fields."""

from .method_cards import load_cards
from .ui_types import field

SPECS = {
    "lit.result_evidence": [
        field("title", "报告标题", default="结果与文献证据"),
        field("columns", "结果列（留空选择数值列）", "list", default=[]),
        field("identity_column", "样品或曲线编号列", default=""),
        field("max_rows", "最多展示行数", "int", default=20, info="1 至 200；超出的行明确标注。"),
        field(
            "method_card",
            "关联方法卡",
            "choice",
            default="",
            choices=["", *[c["id"] for c in load_cards()]],
            info="可选；填写文献解释时须选择已登记方法来源。",
        ),
        field(
            "explanation",
            "文献解释（待核对适用性）",
            default="",
            info="关联文献不等于已经证明该解释，需人工核对样品和实验条件。",
        ),
        field("hypothesis", "待验证推测", default="", info="与直接观察分开显示。"),
    ]
}
CONTRACTS = {
    "lit.result_evidence": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "Quote",
    }
}

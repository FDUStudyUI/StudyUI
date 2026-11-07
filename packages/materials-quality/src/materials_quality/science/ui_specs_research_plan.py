from .ui_types import field

SPECS = {
    "materials.analysis_plan": [
        field(
            "task",
            "分析任务",
            "choice",
            default="group_summary",
            choices=["group_summary", "spectra"],
            info="分组原始/标准化对照，或逐曲线主峰与分组描述。",
        ),
        field(
            "columns",
            "分析数值列",
            "list",
            default=["value"],
            when={"task": ["group_summary"]},
            info="选择有限数值列，分别计算原始与标准化后的描述统计。",
        ),
        field(
            "group_by",
            "分组列",
            "list",
            default=["group"],
            when={"task": ["group_summary"]},
            info="按所选列组合分组；组别不能缺失。",
        ),
        field(
            "normalization",
            "标准化方法",
            "choice",
            default="zscore",
            choices=["zscore", "minmax", "robust"],
            when={"task": ["group_summary"]},
            info="仅作描述性对照，不用于独立测试集建模。",
        ),
        field(
            "normalize_by",
            "分别标准化的分组列",
            "list",
            default=[],
            when={"task": ["group_summary"]},
            info="留空对全部行拟合；此描述性流程不用于训练/测试预测建模。",
        ),
        *[
            field(
                name,
                label,
                default=name,
                when={"task": ["spectra"]},
                info="选择上游表的真实列名；每条曲线必须属于同一条件组。",
            )
            for name, label in [
                ("curve_id", "曲线编号列"),
                ("x", "横坐标列"),
                ("y", "信号列"),
                ("group", "条件组列"),
            ]
        ],
        field(
            "x_unit",
            "坐标单位",
            required=True,
            when={"task": ["spectra"]},
            info="填写仪器已确认的物理坐标单位；不自动猜测。",
        ),
        field(
            "y_unit",
            "信号单位",
            required=True,
            when={"task": ["spectra"]},
            info="填写已确认的信号单位，例如 counts；未知时请先核对。",
        ),
        field(
            "baseline",
            "基线方法",
            "choice",
            default="none",
            choices=["none", "linear", "asls"],
            when={"task": ["spectra"]},
            info="基线只影响派生分析，原始曲线保留；AsLS 参数采用明确记录的默认值。",
        ),
        field(
            "prominence",
            "主峰突出度阈值",
            "float",
            default=0.1,
            when={"task": ["spectra"]},
            info="使用输入信号单位；失败时不会自动降低阈值。",
        ),
    ]
}
CONTRACTS = {
    "materials.analysis_plan": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "Workflow",
    }
}

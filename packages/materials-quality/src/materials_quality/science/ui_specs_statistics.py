"""Native controls and actual output capabilities for the eight statistics nodes."""

from .ui_types import field

_REGRESSORS = ("linear", "polynomial", "ridge", "lasso")
_PREDICTORS = ("random_forest", "gradient_boosting", "svr")


def _groups(*, when=None, include_column=True):
    controls = [
        field(
            "group",
            "分组列",
            default="group",
            when=when,
            info="输入分组列名，可填写自定义列名；组标签不能缺失。",
        ),
        field(
            "groups",
            "参与比较的组",
            "list",
            when=when,
            info="留空使用全部组；填写组标签并保留比较顺序，不能重复。",
        ),
        field(
            "subject",
            "独立实验单位 ID 列",
            when=when,
            info="可选。独立检验中 ID 必须唯一且非缺失；技术重复需先聚合。",
        ),
    ]
    if include_column:
        controls.insert(
            1,
            field(
                "column",
                "测量值列",
                default="value",
                when=when,
                info="输入有限数值列名；每组至少两个观测值。",
            ),
        )
    return controls


def _output():
    return [
        field("output_dir", "输出目录", info="留空自动创建临时目录；填写本机可写目录。"),
        field(
            "overwrite",
            "覆盖同名文件",
            "bool",
            default=False,
            info="关闭时为已有文件生成唯一文件名，保留旧结果。",
        ),
    ]


def _dataset(*, required=False):
    return [
        field(
            "features",
            "特征列（按顺序）",
            "list",
            default=["x"],
            required=required,
            info="填写互不重复的有限数值列名，顺序与模型一致；不能包含目标列。",
        ),
        field(
            "target",
            "目标列",
            default="y",
            required=required,
            info="训练时必填有限数值列；读取已保存模型时可留空使用清单中的目标列。",
        ),
        field("id_column", "样本 ID 列", info="可选。必须唯一且非缺失，用于记录训练和测试样本。"),
        field("group_column", "独立样本分组列", info="同一试样的重复测量使用相同标签，避免泄漏；至少两组。"),
        field("seed", "随机种子", "int", default=42, info="非负整数；固定数据拆分及随机模型。"),
    ]


def _model_options(controller, *, choices):
    def when(*methods):
        return {controller: list(methods)}

    options = []
    if "polynomial" in choices:
        options.append(
            field(
                "degree",
                "多项式阶数",
                "int",
                default=2,
                when=when("polynomial"),
                info="1 至 8 的整数；仅在训练数据上拟合。",
            )
        )
    regularized = [m for m in ("ridge", "lasso") if m in choices]
    if regularized:
        options.append(
            field(
                "alpha",
                "正则化强度",
                "float",
                default=1.0,
                when=when(*regularized),
                info="有限非负数；此处为模型惩罚系数。",
            )
        )
    if "lasso" in choices:
        options.append(
            field(
                "max_iter",
                "Lasso 最大迭代数",
                "int",
                default=10000,
                when=when("lasso"),
                info="正整数；未收敛时可增加迭代数。",
            )
        )
    trees = [m for m in _PREDICTORS[:2] if m in choices]
    if trees:
        options.extend(
            [
                field(
                    "n_estimators",
                    "树的数量",
                    "int",
                    default=100,
                    when=when(*trees),
                    info="正整数；模型固定单线程，数量增加会提高运行成本。",
                ),
                field(
                    "max_depth",
                    "树最大深度",
                    "int",
                    when=when(*trees),
                    info="正整数；留空时随机森林不限制深度，梯度提升使用深度 3。",
                ),
            ]
        )
    if "svr" in choices:
        options.extend(
            [
                field(
                    "C",
                    "SVR 惩罚参数 C",
                    "float",
                    default=10.0,
                    when=when("svr"),
                    info="有限正数；输入特征由训练集拟合的标准化器变换。",
                ),
                field(
                    "epsilon",
                    "SVR 不敏感区间",
                    "float",
                    default=0.1,
                    when=when("svr"),
                    info="有限非负数，使用目标值的单位。",
                ),
                field(
                    "kernel",
                    "SVR 核函数",
                    "choice",
                    default="rbf",
                    choices=("rbf", "linear", "poly", "sigmoid"),
                    when=when("svr"),
                    info="选择 sklearn SVR 支持的普通核函数。",
                ),
            ]
        )
    return options


def _saved_model():
    return [
        field(
            "model_path", "已有模型路径", info="可选。本机 .skops 文件或模型清单 .json；优先读取已有模型。"
        ),
        field("manifest_path", "模型清单路径", info="可选。生成的 model-manifest.json；上游 Data 也可提供。"),
    ]


def _validation_fields(*, cv=False):
    choices = ("random", "chronological_split", "blocked_cv") if cv else ("random", "chronological_split")
    return [
        field(
            "validation_split",
            "验证拆分策略",
            "choice",
            default="random",
            choices=choices,
            info=(
                "random 保留原随机/按试样分组拆分；chronological_split 按时间留出后段；"
                "blocked_cv 需选择 cv，逐块只用过去训练。"
            ),
        ),
        field(
            "time_column",
            "时间或测量顺序列",
            required=True,
            when={"validation_split": [value for value in choices if value != "random"]},
            info="选择有限数值或有效日期时间列；按时间稳定排序，同一时间不跨训练/测试。试样分组跨边界时明确报错。",
        ),
    ]


def _diagnostic_fields(*, residual=True):
    controls = (
        [
            field(
                "residual_diagnostics",
                "输出残差诊断",
                "bool",
                default=False,
                info="报告留出残差的均值、离散和顺序相关摘要；不能证明模型假设成立。",
            )
        ]
        if residual
        else []
    )
    return [
        *controls,
        field(
            "linear_trend_ci",
            "单变量线性均值置信带",
            "bool",
            default=False,
            info=(
                "仅非正则化单变量 OLS；限训练特征范围内的均值区间，非个体预测或未来外推区间。"
                "检出异方差时不输出经典置信带。"
            ),
        ),
        field(
            "confidence_level",
            "均值置信水平",
            "float",
            default=0.95,
            when={"linear_trend_ci": [True]},
            info="0 与 1 之间；有限样本 t 区间仍需线性、独立、正态误差和方差齐性假设。",
        ),
    ]


def _for_task(controller, task, controls):
    """Keep method conditions and task visibility conjunctive."""
    return [{**control, "when": {**control.get("when", {}), controller: [task]}} for control in controls]


SPECS = {
    "stats.grouped": [
        field("group", "分组列", default="group", required=True, info="输入自定义分组列名；标签不能缺失。"),
        field("group_by", "多级分组列", "list", info="可选，优先于单个分组列；例如条件、样品、曲线。"),
        field(
            "normalize_by_group",
            "各组先除以自身均值",
            "bool",
            default=False,
            info="分别对每组每个数值列归一化；零均值时报错。",
        ),
        field(
            "output_format",
            "输出布局",
            "choice",
            default="long",
            choices=("long", "wide"),
            info="long 每个变量一行；wide 将变量与统计量展开为列。",
        ),
        field(
            "columns",
            "统计数值列",
            "list",
            default=["value"],
            required=True,
            info="填写有限数值列名；每组计算数量、均值、样本标准差和分位数。",
        ),
        field("units", "列单位", "dict", default={}, info="列名到单位的映射；单观测组的样本标准差未定义。"),
    ],
    "stats.distribution": [
        field(
            "column",
            "数值列",
            default="value",
            required=True,
            info="至少三个有限且非常数的观测值；输出直方图、Q-Q 图和 Shapiro 检验信息，无表输出。",
        ),
        field(
            "bins",
            "直方图分箱",
            default="auto",
            converter="histogram_bins",
            info="填写正整数，或 auto、fd、doane、scott、stone、rice、sturges、sqrt。",
        ),
        field(
            "profile",
            "图件用途",
            "choice",
            default="preview",
            choices=("preview", "paper"),
            info="preview 用于预览；paper 默认导出 PNG、SVG、PDF、TIFF。",
        ),
        field("formats", "导出格式", "list", info="可选 png、svg、pdf、tiff；留空采用所选用途的默认格式。"),
        field("dpi", "分辨率 DPI", "int", info="72 至 1200；留空按用途选择，TIFF 至少 600 DPI。"),
        field(
            "data_kind",
            "数据来源类型",
            "choice",
            default="unspecified",
            choices=("unspecified", "synthetic", "measured", "simulated", "derived"),
            info="准确标识实测、模拟、合成或派生数据，图件将记录来源。",
        ),
        field("units", "列单位", "dict", default={}, info="数值列名到单位的映射，用于坐标标签。"),
        *_output(),
    ],
    "stats.correlation": [
        field(
            "columns",
            "相关分析列",
            "list",
            default=["x", "y"],
            required=True,
            info="至少两列有限且非常数的数值；逐对输出相关系数与未校正 p 值。",
        ),
        field(
            "method",
            "相关方法",
            "choice",
            default="pearson",
            choices=("pearson", "spearman", "kendall"),
            info="Pearson 为线性相关；Spearman 与 Kendall 为秩相关。",
        ),
        field(
            "alpha",
            "置信区间显著性水平",
            "float",
            default=0.05,
            when={"method": ["pearson"]},
            info="0 与 1 之间；Pearson 区间置信度为 1-alpha。",
        ),
    ],
    "stats.significance": [
        field(
            "method",
            "检验方法",
            "choice",
            default="welch",
            choices=("welch", "independent_t", "paired_t", "mannwhitney", "anova", "kruskal"),
            info="Welch 等双组方法需恰好两组；ANOVA 和 Kruskal 可比较多组。",
        ),
        *_groups(),
        field(
            "alpha", "显著性水平", "float", default=0.05, info="0 与 1 之间；结果同时保留效应量与适用假设。"
        ),
        field(
            "pair_id",
            "配对 ID 列",
            when={"method": ["paired_t"]},
            required=True,
            info="配对 t 检验必填。每个 ID 在每组仅有一条记录，不按行顺序猜测配对。",
        ),
        field(
            "incomplete_pairs",
            "不完整配对处理",
            "choice",
            default="error",
            choices=("error", "drop"),
            when={"method": ["paired_t"]},
            info="默认报错；选择 drop 明确丢弃不完整配对。",
        ),
    ],
    "stats.multiple": [
        field(
            "method",
            "多重比较方法",
            "choice",
            default="holm",
            choices=("holm", "fdr", "tukey", "dunn"),
            info="Holm/FDR 校正已有 p 值；Tukey/Dunn 从分组原始测量值进行比较。",
        ),
        field(
            "column",
            "p 值 / 测量值列",
            default="pvalue",
            info="Holm/FDR 选择 0 至 1 的 p 值列；Tukey/Dunn 选择原始测量值列，每组至少两个观测。",
        ),
        *_groups(when={"method": ["tukey", "dunn"]}, include_column=False),
        field("alpha", "显著性水平", "float", default=0.05, info="0 与 1 之间；整个比较族使用相同阈值。"),
        field(
            "correction",
            "Dunn 校正方法",
            "choice",
            default="holm",
            choices=("holm", "fdr"),
            when={"method": ["dunn"]},
            info="对 Dunn 成对比较的 p 值应用 Holm 或 Benjamini-Hochberg FDR。",
        ),
    ],
    "stats.regression": [
        field(
            "method",
            "回归模型",
            "choice",
            default="linear",
            choices=_REGRESSORS,
            info="先拆分训练/测试集，再拟合缩放器；输出测试集结果、模型及清单。",
        ),
        *_dataset(required=True),
        *_validation_fields(),
        *_diagnostic_fields(),
        field(
            "test_size", "测试集比例", "float", default=0.2, info="0 与 1 之间；训练和测试各需至少两个样本。"
        ),
        *_model_options("method", choices=_REGRESSORS),
        *_output(),
    ],
    "stats.predict": [
        field(
            "prediction_task",
            "预测任务",
            "choice",
            default="train",
            choices=("train", "saved"),
            ui_only=True,
            info="train 训练新模型；saved 使用本机模型或上游清单，自动读取清单中的特征顺序。",
        ),
        *_for_task("prediction_task", "saved", _saved_model()),
        *_for_task(
            "prediction_task",
            "train",
            [
                field(
                    "method",
                    "预测模型",
                    "choice",
                    default="random_forest",
                    choices=_PREDICTORS,
                    info="无已有模型输入时训练；同一试样重复测量应填写独立样本分组列。",
                ),
                *_dataset(),
                *_validation_fields(),
                *_diagnostic_fields(),
                field(
                    "test_size",
                    "训练时的测试集比例",
                    "float",
                    default=0.2,
                    info="0 与 1 之间；训练和测试各至少两个样本。",
                ),
                *_model_options("method", choices=_PREDICTORS),
                *_output(),
            ],
        ),
    ],
    "stats.evaluate": [
        field(
            "evaluation_task",
            "评估数据来源",
            "choice",
            default="train",
            choices=("train", "saved", "predictions"),
            ui_only=True,
            info="train 训练评估；saved 读取已有模型清单；predictions 计算已有真实值和预测值的指标。",
        ),
        field(
            "residual_diagnostics",
            "输出残差诊断",
            "bool",
            default=False,
            when={"evaluation_task": ["train"]},
            info="对留出集或每折预测报告残差摘要；只描述已观察到的误差。",
        ),
        *_for_task("evaluation_task", "saved", _saved_model()),
        *_for_task(
            "evaluation_task",
            "predictions",
            [
                field(
                    "y_true",
                    "已有真实值列",
                    info="与预测值列一起填写时直接计算指标；上游 Data 也可提供两个数组。",
                ),
                field(
                    "y_pred",
                    "已有预测值列",
                    info="与真实值列对齐且至少两个有限观测；此模式不训练或保存模型。",
                ),
            ],
        ),
        *_for_task(
            "evaluation_task",
            "train",
            [
                field(
                    "method",
                    "重新训练的评估方式",
                    "choice",
                    default="cv",
                    choices=("cv", "holdout"),
                    info="无已有模型或预测数据输入时，按所选方式训练并计算评估指标。",
                ),
                field(
                    "model_method",
                    "训练模型",
                    "choice",
                    default="linear",
                    choices=(*_REGRESSORS, *_PREDICTORS),
                    info="交叉验证每折独立拟合预处理，holdout 仅在训练集拟合。",
                ),
                field(
                    "models",
                    "比较多个候选模型（可选）",
                    "list",
                    suggestions=[*_REGRESSORS, *_PREDICTORS],
                    info="留空使用单个训练模型；选多个时用完全一致的留出/验证折比较，输出分数表，不自动重训或保存胜出者。",
                ),
                *_dataset(),
                *_validation_fields(cv=True),
                *_diagnostic_fields(residual=False),
                field(
                    "folds",
                    "交叉验证折数",
                    "int",
                    default=5,
                    when={"method": ["cv"]},
                    info="至少 2 折，每折至少两个测试观测；分组验证的组数不能少于折数。",
                ),
                field(
                    "test_size",
                    "测试集比例",
                    "float",
                    default=0.2,
                    when={"method": ["holdout"]},
                    info="0 与 1 之间；仅 holdout 训练评估使用。",
                ),
                *_model_options("model_method", choices=(*_REGRESSORS, *_PREDICTORS)),
                *_output(),
            ],
        ),
    ],
}


# artifacts_output declares capability: saved-model prediction, provided metrics,
# and CV do not write files; fresh fitting/holdout do. No node reads file uploads.
CONTRACTS = {
    "stats.grouped": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "TableProperties",
    },
    "stats.distribution": {
        "table_output": False,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "ChartColumn",
    },
    "stats.correlation": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "ChartScatter",
    },
    "stats.significance": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "Scale",
    },
    "stats.multiple": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "ListChecks",
    },
    "stats.regression": {
        "table_output": True,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "ChartNoAxesCombined",
    },
    "stats.predict": {
        "table_output": True,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "BrainCircuit",
    },
    "stats.evaluate": {"table_output": True, "artifacts_output": True, "upload_types": [], "icon": "Gauge"},
}

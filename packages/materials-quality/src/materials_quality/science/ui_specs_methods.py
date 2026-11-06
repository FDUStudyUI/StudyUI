"""Human-readable controls for method discovery; unknown is never affirmative."""

from .ui_types import field


def _condition(path, label, info):
    return field(path, label, "choice", default="unknown", choices=("unknown", "yes", "no"), info=info)


SPECS = {
    "lit.method_recommend": [
        field("query", "方法关键词", default="", info="例如 SNV、基线、峰位；无文字命中时返回空表。"),
        field(
            "goal",
            "分析目标",
            "choice",
            default="unknown",
            choices=(
                "unknown",
                "smooth",
                "baseline",
                "normalization",
                "derivative",
                "peak_position",
                "area",
                "absolute_intensity",
                "dimensionality",
                "regression",
            ),
        ),
        field(
            "signal_type",
            "测量信号定义",
            "choice",
            default="unknown",
            choices=(
                "unknown",
                "nir_absorbance",
                "nir_reflectance",
                "ftir_absorbance",
                "raman_intensity",
                "darkfield_intensity",
            ),
            info="材料名称不能代替信号定义；透过率必须另行明确转换。",
        ),
        field(
            "x_unit",
            "物理坐标单位",
            "choice",
            default="unknown",
            choices=("unknown", "nm", "um", "cm^-1", "1/cm"),
        ),
        field("y_unit", "信号单位", info="例如 absorbance、counts；未知时留空。"),
        field("top_k", "最多显示候选", "int", default=5, info="1–20；命中不代表科学验证通过。"),
        _condition("allow_intensity_loss", "允许去除绝对强度", "SNV/MSC 改变每条光谱的强度尺度。"),
        _condition("equally_spaced", "坐标是否等间距", "接入曲线表时将重新核算，声明不能覆盖数据事实。"),
        _condition("nonzero_variance", "逐谱是否有非零方差", "零方差光谱不能进行 SNV。"),
        _condition("positive_peaks", "目标是否为向上的峰", "不自动翻转透过率谷或负峰。"),
        _condition("nonnegative", "输入是否全部非负", "NMF 组合条件；NMF 尚未开放执行。"),
        field(
            "fit_scope",
            "学习型变换拟合范围",
            "choice",
            default="unknown",
            choices=("unknown", "train_only", "all_data"),
            info="PCA/PLS/参考谱只可从训练集学习；交叉验证每折重拟合。",
        ),
        _condition(
            "split_confirmed", "是否已划分训练与测试", "表中使用 train/test 标签；测试集不能参与方法选择。"
        ),
        _condition(
            "groups_disjoint", "样品与重复组是否隔离", "同一样品的重复或跨仪器记录不可跨训练/测试两侧。"
        ),
        field("x", "曲线坐标列", default="x"),
        field("y", "曲线信号列", default="y"),
        field("smooth_window", "SG 窗口点数", "int", info="正奇数，不超过曲线长度；按实验分辨率选择。"),
        field("smooth_order", "SG 多项式阶数", "int", info="小于窗口且不小于导数阶数。"),
        field("prominence", "候选峰突出度", "float", info="正数，使用信号单位；不自动放宽阈值。"),
        field(
            "area_ranges",
            "积分窗口",
            "table",
            converter="pairs",
            pair_columns=["lower", "upper"],
            table_schema=[
                {"name": "lower", "display_name": "下限", "type": "float"},
                {"name": "upper", "display_name": "上限", "type": "float"},
            ],
            info="按物理坐标填写，每行一个窗口。",
        ),
        field("feature_columns", "模型特征列", "list", info="样品×波段宽表中的数值列；不可包含目标值。"),
        field("sample_column", "样品身份列"),
        field("split_column", "训练/测试标签列", info="列中只能包含 train 与 test。"),
        field("group_column", "重复或仪器组对应的样品组列", info="可选；同组必须始终在同侧。"),
        field("target_column", "回归参考值列"),
        field("n_components", "主成分/潜变量数", "int", info="须在训练集内决定，执行时检查样本数和秩。"),
        field(
            "method_ids",
            "指定方法卡 ID",
            "list",
            advanced=True,
            info="可留空；指定时即使条件不符也显示原因。",
        ),
        field(
            "sequence",
            "顺序检查的方法 ID",
            "list",
            advanced=True,
            info="例如 snv,nmf；只检查条件，不执行或自动修复组合。",
        ),
        field("reference_source", "MSC 参考谱来源", advanced=True, info="预留条件说明；MSC 尚未开放执行。"),
    ],
}

CONTRACTS = {
    "lit.method_recommend": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "BookOpenCheck",
    },
}

# A goal opens its relevant controls; unknown leaves the short discovery form.
# The advanced JSON/API contract still accepts explicit conditions independently.
_CURVE_GOALS = [
    "smooth",
    "baseline",
    "normalization",
    "derivative",
    "peak_position",
    "area",
    "absolute_intensity",
]
_MODEL_GOALS = ["dimensionality", "regression"]
_GOALS_BY_FIELD = {
    "x": _CURVE_GOALS,
    "y": _CURVE_GOALS,
    "allow_intensity_loss": ["normalization", "regression", "dimensionality"],
    "nonzero_variance": ["normalization", "regression", "dimensionality"],
    "equally_spaced": ["smooth", "baseline", "derivative"],
    "positive_peaks": ["baseline", "peak_position", "absolute_intensity"],
    "smooth_window": ["smooth", "derivative"],
    "smooth_order": ["smooth", "derivative"],
    "prominence": ["peak_position", "absolute_intensity"],
    "area_ranges": ["area", "absolute_intensity"],
    "fit_scope": _MODEL_GOALS,
    "split_confirmed": _MODEL_GOALS,
    "groups_disjoint": _MODEL_GOALS,
    "feature_columns": _MODEL_GOALS,
    "sample_column": _MODEL_GOALS,
    "split_column": _MODEL_GOALS,
    "group_column": _MODEL_GOALS,
    "target_column": ["regression"],
    "n_components": _MODEL_GOALS,
}
for _descriptor in SPECS["lit.method_recommend"]:
    if _descriptor["path"] in _GOALS_BY_FIELD:
        _descriptor["when"] = {"goal": _GOALS_BY_FIELD[_descriptor["path"]]}
    if _descriptor["path"] == "nonnegative":
        _descriptor["advanced"] = True
    if _descriptor["path"] == "goal":
        _descriptor["info"] = "先选择目标以展开相关条件；unknown 仅浏览候选，未确认条件保持缺失。"

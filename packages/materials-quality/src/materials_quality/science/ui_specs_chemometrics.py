"""Native controls for explicit-partition PCA/PLS; no hand-written JSON required."""

from .ui_types import field

SPECS = {
    "materials.chemometrics": [
        field(
            "method",
            "化学计量学方法",
            "choice",
            default="pca",
            choices=["pca", "pls"],
            info="PCA 提取训练集方差成分；PLS 用光谱预测单个连续目标。均仅在训练数据拟合。",
        ),
        field(
            "feature_columns",
            "光谱/特征列",
            "list",
            required=True,
            info="逐列选择数值波段；每行一个样本。不含目标、样品标识、分组或划分列，禁止非有限值。",
        ),
        field(
            "target_column",
            "连续目标列",
            required=True,
            when={"method": ["pls"]},
            info="PLS 的实测浓度/含量等连续响应列；须有有限值，训练集不能恒定。",
        ),
        field(
            "sample_column",
            "样品身份列",
            required=True,
            info="明确真实样品标识；同一样品的重复或跨仪器记录使用相同标识，禁止跨训练/测试两侧。",
        ),
        field(
            "split_column",
            "训练/测试划分列",
            required=True,
            info="上游表明确填写 train 或 test；至少三个训练行。仅 train 时不报告独立测试性能。",
        ),
        field(
            "group_column",
            "重复/批次分组列",
            info="可选；要求一整个组位于同一划分，也用于训练集交叉验证。留空按样品身份分组。",
        ),
        field(
            "n_components",
            "成分数（CV 时为搜索上限）",
            "int",
            default=2,
            info="正整数且不超过训练行数减一、特征数及训练矩阵中心化秩；CV 逐一比较 1 至该上限。",
        ),
        field(
            "scale",
            "按训练集标准差缩放特征",
            "bool",
            default=True,
            info="始终按训练集均值中心化；勾选再除训练标准差。各 CV 训练折独立重新拟合。",
        ),
        field(
            "cv_folds",
            "训练集成分选择折数",
            "int",
            default=0,
            when={"method": ["pls"]},
            info="0 固定成分；>=2 按样品/分组交叉验证选训练折外 RMSE 最低的成分数。测试集从不参与选择。",
        ),
    ]
}

CONTRACTS = {
    "materials.chemometrics": {
        "table_output": True,
        "features_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "ChartScatter",
    }
}

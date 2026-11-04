"""Native, auditable table-transformation forms with exact source config keys."""

from .ui_types import field

_CALIBRATIONS = ["blank_subtract", "reference_ratio", "linear_calibration"]


def _columns(when=None):
    return field(
        "columns",
        "处理 / 保留列名",
        "list",
        when=when,
        info="填写表中实际列名，可手填自定义名称；留空处理全部列，数值方法请明确选取数值列。",
    )


def _missing_tokens():
    return field(
        "missing_tokens",
        "额外缺失标记",
        "list",
        info="留空仅识别真实空值与空白；填写时替代默认标记集，例如 NA、N/A、null。真实空值始终为缺失。",
    )


def _schema(*columns):
    return [
        {"name": name, "display_name": label, "type": kind, "description": label, "edit_mode": "inline"}
        for name, label, kind in columns
    ]


SPECS = {
    "preprocess.filter": [
        field(
            "conditions",
            "行筛选条件",
            "table",
            converter="filter_conditions",
            table_schema=_schema(
                ("column", "列名", "str"), ("op", "运算符", "str"), ("value", "比较值", "str")
            ),
            info="op 支持 eq/ne/lt/le/gt/ge/in/not_in/contains/isna/notna；"
            "数值自动解析，in/not_in 用逗号列表或 JSON 列表；isna/notna 无需值。",
        ),
        field(
            "logic",
            "条件组合方式",
            "choice",
            default="and",
            choices=["and", "or"],
            info="and 要求所有条件满足，or 要求任一条件满足；无条件时保留全部行。",
        ),
        field(
            "drop_empty",
            "删除全空行",
            "bool",
            default=False,
            info="先判断原表所有列是否为空白/默认缺失标记，再与条件结果取交集。",
        ),
        _columns(),
        field(
            "rename",
            "列重命名映射",
            "dict",
            info="原列名到新列名的映射；原列须位于保留列内，重命名后列名须唯一。",
        ),
        field(
            "derived_columns",
            "公式派生列（筛选前计算）",
            "table",
            table_schema=_schema(
                ("column", "新列名", "str"), ("expression", "数值公式", "str"), ("unit", "输出单位", "str")
            ),
            info="仅支持标识符列名、+ - * / **、abs/sqrt/log/log10/exp/minimum/maximum；"
            "禁止对象访问与代码执行。缩放/同单位加减保留单位；乘除/开方/幂等须声明实际输出单位，数值不自动换算。",
        ),
    ],
    "preprocess.missing": [
        field(
            "method",
            "缺失值处理方式",
            "choice",
            default="keep",
            choices=["keep", "drop", "mean", "median", "mode", "ffill", "linear"],
            info="keep 保留，drop 删除所选列含缺失的行；其余方法可分组填充；不自动外推边界。",
        ),
        _columns(),
        _missing_tokens(),
        field(
            "group_by",
            "分组列",
            "list",
            when={"method": ["mean", "median", "mode", "ffill", "linear"]},
            info="留空使用全表；填写后仅在每组内计算基线/插值，组键不得缺失。",
        ),
        field(
            "order_by",
            "排序 / 插值坐标列",
            required=True,
            when={"method": ["ffill", "linear"]},
            info="须显式填写数值或日期时间坐标列；组内唯一且单调，需先在上游明确排序。",
        ),
        field(
            "continuous",
            "确认所选量可连续插值",
            "bool",
            default=False,
            when={"method": ["linear"]},
            info="线性插值必须明确勾选；每组每列至少两个观测点，仅填已知坐标范围内部的缺失值。",
        ),
    ],
    "preprocess.units": [
        field(
            "source_units",
            "原始单位映射",
            "dict",
            info="列名到原始单位，如 stress:MPa、temperature:degC；"
            "也可读取上游 Data.units、表 attrs 或单元格内单位。",
        ),
        field(
            "target_units",
            "目标单位映射",
            "dict",
            required=True,
            info="必须指定至少一列，如 stress:Pa；原始与目标物理量维度须一致，保留缺失单元格。",
        ),
        _missing_tokens(),
    ],
    "preprocess.reshape": [
        field(
            "method",
            "格式转换方式",
            "choice",
            default="types",
            choices=["types", "wide_to_long", "long_to_wide"],
            info="types 显式转换类型；wide_to_long 将测量列展开；"
            "long_to_wide 以唯一键组合透视，不自动聚合重复值。",
        ),
        field(
            "types",
            "列目标类型映射",
            "dict",
            required=True,
            when={"method": ["types"]},
            info="列名到 number/integer/datetime/category/string/boolean；"
            "integer 须可精确表示为 Int64，boolean 仅接受 true/false。",
        ),
        field(
            "date_formats",
            "日期格式映射",
            "dict",
            when={"method": ["types"]},
            info="datetime 列必须指定精确格式，如 date:%Y-%m-%d；要求原始字符串与格式严格一致。",
        ),
        field(
            "categories",
            "分类允许值映射",
            "dict",
            converter="list_mapping",
            when={"method": ["types"]},
            info="category 列可指定逗号分隔的允许类别，如 phase:alpha,beta；不在列表中的非空值会报错。",
        ),
        field(
            "id_vars",
            "宽转长的标识列",
            "list",
            when={"method": ["wide_to_long"]},
            info="展开后原样保留的列，如 sample_id、temperature。",
        ),
        field(
            "value_vars",
            "宽转长的测量列",
            "list",
            when={"method": ["wide_to_long"]},
            info="需要展开成多行的测量列；留空使用所有非标识列。",
        ),
        field(
            "var_name",
            "长表变量名列",
            default="variable",
            when={"method": ["wide_to_long"]},
            info="存放原测量列名称的新列名，不能与保留列冲突。",
        ),
        field(
            "value_name",
            "长表测量值列",
            default="value",
            when={"method": ["wide_to_long"]},
            info="存放测量值的新列名，不能与已有列冲突。",
        ),
        field(
            "index",
            "长转宽的行标识列",
            "list",
            required=True,
            when={"method": ["long_to_wide"]},
            info="一列或多列共同标识输出行，行标识与列分类的组合必须唯一。",
        ),
        field(
            "columns",
            "长转宽的列分类字段",
            required=True,
            when={"method": ["long_to_wide"]},
            info="一个实际列名，该字段的各个取值将成为新的宽表列名。",
        ),
        field(
            "values",
            "长转宽的测量值字段",
            required=True,
            when={"method": ["long_to_wide"]},
            info="填写一个实际列名以得到平坦列结构；重复键须先显式汇总，节点不会隐式取平均。",
        ),
    ],
    "preprocess.merge": [
        field(
            "method",
            "多表合并方式",
            "choice",
            default="join",
            choices=["join", "append", "asof", "specimen"],
            info="specimen 按样品主表逐一关联仪器特征；join 按键关联，append 逐行追加，"
            "asof 为恰好两表的有容差近邻关联。",
        ),
        field(
            "on",
            "关联键 / 坐标列",
            "list",
            converter="column_or_list",
            default=["sample_id"],
            required=True,
            when={"method": ["join", "asof", "specimen"]},
            info="specimen 可填写多列共同标识一个样品，各表须使用同名、同类型的文本或整数键。"
            "join 可填写多个键；asof 必须恰好一列，坐标不得缺失且两表均须按坐标递增排序。",
        ),
        field(
            "unmatched",
            "未匹配样品的处理",
            "choice",
            default="report",
            choices=["report", "error"],
            when={"method": ["specimen"]},
            info="report 保留全部主表样品并报告缺失特征、主表外的特征；error 要求各表完整覆盖主表。",
        ),
        field(
            "allow_undeclared_features",
            "确认无声明的输入是样品特征表",
            "bool",
            default=False,
            when={"method": ["specimen"]},
            info="仅在已核对导入表每个样品至多一行，且每列特征的测量条件明确时开启。"
            "重复测量须在上游按明确的样品和测量条件处理。",
        ),
        field(
            "how",
            "键关联保留方式",
            "choice",
            default="left",
            choices=["left", "right", "inner", "outer"],
            when={"method": ["join"]},
            info="left 保留左表键，right 保留右表键，inner 只保留交集，outer 保留并集。",
        ),
        field(
            "validate",
            "键基数校验",
            "choice",
            default="one_to_one",
            choices=["one_to_one", "one_to_many", "many_to_one", "many_to_many"],
            when={"method": ["join"]},
            info="默认要求两侧键唯一；按实验记录的真实重复关系选择，避免无意的笛卡尔扩增。",
        ),
        field(
            "suffixes",
            "重复列名的左右后缀",
            "list",
            default=["_left", "_right"],
            when={"method": ["join", "asof"]},
            info="恰好两个文本后缀，依次用于左表和右表的同名非键列。",
        ),
        field(
            "ignore_index",
            "追加后重建行索引",
            "bool",
            default=True,
            when={"method": ["append"]},
            info="打开后生成连续索引；不同列集合按名称对齐，缺失列保留为空。",
        ),
        field(
            "by",
            "近邻关联的分组键",
            "list",
            when={"method": ["asof"]},
            info="可选；仅在同组内寻找近邻，组键不得缺失，右表同组坐标不得重复。",
        ),
        field(
            "tolerance",
            "近邻最大容差",
            converter="number_or_text",
            required=True,
            when={"method": ["asof"]},
            info="必须填写；数值坐标使用数值容差，日期时间坐标使用 1s、10ms 等 pandas 时间间隔。",
        ),
        field(
            "direction",
            "近邻匹配方向",
            "choice",
            default="nearest",
            choices=["nearest", "backward", "forward"],
            when={"method": ["asof"]},
            info="nearest 选最近点，等距两候选会报错；backward/forward 明确选择较早/较晚坐标。",
        ),
    ],
    "preprocess.normalize": [
        field(
            "method",
            "归一化或校准方式",
            "choice",
            default="minmax",
            choices=["minmax", "zscore", "robust", *_CALIBRATIONS],
            info="minmax 按极差，zscore 按总体标准差 ddof=0，robust 按中位数与四分位距；"
            "blank_subtract 扣空白，reference_ratio 按参考归一化，linear_calibration 拟合标准对。",
        ),
        _columns({"method": ["minmax", "zscore", "robust"]}),
        field(
            "calibration_signal",
            "原始信号列",
            required=True,
            when={"method": _CALIBRATIONS},
            info="填写原表中保留的测量信号列。",
        ),
        field(
            "calibration_input_unit",
            "原始信号和参考的单位",
            required=True,
            when={"method": _CALIBRATIONS},
            info="标准信号、空白、参考必须使用同一单位。",
        ),
        field(
            "calibration_output",
            "校准后新列名",
            default="corrected",
            when={"method": _CALIBRATIONS},
            info="写入未使用的列名，保留原始读数。",
        ),
        field(
            "calibration_source",
            "校准来源或标准编号",
            required=True,
            when={"method": _CALIBRATIONS},
            info="记录标准表、证书编号或空白测量的来源。",
        ),
        field(
            "calibration_blank",
            "空白值",
            "float",
            default=0.0,
            when={"method": ["blank_subtract", "reference_ratio"]},
            info="按信号单位填写；选择空白列时采用逐行空白。",
        ),
        field(
            "calibration_blank_column",
            "同一行的空白列",
            when={"method": ["blank_subtract", "reference_ratio"]},
            info="可选。填写后用对应行的空白值。",
        ),
        field(
            "calibration_reference",
            "参考值",
            "float",
            when={"method": ["reference_ratio"]},
            info="填写固定参考值，或选择对应参考列。",
        ),
        field(
            "calibration_reference_column",
            "同一行的参考列",
            when={"method": ["reference_ratio"]},
            info="可选。填写后用对应行的参考值。",
        ),
        field(
            "calibration_output_unit",
            "已知标准值与校准结果的单位",
            required=True,
            when={"method": ["linear_calibration"]},
            info="填写已知标准的实际单位，例如 MPa。",
        ),
        field(
            "calibration_standards",
            "线性标定的标准对",
            "table",
            required=True,
            when={"method": ["linear_calibration"]},
            converter="pairs",
            pair_columns=["signal", "value"],
            table_schema=_schema(("signal", "标准信号", "float"), ("value", "已知值", "float")),
            info="至少填三种不同的标准信号及相应已知值。默认拒绝标定范围外的样品。",
        ),
        field(
            "calibration_allow_extrapolation",
            "允许超出标定范围",
            "bool",
            default=False,
            advanced=True,
            when={"method": ["linear_calibration"]},
            info="仅在有依据时勾选；报告会标出外推行数。",
        ),
        field(
            "group_by",
            "归一化分组 / 校准重复测量分组",
            "list",
            info="归一化按组拟合，留空按全表。校准时仅填写同一样品、同一条件的重复测量分组；"
            "留空则不计算重复测量波动。",
        ),
    ],
}


CONTRACTS = {
    key: {"table_output": True, "artifacts_output": False, "upload_types": [], "icon": icon}
    for key, icon in [
        ("preprocess.filter", "ListFilter"),
        ("preprocess.missing", "Eraser"),
        ("preprocess.units", "Ruler"),
        ("preprocess.reshape", "Table"),
        ("preprocess.merge", "Merge"),
        ("preprocess.normalize", "SlidersHorizontal"),
    ]
}

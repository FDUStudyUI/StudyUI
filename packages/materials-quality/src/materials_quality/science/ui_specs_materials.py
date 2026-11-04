"""Native material-analysis forms; parameter paths follow the scientific functions."""

from .ui_types import field


def _schema(*columns):
    return [{"name": name, "display_name": label, "type": kind} for name, label, kind in columns]


def _curve_fields():
    return [
        field(
            "x",
            "横坐标列",
            default="x",
            required=True,
            info="填写表中实际列名；至少三个有限数值点，横坐标须严格递增且不重复。",
        ),
        field(
            "y",
            "信号列",
            default="y",
            required=True,
            info="填写原始信号列名；不自动转换透过率、吸光度或仪器符号。",
        ),
        field(
            "sort",
            "按横坐标排序",
            "bool",
            default=False,
            info="仅适用于无序但唯一的坐标；加载/卸载曲线应先明确截取单调段。",
        ),
        field(
            "baseline.method",
            "基线方法",
            "choice",
            default="none",
            choices=["none", "constant", "linear", "anchors"],
            info="none 不扣除；constant 扣常数；linear 连首尾；anchors 使用覆盖全测量范围的锚点。",
        ),
        field(
            "baseline.value",
            "常数基线值",
            "float",
            default=0.0,
            when={"baseline.method": ["constant"]},
            info="有限数值，单位与输入信号列相同。",
        ),
        field(
            "baseline.points",
            "基线锚点",
            "table",
            when={"baseline.method": ["anchors"]},
            required=True,
            converter="pairs",
            pair_columns=["x", "y"],
            table_schema=_schema(("x", "横坐标", "float"), ("y", "基线信号", "float")),
            info="至少两行；横坐标严格递增，首末锚点须覆盖全测量范围；使用原始坐标及信号单位。",
        ),
        field(
            "smooth_window",
            "平滑窗口（点数）",
            "int",
            default=0,
            info="0 关闭；开启时须为正奇数、不超过样本数且大于多项式阶数。要求横坐标等间距。",
        ),
        field(
            "smooth_order",
            "平滑多项式阶数",
            "int",
            default=2,
            info="非负整数；启用平滑时须小于窗口点数。使用 Savitzky–Golay 方法。",
        ),
        field(
            "prominence_mode",
            "寻峰阈值策略",
            "choice",
            default="兼容自动",
            choices=["兼容自动", "显式阈值", "旧版全谱相对阈值", "噪声参考"],
            value_map={
                "兼容自动": "legacy_auto",
                "显式阈值": "absolute",
                "旧版全谱相对阈值": "legacy_relative",
                "噪声参考": "noise_reference",
            },
            omit_values=["legacy_auto"],
            info="兼容自动：留空突出度沿用全谱极差 5%，手填沿用显式阈值；噪声参考须提供可信背景窗口。",
        ),
        field(
            "prominence",
            "寻峰突出度",
            "float",
            when={"prominence_mode": ["legacy_auto", "absolute"]},
            info="留空按信号极差的 5% 自适应；手填须大于 0，单位与基线校正后的信号相同。",
        ),
        field(
            "noise_window",
            "噪声参考窗口（原始坐标单位）",
            "range",
            required=True,
            when={"prominence_mode": ["noise_reference"]},
            info="明确填写背景区间；至少五个实测点且有正 MAD。不自动猜测或避开强峰，需复核污染和漂移。",
        ),
        field(
            "noise_multiplier",
            "噪声 MAD 倍数",
            "float",
            default=3.0,
            when={"prominence_mode": ["noise_reference"]},
            info="正数；阈值为背景窗口正态缩放 MAD 的指定倍数；不自动校准误报或修正相关噪声。",
        ),
        field(
            "peak_distance",
            "最小峰间距（采样点）",
            "int",
            default=1,
            info="整数且至少为 1；这是采样点数，不是横坐标单位。",
        ),
        field(
            "peak_distance_x",
            "最小峰间距（原始坐标单位）",
            "float",
            info="可选正数；非均匀采样直接在坐标域抑制过近峰，不重采样；与采样点数约束同时生效。",
        ),
    ]


def _reference_fields():
    return [
        field(
            "match",
            "参考库匹配",
            "choice",
            default="none",
            choices=["none", "profile", "peaks"],
            info="默认关闭；profile 比较完整谱形，peaks 在给定容差内一对一匹配峰位；分数仅用于候选排序。",
        ),
        field(
            "match_tolerance",
            "峰位容差",
            "float",
            default=0.1,
            when={"match": ["peaks"]},
            info="须大于 0，单位与横坐标相同；参考库峰位必须使用相同单位。",
        ),
        field(
            "references",
            "用户参考库（高级）",
            "json",
            advanced=True,
            info="也可由上游 Data.references 提供；名称须唯一。峰匹配用 name/peaks，"
            "谱形匹配或参考拟合用 name/x/y；"
            "谱形须非负、非零并覆盖测量范围，声明的 x_unit 必须一致。仅评价所提供库。",
        ),
    ]


def _area_fields(when=None):
    return [
        field(
            "area_ranges",
            "积分区间",
            "table",
            when=when,
            converter="pairs",
            pair_columns=["lower", "upper"],
            table_schema=_schema(("lower", "下限", "float"), ("upper", "上限", "float")),
            info="留空使用全测量范围；每行下限 < 上限且均在测量范围内，单位同横坐标。"
            "定量分析请选互不重叠区间。",
        )
    ]


def _morphology_fields(sem=False):
    image = {"method": ["image"]} if sem else {}
    return [
        field(
            "path",
            "图像或文件路径",
            when=image or None,
            info="可上传图像或填写本地完整路径；也可连接含 file_path 或 image 数组的上游 Data。",
        ),
        field(
            "feature",
            "前景物理含义",
            "choice",
            default="particle",
            choices=["particle", "pore", "grain"],
            when=image or None,
            info="按实际样品解释选择颗粒、孔或晶粒；二维连通区域不会自动分开相接颗粒。",
        ),
        field(
            "segmentation",
            "分割方法",
            "choice",
            default="threshold",
            choices=["threshold", "ml"],
            when=image or None,
            info="threshold 用亮度阈值；ml 需要上游同一图像的 training_labels，不含预训练材料模型。",
        ),
        field(
            "threshold",
            "阈值（otsu 或数值）",
            default="otsu",
            converter="number_or_text",
            when={**image, "segmentation": ["threshold"]},
            info="otsu 自动估计；也可填原图灰度尺度的有限数值。"
            "常量图像必须手填阈值，灰度图不强制缩放到 0–255。",
        ),
        field(
            "foreground",
            "阈值前景",
            "choice",
            default="bright",
            choices=["bright", "dark"],
            when={**image, "segmentation": ["threshold"]},
            info="bright：灰度 > 阈值；dark：灰度 ≤ 阈值。请按目标结构实际亮暗选择。",
        ),
        field(
            "ml_features",
            "监督分割特征",
            "choice",
            default="intensity",
            choices=["intensity", "multiscale"],
            when={**image, "segmentation": ["ml"]},
            info="默认仅亮度；多尺度还用平滑、梯度与局部方差。"
            "Data.training_labels 必须同形状，取 -1/0/1，且包含两类标注。",
        ),
        field(
            "random_state",
            "随机种子",
            "int",
            default=0,
            when={**image, "segmentation": ["ml"]},
            info="整数；控制随机森林可重复性，不代表已完成独立准确率验证。",
        ),
        field(
            "pixel_size",
            "物理像素尺寸",
            "float",
            when=image or None,
            info="留空且物理单位也留空时按 px 输出。物理标定时须大于 0，并同时填写每像素对应的实际长度单位。",
        ),
        field(
            "spatial_unit",
            "物理长度单位",
            when=image or None,
            info="与像素尺寸一起填写，例如 um、nm、mm；物理标定不能填 px。无标定时两个字段均留空。",
        ),
        field(
            "connectivity",
            "连通邻域",
            "choice",
            default=1,
            choices=[1, 2],
            when=image or None,
            converter="int",
            info="1 为四邻域，2 为八邻域；对角接触区域是否合并由此决定。",
        ),
        field(
            "min_area_pixels",
            "最小区域面积（像素）",
            "int",
            default=1,
            when=image or None,
            info="至少为 1 的整数；小于此像素面积的前景区域被移除，不使用标定后面积。",
        ),
        field(
            "output_dir",
            "分割附件目录",
            when=image or None,
            info="留空创建临时目录；输出 materials_mask.png 和 materials_labels.npy，输入图像受到覆盖保护。",
        ),
    ]


SPECS = {
    "materials.xrd": [
        *_curve_fields(),
        field(
            "x_unit",
            "横坐标单位",
            default="deg",
            info="例如 2θ 对应 deg；须与参考库一致。峰宽是表观宽度，未扣仪器展宽。",
        ),
        field(
            "intensity_unit",
            "衍射强度单位",
            default="unspecified",
            info="声明输入信号列的实测单位（例如 counts）；只传播单位标签，不换算数值。未知时保留 unspecified。",
        ),
        *_reference_fields(),
        field(
            "whole_pattern",
            "全谱经验拟合",
            "choice",
            default="none",
            choices=["none", "reference", "gaussian"],
            info="默认关闭；reference 为参考谱非负组合，系数不是质量分数；"
            "gaussian 为高斯峰和。均不是 Rietveld 精修。",
        ),
        field(
            "fit_peaks",
            "高斯峰初值",
            "table",
            when={"whole_pattern": ["gaussian"]},
            required=True,
            table_schema=_schema(
                ("center", "峰中心", "float"), ("sigma", "标准差", "float"), ("amplitude", "峰高", "float")
            ),
            info="每行一个峰；峰中心在测量范围内部，sigma 与峰高均 > 0；"
            "中心和 sigma 用横坐标单位，峰高用信号单位。",
        ),
    ],
    "materials.spectra": [
        *_curve_fields(),
        field(
            "x_unit",
            "光谱横坐标单位",
            default="cm^-1",
            info="填写实际波数/波长单位，例如 cm^-1、nm；FTIR 应输入适当信号约定，不自动把透过率转为吸光度。",
        ),
        field(
            "normalization",
            "归一化",
            "choice",
            default="none",
            choices=["none", "max", "l2", "area"],
            info="none 保留量级；max 按最大绝对值；l2 按向量范数；area 按绝对信号积分。"
            "峰面积在归一化前计算。",
        ),
        *_area_fields(),
        *_reference_fields(),
    ],
    "materials.thermal": [
        field(
            "kind",
            "热分析类型",
            "choice",
            default="tg",
            choices=["tg", "dsc"],
            info="TG 分析失重阶段；DSC 按仪器吸热符号约定积分。切换类型后须核对纵轴单位。",
        ),
        *_curve_fields(),
        field(
            "x_unit",
            "温度或时间单位",
            "choice",
            default="degC",
            choices=["degC", "K", "s", "min"],
            info="须与横坐标数据一致；DSC 用温度作横坐标时还必须声明升温速率。",
        ),
        field(
            "y_unit",
            "质量或热流单位",
            "choice",
            default="%",
            choices=["%", "mg", "g", "W/g", "mW/mg", "mW/g", "W", "mW"],
            info="TG 仅可选 %、mg、g；DSC 必须改选 W/g、mW/mg、mW/g、W 或 mW。"
            "不得只更改单位标签而不转换数据。",
        ),
        field(
            "initial_mass",
            "TG 初始质量",
            "float",
            when={"kind": ["tg"]},
            info="留空使用首个校正质量值；手填须 > 0，单位同纵轴。使用 % 数据时通常首值约为 100。",
        ),
        field(
            "stage_threshold",
            "TG 失重速率阈值",
            "float",
            when={"kind": ["tg"]},
            info="留空采用最大失重速率的 5%（有正数下限）；手填 > 0，单位 percent/横坐标单位。"
            "阈值会影响阶段分界。",
        ),
        field(
            "endotherm",
            "DSC 吸热方向",
            "choice",
            choices=["positive", "negative"],
            required=True,
            when={"kind": ["dsc"]},
            info="按仪器约定明确选择正峰吸热或负峰吸热；不根据峰形推断。",
        ),
        field(
            "heating_rate",
            "DSC 升温速率",
            "float",
            required=True,
            when={"kind": ["dsc"], "x_unit": ["degC", "K"]},
            info="须 > 0；填写实际实验速率，不默认猜测。横坐标为时间时不使用此项。",
        ),
        field(
            "heating_rate_unit",
            "升温速率单位",
            "choice",
            default="K/min",
            choices=["K/min", "K/s", "degC/min", "degC/s"],
            when={"kind": ["dsc"], "x_unit": ["degC", "K"]},
            info="与实际升温速率数值配套；每分钟和每秒会影响焓积分换算。",
        ),
        *_area_fields({"kind": ["dsc"]}),
    ],
    "materials.mechanics": [
        field(
            "x",
            "应变列",
            default="strain",
            required=True,
            info="工程应变的实际列名；至少三个有限点且严格递增。",
        ),
        field(
            "y", "应力列", default="stress", required=True, info="工程应力的实际列名；仅用于单调拉伸加载段。"
        ),
        field(
            "strain_unit",
            "输入应变单位",
            "choice",
            default="fraction",
            choices=["fraction", "%"],
            info="fraction 表示 0.01 = 1%；% 表示 1 = 1%。拟合区间使用此输入单位。",
        ),
        field(
            "stress_unit",
            "输入应力单位",
            "choice",
            default="MPa",
            choices=["Pa", "kPa", "MPa", "GPa"],
            info="与原始数据一致；输出应力及弹性模量统一换算为 MPa。",
        ),
        field(
            "fit_range",
            "弹性拟合应变区间",
            "range",
            required=True,
            info="必须按输入应变单位手选递增上下限，位于实测范围内且至少包含三个点；不自动假定材料弹性区。",
        ),
        field(
            "yield_offset",
            "屈服偏移（绝对应变）",
            "float",
            default=0.002,
            info="须 > 0，始终使用 fraction；0.002 表示 0.2% 偏移，与输入应变单位选择无关。"
            "缺少实测交点时不报屈服强度。",
        ),
        field(
            "fracture_confirmed",
            "已有实验依据确认末点断裂",
            "bool",
            default=False,
            info="仅在实验确证最后测量点为断裂时勾选；否则断裂应变保持缺失。",
        ),
        field(
            "sort",
            "按应变排序",
            "bool",
            default=False,
            advanced=True,
            info="默认保留加载次序；仅对明确单调加载段的无序唯一点使用，不可混排加载/卸载路径。",
        ),
    ],
    "materials.sem_eds": [
        field(
            "method",
            "SEM/EDS 模式",
            "choice",
            default="image",
            choices=["image", "eds"],
            info="image 提取二维图像形貌；eds 读取外部已定量元素百分比，不做元素谱峰解卷积或 ZAF 校正。",
        ),
        *_morphology_fields(sem=True),
        field(
            "file_path",
            "EDS CSV 路径",
            when={"method": ["eds"]},
            info="优先连接结果表；也可上传 CSV、填写完整路径或连接上游 file_path。",
        ),
        field(
            "encoding",
            "CSV 编码",
            default="utf-8-sig",
            when={"method": ["eds"]},
            info="只用于读取 CSV；例如 utf-8-sig、utf-8、gb18030。",
        ),
        field(
            "element_column",
            "元素列",
            default="element",
            when={"method": ["eds"]},
            info="元素标识不能为空；同一组成内元素不能重复，多测点需设置组成分组列。",
        ),
        field(
            "percent_columns",
            "百分比列",
            "list",
            when={"method": ["eds"]},
            info="留空自动识别存在的 wt_percent、at_percent；自定义列必须是 0–100 的有限百分比值。",
        ),
        field(
            "group_by",
            "组成/测点分组列",
            when={"method": ["eds"]},
            info="多个测点请填写实际标识列；不得有缺失。留空将全表视为一个组成并核查总和与重复元素。",
        ),
    ],
    "materials.microstructure": _morphology_fields(),
}


_IMAGE_TYPES = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"]
CONTRACTS = {
    "materials.xrd": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "ChartLine",
    },
    "materials.spectra": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "Waves",
    },
    "materials.thermal": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "Thermometer",
    },
    "materials.mechanics": {
        "table_output": True,
        "artifacts_output": False,
        "upload_types": [],
        "icon": "Activity",
    },
    "materials.sem_eds": {
        "table_output": True,
        "artifacts_output": True,
        "upload_types": [*_IMAGE_TYPES, "csv"],
        "icon": "ScanLine",
    },
    "materials.microstructure": {
        "table_output": True,
        "artifacts_output": True,
        "upload_types": list(_IMAGE_TYPES),
        "icon": "Microscope",
    },
}

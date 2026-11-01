"""Typed plotting and export forms with honest artifact-only figure contracts."""

from .ui_types import field


def _figure_fields():
    return [
        field("title", "图标题", info="留空使用各图型的默认标题；应准确描述比较对象或诊断问题。"),
        field(
            "units",
            "列单位",
            "dict",
            info="键填原始列名，值填单位（如 stress → MPa）；用于标注并与输入单位元数据核对，不改变数值。",
        ),
        field("labels", "列显示名称", "dict", info="键填原始列名，值填轴标签；列选择仍使用原始列名。"),
        field(
            "color_map",
            "系列颜色",
            "dict",
            advanced=True,
            info="键填分组或系列名称，值填 Matplotlib 颜色（如 #0072B2）；留空按系列名称稳定分配颜色。",
        ),
        field(
            "profile",
            "出图预设",
            "choice",
            default="preview",
            choices=["preview", "paper"],
            info="preview 默认 150 dpi PNG；paper 默认 300 dpi PNG/SVG/PDF/TIFF，"
            "并生成图件清单与图注；TIFF 固定 600 dpi。",
        ),
        field(
            "formats",
            "导出格式",
            "list",
            choices=["png", "svg", "pdf", "tiff"],
            info="留空沿用预设；可填写 png、svg、pdf、tiff。始终保留 PNG 预览；SVG 文字可编辑。",
        ),
        field(
            "dpi",
            "PNG/PDF/SVG 导出 dpi",
            "int",
            info="留空随预设（预览 150、论文 300）；手填整数 72–1200。"
            "TIFF 使用 600 dpi，栅格不得超过 5000 万像素。",
        ),
        field(
            "width_mm",
            "图宽（mm）",
            "float",
            info="留空沿用预设（预览 177.8、论文 150 mm）；手填 50.8–762 mm。"
            "指定宽度后默认高度为宽度的 0.66。",
        ),
        field(
            "height_mm",
            "图高（mm）",
            "float",
            info="可选，须同时指定宽度或使用 paper 预设才生效；范围 50.8–762 mm。"
            "最终尺寸还受栅格像素上限约束。",
        ),
        field(
            "data_kind",
            "数据来源性质",
            "choice",
            default="unspecified",
            choices=["unspecified", "measured", "derived", "simulated", "synthetic"],
            info="按实际来源选择：实测、派生、模拟或合成演示；图件记录该声明，合成演示会明显标注。",
        ),
        field("purpose", "图件要说明的问题", info="用于图件证据清单；留空使用标题或图型名称。"),
        field(
            "evidence_role",
            "图件证据角色",
            advanced=True,
            info="例如 comparison、diagnostic；留空由图型设定。该标签不构成科学验证。",
        ),
        field(
            "output_dir",
            "图件输出目录",
            info="留空创建临时目录；同名文件自动使用新名称，输出清单保留原始数值。",
        ),
    ]


SPECS = {
    "viz.performance": [
        field(
            "method",
            "性能对比图型",
            "choice",
            default="scatter",
            choices=["scatter", "bar", "box", "violin"],
            info="scatter 散点；bar 均值±样本标准差；box 四分位箱图；violin 核密度。各图保留全部观测点。",
        ),
        field(
            "x",
            "横坐标列",
            default="x",
            required=True,
            when={"method": ["scatter"]},
            info="填写实际数值列名；散点图要求横、纵轴均为有限数值。",
        ),
        field(
            "y",
            "性能数值列",
            default="y",
            required=True,
            info="填写实际列名；要求有限数值。误差棒表示样本离散程度，不代表显著性。",
        ),
        field(
            "group",
            "分组列",
            info="可选，填写实际分组列名；不能缺失。留空把全部观测视为一组。小提琴图每组至少两个不同数值。",
        ),
        *_figure_fields(),
    ],
    "viz.spectra": [
        field(
            "method",
            "光谱/衍射图型",
            "choice",
            default="overlay",
            choices=["line", "overlay", "difference"],
            info="line 不偏移折线；overlay 允许逐条偏移；difference 计算第一条强度列减第二条。",
        ),
        field(
            "x",
            "光谱横坐标列",
            default="x",
            required=True,
            info="至少两个点，横坐标必须严格递增且唯一；不同采样网格应先在上游明确重采样。",
        ),
        field(
            "columns",
            "强度列列表",
            "list",
            default=["intensity"],
            required=True,
            info="填写一列或多列实际列名；difference 必须恰好两列，顺序决定相减方向。所有列使用同一横坐标。",
        ),
        field(
            "offset",
            "相邻曲线显示偏移",
            "float",
            default=0.0,
            when={"method": ["overlay"]},
            info="仅影响显示，单位同强度；第 i 条曲线加 i×偏移，不修改原始输入。",
        ),
        field(
            "peaks",
            "峰位注释",
            "table",
            table_schema=[
                {"name": "x", "display_name": "峰位置", "type": "float"},
                {"name": "label", "display_name": "注释", "type": "str"},
            ],
            info="可选，每行填写有限峰位置及注释；峰位须在测量范围内，箭头位于第一条显示曲线上。不自动寻峰。",
        ),
        *_figure_fields(),
    ],
    "viz.mechanics": [
        field(
            "method",
            "力学曲线图型",
            "choice",
            default="overlay",
            choices=["overlay", "mean_error"],
            info="overlay 显示各试样；mean_error 按独立试样计算均值及误差带，每组至少两条试样曲线。",
        ),
        field(
            "x",
            "应变列",
            default="strain",
            required=True,
            info="每条试样曲线至少两个点，保持采集次序且应变严格递增；请先截取单调加载段。",
        ),
        field(
            "y",
            "应力列",
            default="stress",
            required=True,
            info="填写实际数值列名；先在上游统一试样间的应力及应变单位。图件不会换算数值。",
        ),
        field(
            "sample",
            "独立试样标识列",
            default="sample_id",
            required=True,
            info="每个独立试样使用不同标识，不得缺失；同一个试样内重复测量点不作为独立样本。",
        ),
        field(
            "group", "试样分组列", info="可选；每个试样只能属于一个组，分组标识不得缺失。留空按全部试样汇总。"
        ),
        field(
            "error",
            "试样间误差带",
            "choice",
            default="std",
            choices=["std", "sem", "ci95"],
            when={"method": ["mean_error"]},
            info="std 样本标准差；sem 均值标准误；ci95 逐点 Student t 95% 置信区间，不是同时置信带。",
        ),
        field(
            "grid",
            "显式插值应变网格",
            "list",
            when={"method": ["mean_error"]},
            info="可选数值列表；不同试样采样点不一致时必须填写。至少两点、有限且严格递增，完全位于所有试样共同范围内，禁止外推。",
        ),
        *_figure_fields(),
    ],
    "viz.statistics": [
        field(
            "method",
            "统计诊断图型",
            "choice",
            default="histogram",
            choices=["histogram", "correlation", "residual", "prediction"],
            info="histogram 直方图；correlation 相关矩阵；residual 实测减预测；"
            "prediction 实测对预测及恒等线。",
        ),
        field(
            "column",
            "直方图数值列",
            default="value",
            required=True,
            when={"method": ["histogram"]},
            info="填写实际有限数值列名；直方图保留全部输入观测。",
        ),
        field(
            "bins",
            "直方图分箱",
            default="auto",
            converter="histogram_bins",
            when={"method": ["histogram"]},
            info="填正整数箱数，或 auto、fd、doane、scott、stone、rice、sturges、sqrt 自动规则；"
            "范围限制请先在上游筛选。",
        ),
        field(
            "columns",
            "相关矩阵数值列",
            "list",
            required=True,
            when={"method": ["correlation"]},
            info="填写实际数值列名列表；至少三个观测，各列均须有变化且无非有限值。",
        ),
        field(
            "correlation_method",
            "相关系数",
            "choice",
            default="pearson",
            choices=["pearson", "spearman", "kendall"],
            when={"method": ["correlation"]},
            info="分别为 Pearson 线性相关、Spearman 秩相关及 Kendall 秩相关；相关不证明因果。",
        ),
        field(
            "y_true",
            "实测值列",
            default="y_true",
            required=True,
            when={"method": ["residual", "prediction"]},
            info="填写实际数值列名；实测与预测必须声明一致单位，数值换算请在上游完成。",
        ),
        field(
            "y_pred",
            "预测值列",
            default="y_pred",
            required=True,
            when={"method": ["residual", "prediction"]},
            info="填写实际数值列名；残差定义为实测 − 预测。请使用独立验证或留出集预测评价模型。",
        ),
        *_figure_fields(),
    ],
    "export.table": [
        field(
            "format",
            "结果表格式",
            "choice",
            default="csv",
            choices=["csv", "excel"],
            info="CSV 使用 UTF-8 BOM；Excel 输出 .xlsx 并带 Metadata 工作表。文件写出后会回读核查。",
        ),
        field(
            "filename",
            "导出文件名",
            info="可选简单文件名；CSV 须以 .csv 结尾，Excel 须以 .xlsx 结尾。留空自动选择 results.csv/xlsx。",
        ),
        field(
            "output_dir",
            "导出目录",
            info="留空创建临时目录；始终避免覆盖同名文件，同时输出带哈希和类型信息的 metadata.json。",
        ),
        field(
            "id_columns",
            "样品标识列",
            "list",
            info="填写实际标识列名列表，回读时按字符串核对；"
            "Excel 不保证超过 15 位整数精度，应先转为文本或使用 CSV。",
        ),
        field(
            "units",
            "列单位",
            "dict",
            info="键填实际列名，值填单位；与上游单位元数据核对。"
            "重开 CSV 时请配套使用元数据以恢复标识类型和单位。",
        ),
    ],
    "export.report": [
        field(
            "format",
            "报告格式",
            "choice",
            default="html",
            choices=["html", "markdown"],
            info="HTML 或 Markdown 报告；图片嵌入为 PNG，源图哈希及嵌入尺寸会核查。",
        ),
        field(
            "title",
            "报告标题",
            default="Materials analysis report",
            info="上游 Data.title 优先；连接结果上下文以提供 "
            "sources、parameters、results、warnings、figures。",
        ),
        field(
            "filename",
            "报告文件名",
            info="可选简单文件名；HTML 须为 .html，Markdown 须为 .md；留空自动使用 analysis-report.html/md。",
        ),
        field(
            "output_dir",
            "报告输出目录",
            info="留空创建临时目录；始终避免覆盖同名文件。可连接一张结果表；"
            "报告本身只输出 Data 和附件，不输出表。",
        ),
    ],
}


CONTRACTS = {
    "viz.performance": {
        "table_output": False,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "ChartScatter",
    },
    "viz.spectra": {"table_output": False, "artifacts_output": True, "upload_types": [], "icon": "Waves"},
    "viz.mechanics": {
        "table_output": False,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "Activity",
    },
    "viz.statistics": {
        "table_output": False,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "ChartColumnIncreasing",
    },
    "export.table": {
        "table_output": True,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "FileSpreadsheet",
    },
    "export.report": {
        "table_output": False,
        "artifacts_output": True,
        "upload_types": [],
        "icon": "FileText",
    },
}

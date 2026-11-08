"""Native file, database, OCR and calibrated extraction forms; no engine imports."""

from .ui_types import field

_RASTER_TYPES = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp", "gif"]
_TABLE_TYPES = ["csv", "tsv", "txt", "dat", "lis", "xlsx", "xls", "xlsm", "ods"]
_INSTRUMENT_TYPES = ["xy", "xye", "csv", "txt", "dat", "jdx", "dx", "jcamp", "brml", "raw"]


def _schema(*columns):
    return [
        {"name": name, "display_name": label, "type": kind, "description": label, "edit_mode": "inline"}
        for name, label, kind in columns
    ]


def _path(when=None):
    return field(
        "path",
        "本地文件路径",
        when=when,
        info="可上传文件、填写现有文件的绝对路径，或连接上游 Data.file_path；源文件保持不变。",
    )


def _encoding(when=None):
    return field(
        "encoding",
        "文本编码",
        "choice",
        default="auto",
        when=when,
        choices=["auto", "utf-8", "utf-8-sig", "gb18030", "gbk", "utf-16", "cp1252", "latin-1"],
        info="auto 依次检查 BOM、UTF-8、GB18030；识别失败时选择源文件实际编码。",
    )


def _table_fields(when=None, *, include_encoding=True):
    controls = [
        field(
            "sheet",
            "Excel 工作表名称或序号",
            default="0",
            converter="number_or_text",
            when=when,
            info="Excel/ODS 使用名称或从 0 开始的工作表序号；CSV/TSV 忽略此项。",
        ),
        field(
            "header",
            "表头行号 / null 无表头",
            default="0",
            converter="nullable_int",
            when=when,
            info="从 0 开始，且相对于所选矩形区域；输入 null 表示无表头，再用列名列表命名。",
        ),
        field(
            "delimiter",
            "文本分隔符",
            default="auto",
            when=when,
            info="auto 自动识别；手填一个实际字符，如逗号、分号、竖线或实际制表符；Excel 忽略。",
        ),
        field(
            "decimal_separator",
            "小数分隔符",
            "choice",
            default=".",
            when=when,
            choices=[".", ","],
            info="文本表格按来源明确选择小数点或小数逗号；逗号小数仅在整列均为数值格式时转换。",
        ),
        field(
            "range",
            "读取矩形区域",
            when=when,
            info="可留空读取全表；用 A2:C20 形式选取原始单元格矩形，表头行号相对于此区域。",
        ),
        field(
            "names",
            "无表头时的列名",
            "list",
            when=when,
            info=(
                "仅 header=null 时使用；留空按选中区域列数自动命名。非空列表数量须与列数一致；"
                "空名称和重复名称会生成唯一名称并保留全部数据列。"
            ),
        ),
        field(
            "id_columns",
            "保留为文本的标识符列",
            "list",
            when=when,
            info="填写实际列名；保留样本编号、前导零及超长整数，避免数值推断破坏标识符。",
        ),
        field(
            "dtype",
            "列类型映射",
            "dict",
            when=when,
            info="列名到 pandas 类型，如 sample_id:string、count:Int64、value:float64；标识符须为文本。",
        ),
    ]
    return ([_encoding(when)] if include_encoding else []) + controls


def _output(when=None):
    return [
        field(
            "output_dir",
            "附件输出目录",
            when=when,
            info="留空使用独立临时目录；填写绝对路径可集中保存渲染页或转换结果。",
        ),
        field(
            "overwrite",
            "允许覆盖同名输出",
            "bool",
            default=False,
            when=when,
            info="默认遇同名文件生成新名称；原始输入文件始终受保护。",
        ),
    ]


def _pdf_fields():
    return [
        _path(),
        field(
            "pages",
            "页码列表",
            "list",
            converter="int_list",
            info="留空处理全部页面；页码从 1 开始，例如 1、3、5，不使用 0 起始索引。",
        ),
        field(
            "dpi",
            "OCR / 渲染分辨率",
            "int",
            default=150,
            info="36 至 1200 DPI；更高分辨率可改善小字识别，也增加运行时间和附件体积。",
        ),
    ]


def _ocr_fields(when=None):
    return [
        field(
            "text_score",
            "文字识别置信度阈值",
            "float",
            default=0.5,
            when=when,
            info="0 到 1；只保留达到阈值的真实识别结果，空结果会保留为空表。",
        ),
        field(
            "box_thresh",
            "文字检测框阈值",
            "float",
            default=0.5,
            when=when,
            info="传给 RapidOCR 的检测框阈值，建议 0 到 1；阈值升高会减少低置信度区域。",
        ),
        field(
            "ocr_config_path",
            "RapidOCR 模型配置路径",
            advanced=True,
            when=when,
            info="可选的现有 RapidOCR 配置文件；留空使用已安装的本地 ONNX 模型。",
        ),
    ]


def _region(*, pdf=False, when=None):
    unit = "PDF 点（1/72 英寸，可为小数）" if pdf else "原图整数像素"
    return field(
        "region",
        "提取矩形区域",
        "list",
        when=when,
        converter="float_list" if pdf else "int_list",
        info=f"可留空处理全图/全页；依次填写 left、top、right、bottom，单位为{unit}；右下界大于左上界。",
    )


def _grid_fields(when=None):
    return [
        field(
            "x_lines",
            "手动纵向网格线坐标",
            "list",
            converter="int_list",
            when=when,
            info="可留空自动检测；手动时须同时填 y_lines，至少两个严格递增的原图像素坐标。",
        ),
        field(
            "y_lines",
            "手动横向网格线坐标",
            "list",
            converter="int_list",
            when=when,
            info="须与 x_lines 同时填写；坐标位于所选区域内，末线严格小于区域右/下边界。",
        ),
        field(
            "line_threshold",
            "网格线灰度阈值",
            "int",
            default=180,
            when=when,
            info="0 到 255；仅用于自动检测有线表格的深色网格，不推断无框表格。",
        ),
        field(
            "min_table_width",
            "最小表格宽度（像素）",
            "int",
            default=40,
            when=when,
            info="自动网格检测的最小区域宽度；过小区域会被忽略。",
        ),
        field(
            "min_table_height",
            "最小表格高度（像素）",
            "int",
            default=30,
            when=when,
            info="自动网格检测的最小区域高度；没有网格时返回真实空表及提示。",
        ),
    ]


SPECS = {
    "io.table_import": [
        _path(),
        *[
            {
                **control,
                **({"kind": "choice", "choices": [], "combobox": True} if control["path"] == "sheet" else {}),
            }
            for control in _table_fields()
        ],
    ],
    "io.text_import": [
        _path(),
        field(
            "method",
            "文本解析方式",
            "choice",
            default="lines",
            choices=["lines", "delimited", "fixed_width"],
            info="lines 保留行号和原文；delimited 解析分隔表；fixed_width 按每列字符宽度解析。",
        ),
        _encoding(),
        *[
            control
            for control in _table_fields({"method": ["delimited"]}, include_encoding=False)
            if control["path"] not in {"sheet", "names", "dtype"}
        ],
        field(
            "names",
            "列名列表",
            "list",
            when={"method": ["delimited", "fixed_width"]},
            info="固定宽度时数量须等于 widths；分隔模式仅 header=null 时使用；列名须唯一。",
        ),
        field(
            "dtype",
            "列类型映射",
            "dict",
            when={"method": ["delimited", "fixed_width"]},
            info="可选列名到 pandas 类型映射，如 sample_id:string；固定宽度解析时直接交给 pandas。",
        ),
        field(
            "widths",
            "各列字符宽度",
            "list",
            converter="int_list",
            required=True,
            when={"method": ["fixed_width"]},
            info="按列顺序填写正整数宽度，例如 8、12、10。",
        ),
        field(
            "skiprows",
            "跳过开头行数",
            "int",
            default=0,
            when={"method": ["fixed_width"]},
            info="固定宽度模式读取前跳过的行数，从 0 开始；这些行不会作为数据。",
        ),
    ],
    "io.pdf_import": [
        *_pdf_fields(),
        field(
            "render_all",
            "渲染全部所选页面",
            "bool",
            default=False,
            info="默认只渲染没有原生文字的页面；打开后每页生成 PNG 附件。此节点输出页面信息而非表格。",
        ),
        *_output(),
    ],
    "io.image_import": [_path()],
    "io.instrument_import": [
        _path(),
        field(
            "format",
            "仪器数据格式",
            "choice",
            choices=[
                "xy",
                "xye",
                "csv",
                "txt",
                "dat",
                "jdx",
                "dx",
                "jcamp",
                "brml",
                "raw",
                "h5",
                "hdf5",
                "nc",
                "netcdf",
                "zarr",
            ],
            info="留空按扩展名识别；XY 须是无文字表头的数值行，JCAMP 只直接支持未压缩数据。"
            "BRML 请显式选择格式并填写通道，RAW 须另配插件/转换器。",
        ),
        _encoding(),
        field(
            "mode",
            "数组读取模式",
            "choice",
            default="read",
            choices=["read", "browse"],
            info="HDF5/NetCDF/Zarr 可先 browse 查看实际路径、维度、类型和属性，"
            "再 read 明确选择数组；其他格式用 read。",
        ),
        field(
            "dataset_path",
            "信号数据集路径",
            "choice",
            choices=[],
            combobox=True,
            info="从 browse 结果复制实际路径，如 /measurement/intensity；不自动选择或合并数据集。",
        ),
        field(
            "x_axis_path",
            "光谱坐标轴路径",
            "choice",
            choices=[],
            combobox=True,
            info="明确选择一维坐标数组路径；长度须匹配指定光谱轴，不自动猜测坐标。",
        ),
        field(
            "group_axis_path",
            "逐曲线标识轴路径",
            "choice",
            choices=[],
            combobox=True,
            info="二维信号必须选择另一维对应的一维唯一曲线标识；输出 curve_id 保留前导零。",
        ),
        field(
            "spectrum_axis",
            "二维数组的光谱轴索引",
            "int",
            default=None,
            info="二维数据必须显式启用并填写 0 或 1；不会按数组长度自动转置。一维数据不需要。",
        ),
        field(
            "background_path",
            "背景数据集路径",
            "choice",
            choices=[],
            combobox=True,
            info="可选一维背景或与信号同形数组；只在明确指定后执行 signal-background。",
        ),
        field(
            "reference_path",
            "参考数据集路径",
            "choice",
            choices=[],
            combobox=True,
            info="可选一维参考或同形数组；按 (signal-background)/(reference-background) 计算，"
            "非正分母标记缺失。",
        ),
        field(
            "reference_floor",
            "最小有效参考分母",
            "float",
            default=0.0,
            advanced=True,
            info="强度单位下的非负阈值；参考减背景小于等于该值的通道标记无效，不返回无穷大。",
        ),
        field(
            "noise_range",
            "声明的噪声坐标区间",
            "range",
            advanced=True,
            info="可选源坐标单位下的区间，至少两个观测点；SNR=最大绝对信号/该区间样本标准差，区间内真实峰会造成偏差。",
        ),
        field(
            "decode_cf",
            "解码 NetCDF 缺失值与缩放属性",
            "bool",
            default=True,
            advanced=True,
            info="NetCDF 使用 _FillValue/missing_value 和 scale_factor/add_offset；"
            "关闭时保留未缩放数值并仍标记缺失。",
        ),
        field(
            "max_rows",
            "数组最多输出测量点数",
            "int",
            default=2_000_000,
            advanced=True,
            info="读取数组前检查元素数；超限拒绝，需先在仪器软件或可信本地工具中导出子集。",
        ),
        field(
            "max_bytes",
            "数组与输出估算内存上限（字节）",
            "int",
            default=268_435_456,
            advanced=True,
            info="在数组分配和解压前检查数组、块及长表估算大小；默认 256 MiB。",
        ),
        field(
            "max_nodes",
            "数组树最多节点数",
            "int",
            default=2000,
            advanced=True,
            info="仅浏览有限数量的本地组和数据集；超限明确报错，不静默省略剩余节点。",
        ),
        field(
            "x_index",
            "BRML 横坐标通道索引",
            "int",
            required=True,
            when={"format": ["brml"]},
            info="从 0 开始，须根据该仪器 Datum 格式明确指定，系统不猜测通道顺序。",
        ),
        field(
            "y_index",
            "BRML 信号通道索引",
            "int",
            required=True,
            when={"format": ["brml"]},
            info="从 0 开始，须为非负整数且小于 Datum 通道数量。",
        ),
        field(
            "plugin",
            "仪器解析插件",
            advanced=True,
            info="可选 module:function；插件优先于外部转换命令，接收隔离副本并返回表格或独立转换文件。",
        ),
        field(
            "converter",
            "外部转换命令参数",
            "list",
            advanced=True,
            info="每项一个命令参数，必须同时包含 {input} 与 {output}；"
            "不使用 shell 语法，输入在隔离副本中处理。",
        ),
        field(
            "timeout",
            "转换命令超时（秒）",
            "float",
            default=60.0,
            advanced=True,
            info="仅外部 converter 命令使用；命令须生成新的 CSV 输出文件。",
        ),
        *_output(),
    ],
    "io.database_import": [
        field(
            "method",
            "数据接入方式",
            "choice",
            default="sqlite",
            choices=["sqlite", "sqlalchemy", "rest"],
            info="SQLite 和 SQLAlchemy 仅执行只读查询；REST 读取 JSON 对象列表并可分页。",
        ),
        _path({"method": ["sqlite"]}),
        field(
            "query",
            "只读 SQL 查询",
            default="SELECT * FROM samples",
            when={"method": ["sqlite", "sqlalchemy"]},
            required=True,
            info="仅允许单条 SELECT 或 WITH 查询；拒绝写入、扩展加载、文件导出及不支持只读事务的数据库。",
        ),
        field(
            "parameters",
            "SQL 绑定参数",
            "dict",
            when={"method": ["sqlite", "sqlalchemy"]},
            info="参数名到值的映射，对应查询中的 :参数名；使用只读账户连接远程数据库。",
        ),
        field(
            "url",
            "数据库连接串 / REST URL",
            when={"method": ["sqlalchemy", "rest"]},
            required=True,
            info="SQLAlchemy 使用数据库连接 URL；REST 使用 HTTP(S) URL，"
            "认证信息放入 headers，不嵌入 REST URL。",
        ),
        field(
            "fields",
            "输出字段列表",
            "list",
            info="留空保留全部字段；SQL 用结果列名，REST 支持嵌套字段路径，如 sample.id。",
        ),
        field(
            "params",
            "REST 查询参数",
            "dict",
            when={"method": ["rest"]},
            info="附加到 URL 的参数名和值；分页字段由下方分页配置写入。",
        ),
        field(
            "headers",
            "REST 请求头",
            "dict",
            advanced=True,
            when={"method": ["rest"]},
            info="可选请求头；凭据会随保存的配置传递，请使用测试或受限凭据并依照本地密钥管理策略。",
        ),
        field(
            "records_path",
            "REST 记录列表路径",
            when={"method": ["rest"]},
            info="留空表示响应本身是对象列表；否则填写 data.items 等点分隔路径，结果须为字典列表。",
        ),
        field(
            "timeout",
            "REST 超时（秒）",
            "float",
            default=20.0,
            when={"method": ["rest"]},
            info="单次 REST 请求超时；跨来源重定向和跨来源下一页链接会被拒绝。",
        ),
        field(
            "pagination.mode",
            "REST 分页方式",
            "choice",
            default="page",
            choices=["page", "offset", "next", "none"],
            when={"method": ["rest"]},
            info="page 使用页码；offset 使用偏移；next 读取响应链接；none 只请求一次。",
        ),
        field(
            "pagination.max_pages",
            "最大读取页数",
            "int",
            default=100,
            when={"method": ["rest"]},
            info="须大于 0；达到上限但尚未结束时标注结果不完整，不宣称完整下载。",
        ),
        field(
            "pagination.page_size",
            "每页记录数",
            "int",
            default=100,
            when={"method": ["rest"], "pagination.mode": ["page", "offset"]},
            info="须大于 0；传给页大小参数，服务端实际返回数量可能不同。",
        ),
        field(
            "pagination.start",
            "起始页码 / 偏移",
            "int",
            when={"method": ["rest"], "pagination.mode": ["page", "offset"]},
            info="留空时 page 从 1、offset 从 0 开始；按服务 API 约定填写。",
        ),
        field(
            "pagination.page_param",
            "页码参数名",
            default="page",
            when={"method": ["rest"], "pagination.mode": ["page"]},
            info="分页 URL 中的页码参数名。",
        ),
        field(
            "pagination.offset_param",
            "偏移参数名",
            default="offset",
            when={"method": ["rest"], "pagination.mode": ["offset"]},
            info="分页 URL 中的起始记录偏移参数名。",
        ),
        field(
            "pagination.size_param",
            "每页数量参数名",
            when={"method": ["rest"], "pagination.mode": ["page", "offset"]},
            info="留空时 page 使用 page_size，offset 使用 limit；也可按接口文档填写。",
        ),
        field(
            "pagination.next_path",
            "下一页链接字段",
            default="next",
            when={"method": ["rest"], "pagination.mode": ["next"]},
            info="响应中下一页链接的点分隔路径，链接为空时结束，下一页必须保持同一来源。",
        ),
    ],
    "extract.pdf_text": [
        *_pdf_fields(),
        field(
            "method",
            "PDF 文字提取方式",
            "choice",
            default="auto",
            choices=["auto", "native", "ocr"],
            info="auto 优先原生文字，仅扫描页使用 OCR；native 只取原文；ocr 强制渲染并识别。",
        ),
        *_ocr_fields({"method": ["auto", "ocr"]}),
        *_output(),
    ],
    "extract.pdf_tables": [
        *_pdf_fields(),
        field(
            "method",
            "PDF 表格提取方式",
            "choice",
            default="auto",
            choices=["auto", "lines", "text", "ocr"],
            info="auto 先网格线、再文字对齐，未检出时使用 OCR；OCR 表格须有可识别的网格线。",
        ),
        field(
            "header",
            "将第一行作为列名",
            "bool",
            default=True,
            info="关闭后自动生成列名并保留首行数据；重复印刷表头会被区分命名。",
        ),
        _region(pdf=True),
        field(
            "min_words_vertical",
            "文字对齐最少词数",
            "int",
            default=3,
            when={"method": ["auto", "text"]},
            info="原生文字对齐策略用于识别纵向表格结构的最少词数。",
        ),
        *_ocr_fields({"method": ["auto", "ocr"]}),
        *_grid_fields({"method": ["auto", "ocr"]}),
        *_output(),
    ],
    "extract.image_ocr": [
        _path(),
        field(
            "regions",
            "识别区域列表",
            "table",
            converter="rectangles",
            table_schema=_schema(
                ("left", "左", "int"), ("top", "上", "int"), ("right", "右", "int"), ("bottom", "下", "int")
            ),
            info="留空自动检测全图；每行一个原图整数像素矩形 left/top/right/bottom，须处于图像范围内。",
        ),
        *_ocr_fields(),
    ],
    "extract.image_tables": [
        _path(),
        _region(),
        field(
            "header",
            "将第一行作为列名",
            "bool",
            default=True,
            info="有网格表格逐单元格 OCR；关闭后生成列名并保留第一行数据。",
        ),
        *_grid_fields(),
        *_ocr_fields(),
    ],
    "extract.chart_digitize": [
        _path(),
        *[
            field(
                f"calibration.{axis}",
                f"{axis.upper()} 轴两点标定",
                "table",
                required=True,
                converter="pairs",
                pair_columns=["pixel", "value"],
                table_schema=_schema(("pixel", "原图像素位置", "float"), ("value", "实际坐标值", "float")),
                info="恰好两行，填写原图上的像素坐标与对应实际值；两像素及两实际值均须不同且有限。",
            )
            for axis in ("x", "y")
        ],
        *[
            field(
                f"calibration.{axis}_scale",
                f"{axis.upper()} 轴刻度",
                "choice",
                default="linear",
                choices=["linear", "log"],
                info="linear 为线性轴；log 为十进对数轴，两个实际标定值必须为正。",
            )
            for axis in ("x", "y")
        ],
        field(
            "color",
            "曲线 RGB 颜色",
            "list",
            default=[255, 0, 0],
            converter="int_list",
            required=True,
            info="依次填写红、绿、蓝三个 0 到 255 的整数，例如 255、0、0 表示红色。",
        ),
        field(
            "color_tolerance",
            "颜色欧氏距离容差",
            "float",
            default=40.0,
            info="非负有限值；选择与 RGB 目标颜色距离不大于此值的像素。",
        ),
        _region(),
        field(
            "pixel_step",
            "横向采样步长（像素）",
            "int",
            default=1,
            info="正整数；每隔这些像素取一列，以匹配像素的纵坐标中位数定位曲线。",
        ),
        field(
            "max_thickness",
            "厚度警告阈值（像素）",
            "float",
            default=10.0,
            info="同一横向位置命中像素的纵向跨度大于此值时警告；多曲线/标记可能混入结果。",
        ),
    ],
    "extract.convert_file": [
        _path(),
        field(
            "target",
            "目标文件格式",
            "choice",
            default="csv",
            choices=["csv", "txt", "png"],
            info="CSV 输出提取表格；TXT 输出文字或制表分隔表；"
            "PNG 渲染 PDF 页面、转换图片或绘制输入表。PNG 模式只暴露附件输出。",
        ),
        field(
            "filename",
            "输出文件名",
            info="可留空使用 converted.目标扩展名；手填须为无目录的文件名，扩展名须与目标格式一致。",
        ),
        field(
            "method",
            "源文件解析方式",
            "choice",
            choices=["auto", "lines", "text", "native", "ocr", "delimited", "fixed_width"],
            info="留空按源格式默认解析；PDF→CSV 选 auto/lines/text/ocr，"
            "PDF→TXT 选 auto/native/ocr，TXT 可选 lines/fixed_width。",
        ),
        _encoding(),
        field(
            "sheet",
            "源 Excel 工作表",
            default="0",
            converter="number_or_text",
            info="Excel/ODS 的名称或从 0 开始的序号；其他来源忽略。",
        ),
        field(
            "delimiter",
            "源文本分隔符",
            default="auto",
            info="分隔表使用 auto 或一个实际分隔字符；PDF、图片和数值仪器文件忽略。",
        ),
        field("range", "源表格读取区域", info="表格来源可选 A2:C20 矩形；不会用于 PDF/图片裁剪。"),
        field(
            "widths",
            "定宽文本各列宽度",
            "list",
            converter="int_list",
            required=True,
            when={"method": ["fixed_width"]},
            info="仅 TXT 定宽解析使用，按顺序填写各列正整数字符宽度。",
        ),
        field(
            "names",
            "定宽文本列名",
            "list",
            when={"method": ["fixed_width"]},
            info="可留空自动命名；手填须唯一且与宽度数量一致。",
        ),
        field(
            "pages",
            "PDF 页码列表",
            "list",
            converter="int_list",
            info="仅 PDF 来源使用；从 1 开始，留空转换全部页面。",
        ),
        field(
            "dpi",
            "PDF 渲染分辨率",
            "int",
            default=150,
            info="36 至 1200 DPI；扫描页文字/表格 OCR 和 PDF→PNG 使用。",
        ),
        *_ocr_fields(),
        *_output(),
    ],
}


def _contract(table, artifacts, uploads, icon, **extra):
    return {
        "table_output": table,
        "artifacts_output": artifacts,
        "upload_types": list(uploads),
        "icon": icon,
        **extra,
    }


CONTRACTS = {
    "io.table_import": _contract(True, False, _TABLE_TYPES, "FileSpreadsheet"),
    "io.text_import": _contract(True, False, ["txt", "csv", "tsv", "dat", "log"], "FileText"),
    "io.pdf_import": _contract(False, True, ["pdf"], "FileText"),
    "io.image_import": _contract(False, False, _RASTER_TYPES, "Image"),
    "io.instrument_import": _contract(
        True, True, [*_INSTRUMENT_TYPES, "h5", "hdf5", "nc", "netcdf", "nc4"], "Activity"
    ),
    "io.database_import": _contract(True, False, ["db", "sqlite", "sqlite3"], "Database"),
    "extract.pdf_text": _contract(True, True, ["pdf"], "ScanText"),
    "extract.pdf_tables": _contract(True, True, ["pdf"], "Table"),
    "extract.image_ocr": _contract(True, False, _RASTER_TYPES, "ScanText"),
    "extract.image_tables": _contract(True, False, _RASTER_TYPES, "Table"),
    "extract.chart_digitize": _contract(True, False, _RASTER_TYPES, "ChartLine"),
    # Raster/PDF -> PNG returns no frame. CSV/TXT always return genuine tables;
    # PNG's occasional source frame remains available at its upstream reader.
    "extract.convert_file": _contract(
        True,
        True,
        list(dict.fromkeys(["pdf", *_TABLE_TYPES, *_RASTER_TYPES[:-1], *_INSTRUMENT_TYPES])),
        "FileOutput",
        method_path="target",
        table_methods=["csv", "txt"],
    ),
}

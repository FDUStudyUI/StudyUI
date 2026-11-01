# 数据接入与内容提取

表格导入默认保留 `001`、`01` 等文本编号以及 Excel 中的字面值 `NA`；
可用 `id_columns:["sample_id"]` 和 `dtype:{"batch":"string"}` 明确声明字段。
导入报告的 `schema` 记录类型和决策。大整数不会经浮点数静默舍入。

这里实现《材料科学节点与方法》第 1、2 类的 12 个独立节点。核心函数统一返回 `NodeResult(table, data, artifacts, warnings)`；`config.path` 或上游 `data.file_path` 指定原始文件。页码从 1 开始，表头行和数组索引从 0 开始，图片位置单位为像素，PDF 位置单位为点（1/72 英寸）。所有示例数据均为 **SYNTHETIC 合成数据**。

## 新手运行

先在材料节点包目录安装 `python -m pip install ".[science,dev]"`。启用虚拟环境后执行：

```powershell
$env:PYTHONUTF8 = '1'
python examples/science/io/build_fixtures.py
python examples/science/io/run_examples.py --output-dir artifacts/io-demo
python -m pytest tests/test_science_io.py tests/test_science_extract.py -q --basetemp artifacts/pytest-io-local
```

`artifacts` 目录应已存在，或先运行 `New-Item -ItemType Directory -Force artifacts`。普通任务使用[表单控件](node-usability.md)。高级 `json` 模式可参考 `examples/science/io/configs.json`，将其中的文件路径改成本机绝对路径；截图坐标和坐标轴标定必须对应自己的原图。CSV、Excel 和原始图片不会被结果覆盖；即使 `overwrite=true`，与当前原始输入路径冲突时也会另建文件名。

## 方法、配置与验证

测试文件简称 IO=`tests/test_science_io.py`，EX=`tests/test_science_extract.py`。

| 节点及全部原文子方法 | 配置与真实实现 | 主要验收测试 |
| --- | --- | --- |
| `io.table_import`：识别编码、分隔符；工作表、表头行、数据区域 | 文本支持 UTF-8/BOM、UTF-16/BOM、GB18030，其他编码由 charset-normalizer 候选推断，支持显式 `encoding`；`delimiter=auto` 用 CSV Sniffer；`sheet` 名称/索引，`range=A2:C20`，范围选择后 `header=0`，`header=null` 表示无表头 | IO `test_csv_encoding_delimiter_header_and_range`、`test_excel_sheet_header_range` |
| `io.text_import`：识别编码；按行、分隔符、固定宽度 | `method=lines/delimited/fixed_width`；逐行返回 `line_number`；固定宽度明确 `widths`、`names`，可给 `skiprows`；不会将错误宽度伪装成成功 | IO `test_text_parsers` 3 路、`test_invalid_parser_configuration_rejected` |
| `io.pdf_import`：原生文本；扫描件转图片交给 OCR | PyMuPDF 提取排序文本、块内容及 bbox；无原生文本的页按 `dpi` 渲染 PNG 并记录 `requires_ocr`；`render_all=true` 强制渲染全部选择页；`pages=[1,3]` | IO `test_pdf_import_native_and_scanned_page_artifact`，EX 扫描件回退测试 |
| `io.image_import`：格式、尺寸、分辨率、元数据 | Pillow 真解码，返回格式、像素宽高、模式、DPI（不存在时为 null）、帧数、EXIF 与图片 info | IO `test_image_metadata_and_upstream_path` |
| `io.instrument_import`：原始格式；转换器或插件 | 数字 XY/XYE/DAT/TXT/CSV；未压缩 JCAMP XY 对/增量 Y；BRML ZIP RawData XML `Datum`，显式 `x_index/y_index`；其他厂商二进制使用可信 `module:function` 插件或命令 token 列表 `converter`，命令中必须含 `{input}`、`{output}`，输出 CSV。插件/转换器拿到临时输入副本，避免其原地编辑损伤原件 | IO `test_instrument_xy_and_jcamp` 3 路、`test_brml_xml_raw_points`、`test_unsupported_binary_requires_plugin_and_executes_explicit_converter`、两项输入隔离测试 |
| `io.database_import`：SQL；REST 分页；字段筛选 | `method=sqlite/sqlalchemy/rest`；SQL 参数化 `query/parameters`，只读 SQLite URI+`query_only`；SQLAlchemy SQLite 只读 URI，PostgreSQL/MySQL/MariaDB 只读事务；`fields` 选列。REST：`url/records_path/headers/params`，点分字段；`pagination.mode=page/offset/next/none`，页码、偏移、next 字段名可配；最大页数截断明确警告 | IO `test_database_readonly_query_field_selection` 2 路、本地 HTTP 服务分页及三种替代模式、截断测试 |
| `extract.pdf_text`：按页；段落与版面顺序 | `method=native/ocr/auto`；原生文本按页、位置排序，保留文本块与 bbox；扫描页使用 RapidOCR，字符/词框缩放回 PDF 点；保留每块 `method/confidence` | EX `test_pdf_text_page_order_locations_and_selection`、`test_scanned_pdf_text_and_table_ocr_fallback` |
| `extract.pdf_tables`：表格线；文本对齐；OCR | `method=lines/text/ocr/auto`；PyMuPDF `find_tables` 的线/文字对齐策略，返回每表页码、bbox、原始行与单元格位置；自动模式先线再文字，再栅格表格 OCR；`region` 是 PDF 点坐标 | EX `test_pdf_table_native_methods` 2 路、扫描件回退测试 |
| `extract.image_ocr`：OCR；版面区域；文字位置与内容 | 本地 RapidOCR ONNX 真实推理；自动文本检测区域（不虚构标题/图表等语义角色）或 `regions=[[x0,y0,x1,y1]]`；返回行框、字符/词 polygon、文本、置信度及坐标来源。词框直接来自引擎 CTC 对齐，不进行等宽伪造 | EX `test_actual_ocr_text_locations_confidence_and_region`、`test_blank_image_ocr_does_not_invent_success` |
| `extract.image_tables`：检测区域；切分单元格；识别内容 | OpenCV 形态学检测横竖表格线与连通表格区域，分割每个网格；单元格真实 OCR，并回映到原图 bbox；可显式 `region/x_lines/y_lines` 修正。`header=true/false` 处理首行 | EX `test_image_table_cell_segmentation_real_ocr`、PDF OCR 表格回退 |
| `extract.chart_digitize`：标定坐标；识别曲线；数字化 | 必填 `calibration.x/y=[[pixel,value],[pixel,value]]`，可用 `x_scale/y_scale=log`；RGB `color/color_tolerance` 识别指定曲线；`region/pixel_step` 控制区域/采样；每像素列取匹配曲线中位 y，并返回原始 pixel 坐标、匹配数量、厚度及歧义警告 | EX `test_calibrated_curve_digitization_known_pixels`、`test_logarithmic_calibration_and_region` |
| `extract.convert_file`：解析源格式；转 CSV、TXT、PNG | 根据原格式真正调用表格/仪器/PDF/图像解析器；CSV、UTF-8 TXT 或 Pillow PNG 输出。PDF→PNG 渲染各页；图像→PNG 保留解码像素；表→PNG 绘制表格。`target/filename/output_dir`，表输入可直接导出 | EX 三种格式读回、原文件冲突保护、带上游表时的原路径保护、PDF 文本/PNG、图片像素读回 |

## 高级 JSON 配置

文件导入：

```json
{"path":"C:/data/experiment.xlsx","sheet":"Experiment","range":"A2:D50","header":0}
```

每一个 `range` 都包含终止行列；`header` 相对于选中区域，而非整个工作表。例如 `A2:D50` 加 `header=0` 表示原工作表第 2 行是表头。自动编码识别具有歧义，检查中文和单位后可改为 `encoding=gb18030` 或原始设备记录的编码；不会声称能唯一识别所有编码。

只读数据库：

```json
{"method":"sqlite","path":"C:/data/experiment.sqlite","query":"SELECT sample,value FROM samples WHERE value > :threshold","parameters":{"threshold":10},"fields":["sample","value"]}
```

REST 示例先另开终端运行 `python examples/science/io/demo_rest.py`，再使用：

```json
{"method":"rest","url":"http://127.0.0.1:8766/","records_path":"items","fields":["sample","result.value"],"pagination":{"mode":"page","page_size":1,"max_pages":10}}
```

分页 `page_param/size_param/start` 控制页码接口；`offset_param/size_param/start` 控制偏移接口；next 接口设置 `next_path`（默认 `next`）。空数组、没有 next 链接或单次模式表示完成；达到 `max_pages` 则 `data.complete=false` 并警告。next 链接跨源会拒绝；凭据应由部署环境配置，不写进示例。

厂商转换插件（可信本地代码）：

```json
{"path":"examples/science/io/fixtures/vendor.raw","plugin":"examples.science.io.demo_plugin:convert"}
```

插件签名是 `convert(path: Path, config: dict) -> DataFrame | str | Path`。`path/config.path/config.file_path` 都指向临时输入副本；返回文件路径时必须是单独转换文件，框架会解析并保存最终 CSV。命令转换器用 `converter=["C:/vendor/converter.exe","{input}","{output}"]`；不通过 shell 执行，`timeout` 默认 60 秒。该接口运行用户安装的可信转换器，不具备恶意代码沙箱。压缩 JCAMP、未经适配的厂商 RAW、未知 BRML 通道顺序会明确要求配置或转换器。

曲线数字化：

```json
{"path":"examples/science/io/fixtures/curve.png","color":[255,0,0],"color_tolerance":5,"calibration":{"x":[[20,0],[120,10]],"y":[[120,0],[20,100]]}}
```

像素 y 方向向下，数值 y 方向由两个校准点决定。合成示例恢复 `y=10*x` 的 101 点。黑白图也可选黑色，但应通过 `region` 排除坐标轴和文字；同色多曲线、交叠、粗线、倾斜坐标轴需要更细选择或人工复核。本实现为标准二维直角坐标标定，不宣称支持透视畸变自动校正。

## 依赖与适用条件

- 表格需要 pandas/openpyxl；旧 XLS 使用 xlrd。ODS 需用户另外安装 pandas 的 odf 引擎；主要验收覆盖 CSV 和 XLSX。
- PDF 需要 PyMuPDF；OCR 需要 `rapidocr-onnxruntime==1.4.4`、ONNX Runtime、OpenCV，以及该包附带的检测/方向分类/识别 ONNX 模型。默认在本地 CPU 单线程推理；可用 `ocr_config_path` 指定其他本地模型配置。测试已实际执行模型推理，不用 OCR mock。网络服务和 API key 不是 OCR 运行条件。
- OCR 结果是待核查转录。低置信度、扫描噪声、合并单元格、无格线图片、复杂跨栏表格需要人工调整区域/网格或其他模型。未检测表格/文字时返回空结果与警告，不伪造单元格或文本。
- PDF 原生块排序尽量保留段落与位置；复杂多栏阅读顺序可能需要逐区域执行。PDF 表格原始 `rows/cells` 保留以便核查；多表列名不同会合并成并集，`data.tables` 保留每个表的独立结构。
- SQLAlchemy 实际本地 SQLite 已测；PostgreSQL/MySQL/MariaDB 路径执行真实只读事务，但需要对应驱动、服务器、凭据，尚未对外部生产服务器执行连通测试。其他方言明确拒绝，避免虚假只读保证。SQL 过滤保守，不接受多条语句或含写操作词的查询。
- REST 测试使用本地真实 HTTP 服务覆盖分页、偏移、next、单次及截断。未对任意公网服务保证兼容；接口字段名和认证由使用者明确提供。

原生图、独立 wheel 和网页验证见[0.3.0 整体验收](full-suite-acceptance.md)；
开发测试的历史记录见[验证归档](development/domain-validation.md)。

API 实现依据：[PyMuPDF Page API](https://pymupdf.readthedocs.io/en/latest/page.html)、[SQLite URI 只读模式](https://www.sqlite.org/uri.html)、[SQLAlchemy SQLite URI](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#uri-connections)、[RapidOCR 上游项目](https://github.com/RapidAI/RapidOCR)。本地直接检查 RapidOCR 1.4.4 的 `__call__`、`get_final_res`、`CalRecBoxes` 返回结构后实现字符/词框读取。

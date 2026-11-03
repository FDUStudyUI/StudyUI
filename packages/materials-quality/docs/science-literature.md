# 文献与知识检索：六个可组合节点

模块 `materials_quality.science.literature` 导出 `search / metadata / extract / compare / sources / summary`。
六个函数都接受 `table=None, *, config=None, data=None, tables=None`，返回共享 `NodeResult`。
`tables` 保留接口兼容性；本组节点使用单表或结构化数据，不消费多表端口。

## 先跑一个完整的本地例子

安装项目的 `science` 依赖后，在包目录执行：

```powershell
python examples/science/literature_workflow.py
```

例子使用明确标注的合成 ZnO 性能数据，无网络、无密钥、无付费调用。它依次执行检索、带证据抽取、单位对齐、冲突报告、来源 JSON 保存、检索式摘要，并读回文件验证 100 MPa 与 0.12 GPa 转换后的 100/120 MPa。输出在 `examples/science/literature_output`，原输入不修改。

## 输入与证据

```python
data = {'documents': [{'source_id': 'paper-a-page-2', 'text': 'ZnO strength is 100 MPa.',
                      'doi': '10.1234/example', 'page': 2, 'table_id': 'T1'}]}
```

也可接入 PDF 文本提取表，其 `text / page / source_file / bbox / confidence` 保留为证据位置。每个文本片段需要唯一 `source_id`；未提供时按输入顺序生成 `source-1` 等。不要把同篇论文多个页面赋予相同片段 ID。

抽取结果保存 `source_id / quote / span_start / span_end`，位置以原始 Python 字符串的 Unicode 字符计，起点包含、终点不包含。原有 DOI、页码、表号、图号、文件、URL、包围框及置信度继续保留。没有的位置字段保持缺失。`sources(data=extract_result.data)` 保存抽取片段及原文；输出 `data` 可继续连接 `summary`。

## 方法与参数

普通任务使用[原生表单](node-usability.md)。以下配置键供高级 JSON 或 Python API 使用。

| 节点 | 配置与行为 | 验证 |
| --- | --- | --- |
| `lit.search` | `provider=local/crossref`；`method=keyword/boolean/author/doi`；`query`。本地读取 `data.records` 或 `data.documents`；关键词为各词均出现，作者为无大小写子串。 | 本地关键词、作者、DOI、组合布尔及非法表达式；真实本地 HTTP 请求参数。 |
| `lit.metadata` | `provider=local/crossref`；`config.doi` 或文中 DOI。本地模式只读显式 `Title: / Authors: / Journal: / Year:` 行，作者以分号分隔；未知项为 `None`。Crossref 读取题名、作者、期刊、发表年份。 | 缺失不补造、DOI 规范化、真实 HTTP `/works/{doi}` 协议、公开 API 实测。 |
| `lit.extract` | `method=regex`，`patterns={性能名:表达式}`；命名组 `value/unit/material/preparation/test_condition`。数值转有限浮点，其他词保留。`method=lexicon`，`lexicon={字段名:[词,...]}`，按无大小写字面匹配。 | 数值/单位及原文跨度，字典命中证据，危险表达式拒绝。 |
| `lit.extract` | `method=table`；`delimiter` 单字符。解析带表头的 CSV/TSV 原文，保留每行原文证据、表号。需要每条记录占一条物理行；带换行的单元格明确拒绝。 | 合成 CSV 行、单元格和证据。 |
| `lit.extract` | `method=llm`；见下文。发送实际 OpenAI 兼容 Chat Completions JSON Schema 请求，验证每个声明的来源、原文、跨度、数值、单位和上下文字段。 | 真实本地 HTTP 服务验证请求、响应、凭据及失败情形；没有付费模型实测。 |
| `lit.compare` | 输入抽取表/`data.records`；必需 `material/preparation/test_condition/property/value/unit/source_id`。`target_units={指标:单位}` 通过 Pint 显式换算。`relative_tolerance` 控制报告不同值的相对阈值，默认 0。 | GPa→MPa、摄氏→开尔文、量纲不兼容拒绝、条件隔离、未知条件不强行对齐、输入不变。 |
| `lit.sources` | 保存 DOI、页码、表图编号、精确原文及跨度；`save=true` 写来源 JSON；`output_dir` 可指定，默认新临时目录，已存在文件默认换名。 | 抽取→注册→摘要及 JSON 文件读回。 |
| `lit.summary` | 必需 `question`；`top_k=1..100`。按问题词与原句的子串重叠数排序并保留跨度，默认 `method=extractive`，每点链接 DOI/URL/文件及页表图位置。`method=llm` 从已检索来源提取验证过的声明，再以原文证据构成摘要。 | 相关片段、无命中警告、小数保留、模型伪造来源拒绝。 |

布尔检索使用真正的递归下降解析器，优先级 `NOT > AND > OR`，支持括号和双引号短语；操作符用大写，必须显式写 AND/OR。不会执行 `eval`。本地集合执行完整布尔过滤。Crossref 原生接口是排序搜索，所以先取 `rows=1..1000` 条候选，再执行布尔过滤；**这不保证整个文献库的布尔召回率**，返回 `candidate_filtering=true` 和警告。负词也可能参与候选检索，因此不能把结果数量当作系统综述的全库计数。

正则使用 `regex` 包的每次匹配 0.2 秒超时，额外拒绝明显的嵌套重复；缺包时明确报错。字典为用户定义字面词典，不自动推断物相、材料同义词或化学实体身份。表格模式消费已提取的文本表；图像/PDF 表格检测由内容提取节点负责。

## 外部服务与模型凭据

[Crossref 官方 REST 文档](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) 列出公开 `/works` 和 `/works/{doi}`，无需账户。默认 `base_url=https://api.crossref.org`；`timeout` 默认 20 秒，最大 60 秒。真实公网 DOI 请求的独立记录在 `examples/science/literature_crossref_smoke.json`：2026-10-30 UTC 成功取得 `10.1038/nphys1170` 的元数据。网络健康会变化，该记录不属于离线 CI 成功保证。Crossref 不负责全文下载，也不覆盖全部 DOI 注册机构。

LLM 必须显式配置：

```python
config = {'method': 'llm', 'llm': {
    'url': 'https://your-provider.example/v1/chat/completions',
    'model': 'your-structured-output-model', 'api_key_env': 'LITERATURE_API_KEY', 'timeout': 30}}
```

将实际密钥放到对应环境变量。配置里的原始 `api_key / headers / authorization` 拒绝接受；结果、报告和异常不回传密钥。模型服务必须支持 `response_format.type=json_schema` 及严格 schema。缺凭据、网络失败、HTTP 错误、非 JSON 或声明未通过证据验证均报错。未使用付费服务测试；本地 `ThreadingHTTPServer` 实际验证了 HTTP JSON 请求与响应，以及未知来源、错误原文/跨度、无依据数值、虚构上下文字段、schema 错误、重定向和缺密钥拒绝。

LLM 的每个材料、制备和条件字段另附 `field_evidence`，各自定位到原文。验证仅说明字符串和数值有原文依据，不证明原文科学结论成立或数值与性能语义正确，仍需要研究者审核。摘要不接受模型自由写作的综述段落；只输出通过验证的原文要点与来源，避免把模型修辞变成无来源主张。

远程端点需要 HTTPS；HTTP 只允许 localhost/127.0.0.1/::1 以连接本地服务。HTTP 重定向一律拒绝，凭据不会跟随重定向转发。JSON 响应限制 10 MB。不会自动安装依赖、跟进登录或尝试其他付费服务。

## 边界与测试命令

比较按材料、制备、测试条件、指标和归一化单位分组，任一字段未知时单独成组。没有显式目标单位时保留原单位并分开比较，不按量纲猜测物理身份。不同值仅标记报告差异，不声称统计显著、实验冲突已解释或某篇论文错误。条件文字需要用户先做语义清洗，例如 `300 K` 与 `26.85 degC` 不自动判为同一测试条件。

摘要是透明的词匹配检索与原文摘录，不是向量语义检索；中文问题可使用原文出现的中文词片段，跨语言问题需要用户提供同语言关键词。输入须是可读文本；OCR 准确度取决于上游。图中曲线不能通过本节点凭空变成性能数值。

```powershell
python -m pytest tests/test_science_literature.py tests/test_science_literature_http.py --basetemp artifacts/pytest-literature -q
python -m ruff check src/materials_quality/science/literature.py src/materials_quality/science/lit_evidence.py tests/test_science_literature*.py
```

开发测试的历史记录见[验证归档](development/domain-validation.md)。

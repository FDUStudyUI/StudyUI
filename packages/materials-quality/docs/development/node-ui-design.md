# Node usability redesign

The November 1 review identifies real usability defects: all scientific nodes share generic ports,
every normal operation requires JSON, and missing table results masquerade as empty tables.
The user requested direct implementation and a documented usability improvement inventory.

## Decisions

- Keep Python 3.10 and Langflow/LFX 1.13.0. Do not change scientific algorithms or raw data.
- All 44 scientific operations receive native, operation-specific controls: choices, numeric values,
  column selectors accepting custom names, lists, key/value mappings and structured editable tables.
  Complex exceptional options remain available in advanced JSON, with explicit configuration mode.
- Include the eight original quality/context/summary nodes: normal shared rule editing and common
  checks must work without JSON. Connected shared rules remain authoritative.
- Ports follow operation capabilities. Distinguish actual data inputs from optional provenance context.
  Report export and selected multi-source operations accept report collections; only real file readers expose file upload.
  Never expose an always-absent table output. A requested unavailable conditional table fails clearly.
  Native unit checking exposes converted_table only after explicit opt-in; blocked conversion raises.
  Legacy JSON retains flagged unavailable tables solely for existing report-chain compatibility.
- Preserve old saved JSON configuration and existing port identifiers where meaningful. New forms have
  an explicit mode; direct legacy config_json-only callers keep their original settings. Provide a migration
  tool and regenerate supported workflows; do not silently discard unsupported old edges.
- Use meaningful icons, Chinese help, good defaults, method-dependent visibility and actionable validation.
  Candidate column names may be refreshed when table/file metadata is available; custom names remain
  possible. Do not claim automatic cross-node column discovery when Langflow has not supplied metadata.
- Cache identity, source hashes, units, secrets redaction and full-precision data remain intact.
- Keep the running user's original main environment and saved flows intact. Test an isolated app instance.

## Acceptance

All operations have native form definitions verified through SDK construction and serialization.
Representative actual UI acceptance covers upload, image import, preprocessing, mechanics, plotting/report export and
shared-quality rules without typing JSON. A mechanics graph has typed
strain/stress selectors, unit dropdowns and elastic interval bounds. Image import offers image metadata,
never a fake empty table. All 50 source requirements, 52 formal components and scientific outputs remain.
Native graph roundtrips, legacy compatibility, wheel install, original examples, nine connected science
flows, and real browser actions must pass. Document implemented improvements and bounded follow-ups.

## Shared schema interface

`ui_types.field(path, label, kind='str', *, default=None, choices=(), advanced=False, info='', when=None,
required=False)` returns a JSON-compatible descriptor. Paths use dotted dictionary keys. Kinds are
`str`, `list`, `int`, `float`, `bool`, `choice`, `dict`, `range`, `table`, `json`.
`range` is a pair of optional numeric controls; `dict` is a native key/value editor; `json` is advanced only.
`when` maps controlling config paths to allowed values, e.g. `{'method': ['range']}`.
UI names are `cfg_` + path with dots replaced by underscores (ranges append `_min` and `_max`).
Optional descriptor keys may include `table_schema`, `converter`, `suggestions` if an actual need exists;
coordinate additions before changing the shared interface.

Domain modules export `SPECS: dict[str,list[dict]]` and `CONTRACTS: dict[str,dict]`. Contracts use
`table_output: bool`, `artifacts_output: bool`, `upload_types: list[str]`, `icon: str`; conditional table
availability can additionally declare `table_methods` with its controlling `method_path`.
The parent owns common construction/composition, capabilities, generator and integration.

## 后续界面建议（2026-11-01，未验收）


| 优先级 | 建议 | 验收方式 |
|---|---|---|
| 高 | 运行读取节点后，给下游提供可复用的数据集字段目录 | 同一次上传，分析、绘图和质检选择器都看到实际列名；换文件后旧字段被提示 |
| 高 | 材料类型与试验模板，集中配置单位、标距、截面积及拟合区间 | 一个设置面板驱动多个节点，导出后参数和单位仍可追溯 |
| 高 | 运行前统一预检，集中列出缺文件、缺列、单位及标定问题 | 运行计算前一次显示可定位到节点和字段的问题 |
| 高 | 数据预览与单位确认，显示前几行、行数、缺失情况 | 上传后不运行复杂模型即可确认读对了列、分隔符和单位 |
| 中 | 表单配置预设的保存、命名和版本比较 | 队员复用同一套规则，能看出修改了哪些参数 |
| 中 | 直接下载生成文件及一键打包报告、图片和参数 | 远程服务器运行后，用户能在浏览器拿到完整结果，不需要找服务器路径 |
| 中 | 上传状态和选中文件的明确确认 | 上传完成后清楚显示当前选择，进度期间避免误点，确认按钮与真实选中状态保持一致 |
| 中 | 新手教学流程、分步提示和一键恢复示例 | 不看代码即可完成上传→质检→分析→绘图→导出的完整链 |
| 中 | 长任务进度、取消和失败重试 | OCR 或大数据运行中可看进度，取消后不留下被误认为完成的文件 |
| 中 | 字段目录缓存与大流程性能优化 | 用真实大流程测量启动、方法切换和输入编辑耗时，再优化热点并验证版本更新会使缓存失效 |
| 中 | 方法适用条件和结果解释卡片 | 选择检验/模型时看到样本量、独立性、配对与单位要求，并随报告记录 |
| 中 | 结果差异比较，人工修订前后并排展示 | 同一份原始数据不同规则/版本可核对发现数和力学指标变化 |
| 低 | 常用节点收藏、中文标签筛选、统一键盘操作 | 新手能迅速找到常用节点，编辑器中的键盘操作一致 |
| 低 | 任务运行记录、耗时和产物目录管理 | 可追踪哪次运行生成哪些文件，清理前能确认依赖与保留策略 |

这些建议包含需要 Langflow 前端或团队产品层支持的功能，不通过随意增加计算节点参数来代替。
已实现功能的验收范围见[0.4.0 表单验收记录](../node-ui-acceptance.md)。

## 0.4.0 行为对照（历史记录）


| 用户遇到的问题 | 当前处理 |
|---|---|
| 必须手写大段 JSON | 普通参数拆成原生表单；复杂少见对象放在高级设置 |
| 所有节点都长一样 | 不同任务使用不同图标、方法、字段和帮助说明 |
| 不知道应接什么 | 输入按实际任务生成，区分主数据与可选追溯；报告集合仅保留给确有多来源需要的节点 |
| 图像读取出现空表格 | 图像读取等不产生表格的任务不提供表格端口；报告明确标记无表格 |
| 真正筛选到零行时被误判 | 真正的零行表仍是表，报告记录 0 行；与无表格结果分开 |
| 方法切换后很多无关参数 | 根据当前方法显示控件，只把适用参数传给算法 |
| 模型任务选择被上游覆盖 | 明确区分重新训练、已有模型、已有预测值；任务选择决定执行路径并记录到追溯中 |
| 输入框顺序难找 | 流程保存字段顺序，先数据输入，再列、单位和参数；区间先下限再上限 |
| 可选数值留空却传入 0 | 增加“自定义”开关；关闭时省略参数 |
| 多个相同值无法输入 | 对 RGB、坐标、网格、命令参数等采用允许重复的有序列表 |
| 参数写错难定位 | 错误指出具体字段；整数、有限数值、区间和结构在接入处检查，算法继续检查科学适用条件 |
| 上传文件不方便 | 真实文件读取节点直接提供上传；只显示支持的文件类型 |
| 不知道结果从哪来 | 保留参数、源文件哈希、单位和来源链；已连接的追溯端口在导出流程中保持可见 |
| 旧流程升级怕丢配置 | 提供保留原文件的迁移工具；遇到自定义代码或未知参数会报告，不静默删除 |
| 不知道如何复现 | 保留可导入示例、测试和独立界面验收脚本；评委运行不依赖个人 skill |

列候选会在 Langflow 实际提供表格元数据时更新，也可手动输入。
这不等于上传文件后所有下游节点都能自动知道列名；当前 Langflow 对未执行的跨节点数据不保证提供列信息。

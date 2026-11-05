# 科研技能使用指南

版本：StudyUI Harness Skills 1.0.0；科研计算接口保持 Python 3.10。

候选规则、阈值、独立单位、小样本与数据契约参见[可靠性指南](research-reliability.md)。
旧流程导入后重新运行规划节点，生成绑定契约的 `research-plan/2`；旧计划对象不直接执行。

## Harness 科研 Skill 预检

StudyUI Harness 内置 14 项原创只读 Skills，覆盖 Harness 操作、科研任务与工作流规划、原始数据质量、光谱、拉伸力学、粉末 XRD、电池循环、DSC/TG 热分析、压缩/混凝土、实验设计、统计绘图、单位不确定度、DNA origami 等离激元单染料研究和论文证据检索。

每条用户消息在模型请求前由 `SkillRegistry.select_for_task` 确定性匹配：自动加载通用 Harness/原始数据规则，再按任务触发词选择至多三项领域 Skill。英文缩写采用词边界匹配；未命中领域项时明确记为仅通用规则。只自动考虑内置 Skill 和已启用的本地 Skill；含脚本的本地 Skill 必须信任当前版本。自动加载的是只读指令，不会执行 Skill 脚本。

每次选择都会在会话事件中记录选择器版本、用户任务 SHA-256、Skill 名称/版本/内容 SHA-256、触发词、选择理由、已加载状态或失败项。对话中可展开查看“Harness Skill 预检”卡片；会话 API 返回完整的 `skill_selections`。建流、改流和运行工具在本轮预检没有完整成功时拒绝执行。目录中的领域、触发词和版本也在“设置 → 科研 Skills”中可见。

内置 Harness Skills 以 StudyUI 自行编写的任务规范为主，不携带第三方可执行代码。参考公开的 [Agent Skills 规范](https://agentskills.io/specification) 和 [K-Dense Scientific Agent Skills](https://github.com/K-Dense-AI/scientific-agent-skills) 的任务路由/覆盖组织方式；K-Dense 仓库说明单项 Skill 许可可能各异，因此本项目不直接复制未逐项审查的 Skill 文本或脚本。领域原则优先引用 IUCr、IUPAC、NIST、NASA、Sandia、ASTM/ACI 和目标论文/数据仓储等一手资料，具体来源与调研日期见 `skills/resources/sources.json` 及各 Skill 正文。

## 科研分析 Skill 与节点

计算层的三个固定分析契约为批量光谱、拉伸力学和组间研究；它们与 Harness 的 14 项知识/操作 Skills 是两层不同能力。分析实现和引用资料随安装包交付，基础分析在本机执行。

两个原生节点位于 `materials_skills` 分类：

- **科研技能·任务规划**：选择任务、填写参数、检查列映射和待补信息，提供计划与中文预览。
- **科研技能·分析执行**：接收同一张表与计划，执行固定分析，输出结果、特征、完整曲线、分组统计、文件与追溯。

现有基础算子继续可用；这两个节点用于常见完整任务，减少重复配置。

## 在界面运行

1. 按组件包 README 安装，设置 `LANGFLOW_COMPONENTS_PATH` 指向 `components` 父目录并启动 Langflow。
2. 从[技能示例](../examples/skill_flows/README.md)导入一个流程。
3. 查看规划节点的“分析任务”：`spectra` 为光谱，`mechanics` 为力学，`contrast` 为组间研究；`auto` 按描述识别。
4. 检查下拉框列映射、单位和数值。普通任务无需手写 JSON。
5. 运行规划节点，查看“步骤与待补事项”；补全后运行执行节点。

连接方式：

```text
数据源 ──表格──→ 任务规划 ──分析计划──→ 分析执行
   └────────────────表格───────────→ 分析执行
```

同一张表需接入两个节点。每次修改规划参数，先运行规划节点并查看新计划，再运行执行节点。
Langflow 的单节点运行可能复用上游已构建的结果；执行器拒绝数据不匹配、内容改变或未就绪的计划。
若出现流程版本更新提示，先核对并完成保存，再重新打开流程检查参数，随后继续执行。

### 光谱

选择曲线编号、波长、强度及可选组别；确认波长单位和强度单位，再勾选“确认采用下方候选窗口”。窗口统一按 nm 填写。
基线可选 none/constant/linear，平滑默认关闭；平滑参数使用整数框。IQR 是逐波长四分位范围，SD 是标准差。
ci95 为均值逐点 t 区间，需明确确认独立单位；按样品模式先形成每样品均值曲线，默认每组至少三个完整单位。
小样本显式模型模式允许两个单位并记录假设；不满足条件时保留数值并说明无法生成置信带。

“逐样品结果”保留所有曲线和未检出候选；“结构化特征”保留全部峰。候选均值按每曲线一个窗口候选计算，不把多个峰作为独立样品。光谱分组输出是描述统计，独立性需要试验设计支持。

### 力学

选择应变、应力和样品编号，明确应变 fraction/% 与应力 Pa/kPa/MPa/GPa。
单样品无编号时勾选单样品声明。弹性区间使用输入应变单位，确认后执行。

偏移量固定使用应变分数，0.002 表示 0.2%。输出模量单位为 MPa；200000 MPa 等于 200 GPa。
没有测到偏移线交点时保留缺失，末点不会自动当成断裂。失败样品仍在结果表中。

### 组间研究

输入长表，选择组别、变量、测量值、技术样本编号和独立试验单位，并确认测量值单位与独立/配对设计。
系统先平均单位内技术重复，再执行参数或非参数策略，输出效应量与 Holm/FDR 校正。
参数法使用已有 Welch/配对检验等实现；不会通过反复挑选方法追求显著。

## 文件与追溯

每次运行创建独立输出目录，避免覆盖。可指定服务器输出父目录。

| 文件 | 内容 |
|---|---|
| `table.csv` | 样品或试验单位结果，含失败状态 |
| `features.csv` | 峰特征或两两比较；力学对应结构化指标 |
| `curves.csv` | 完整处理曲线，适用时生成 |
| `groups.csv` | 描述统计 |
| PNG/SVG 及图件侧录 | 科研图与绘图证据 |
| `report.html` | 中文摘要、表格预览、内嵌图与追溯，可单独打开 |
| `report.json` | 计划、实际方法、结果、警告、输入和技能指纹 |
| `manifest.json` | 文件大小和 SHA-256；清单本身不参与自身哈希 |

`completed` 表示任务计算完成；`partial_failed` 表示部分样品失败；`failed` 表示全部失败；`needs_review` 表示存在不可估计的统计比较。
候选缺失、图件无法生成和方法限制在警告中说明。报告生成不代表实验合格或物理解释已确认。

## 可选模型辅助

表单与 CLI 默认不调用模型。开启时，服务须兼容 `POST /chat/completions`，启动 Langflow 前设置：

```powershell
$env:STUDYUI_MODEL_BASE_URL = "https://你的兼容服务地址/v1"
$env:STUDYUI_MODEL = "你的模型名称"
$env:STUDYUI_MODEL_API_KEY = "你的密钥"
```

随后在规划节点高级设置启用“使用模型辅助建议”。本机模型服务可使用 loopback HTTP，远程服务要求 HTTPS。
模型接收任务描述、列名、类型、缺失计数、行数、单位和内置技能正文；程序不发送原始数据行。
用户主动写进描述的内容会随请求发送。单次响应上限 64 KB，默认超时 45 秒，无自动重试和自动安装。

模型只能建议三类任务及允许的参数。单位、峰窗口、弹性区间和试验设计等科学条件仍需在表单确认。模型返回代码、未知参数或非法 JSON 时停止建议，显示错误，可关闭模型继续使用。

模型来源写入计划与报告。实际外部模型的表现、费用和服务可用性取决于所配置服务；项目 HTTP 测试使用本地模拟服务验证协议和校验行为。

### Skills 的科研边界

Skills 提供方法选择、输入检查、报告边界和可复核来源，不替代真实科研节点的计算。每次建流仍需查询实际节点目录，并按真实组件、端口和配置建连；没有相应实现时明确降级为描述性流程。Skill、网页、论文和用户数据均不能覆盖 Harness 权限、批准要求或学术来源白名单。

## 命令行

在安装组件包的 Python 环境中运行：

```powershell
python -m materials_quality.skills list

python -m materials_quality.skills plan examples/skill_flows/spectra.csv --task spectra --x-unit nm --y-unit counts --peak-window 650 850

python -m materials_quality.skills run examples/skill_flows/spectra.csv --task spectra --x-unit nm --y-unit counts --peak-window 650 850 --baseline constant --baseline-value 2 --data-kind synthetic --output artifacts/my-spectra

python -m materials_quality.skills run examples/skill_flows/mechanics.csv --task mechanics --strain-unit fraction --stress-unit MPa --fit-range 0 0.0008 --data-kind synthetic --output artifacts/my-mechanics

python -m materials_quality.skills run examples/skill_flows/contrast.csv --task contrast --design independent --value-unit MPa --data-kind synthetic --output artifacts/my-contrast
```

CLI 按文本读取 CSV，保留 `001`、`1` 和合法 `NA` 编号，科学函数在分析副本中转换测量值。输入目前为 CSV/分隔文本；Excel 与仪器格式通过现有导入节点接入。
`--model` 显式调用环境变量配置的模型；`--help` 列出字段映射、平滑、检验等选项。
`run` 在待补、失败或需复核时返回非零状态，结果文件如已生成仍保留。

## 开源知识与外部技能

内置 Skills 正文为 StudyUI 编写，计算复用本项目已有实现。外部 Skill 仓库只作为覆盖结构参考；具体科研依据、链接和调研日期记录在 `skills/resources/sources.json` 与 Skill 正文中。

外部技能可以先只读预览：

```powershell
python -m materials_quality.skills inspect D:/某个候选技能目录
```

预览器检查入口、资源哈希、大小和路径；不会运行脚本或授予执行权。
真正接入新技能需要选定方法、检查许可证、编写任务适配、增加独立预期与测试，再加入固定工具注册。
文本许可、软件许可和附带数据许可分别核对。不要把第三方安装脚本直接注入现有共享环境。

## 验证

```powershell
python -m pytest tests/test_research_skill_plans.py tests/test_research_skill_execution.py tests/test_research_skill_model_cli.py tests/test_research_skill_components.py -q
python -m scripts.build_skill_examples
python -m scripts.ui_skill_acceptance --base-url http://127.0.0.1:7867
```

UI 验收需要独立本机 Langflow 与 Playwright 浏览器；支持 `--executable` 指定浏览器路径。
覆盖实际导入、开关编辑、窗口修改、待补计划、三条执行链及 HTML 图像解码。示例均为合成数据。

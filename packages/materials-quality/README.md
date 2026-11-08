# StudyUI

**StudyUI 是面向材料科学研究的本地 Agent 工作台和可视化工作流环境。**研究者可以用自然语言描述任务、管理项目与会话、检查数据和学术来源，并在项目权限允许时让 Agent 规划、创建、修改、运行科研工作流。工作流画布与 Agent 由同一个本地服务提供；工作流以 JSON 文件保存，计算由已安装并登记的 StudyUI 组件执行。

本仓库同时包含 StudyUI 应用、材料科学节点包、示例与回归测试。Python 分发包名称为 `langflow-materials-quality`；主要实现位于 `packages/materials-quality/`。

> **研究结果需要研究者复核。**节点会报告使用的方法、参数、输入来源、警告和适用范围；它们不会自动确认样品身份、实验设计、仪器校准或物相。仓库演示数据不能替代真实实验数据。

## 功能概览

### StudyUI Agent 与项目工作流

- 按项目组织对话、工作流、权限与审计记录；支持长任务状态、流式进度、取消及审批后继续任务。
- Agent 可检查本地数据结构、推荐方法、搜索受限的学术元数据来源，并依照组件目录规划、校验和运行工作流。
- 左侧工作流面板可按项目浏览和管理工作流；保存修改会保留可恢复的历史版本，删除则移入可恢复目录。
- 同一服务托管 StudyUI 和 LFX 工作流画布；工作流运行结果可回到对话，并附带表格、图表和报告等产物。
- Agent 只能使用仓库登记的组件。载入流程时会重新绑定安装版本的组件实现；未知组件和自定义代码不会执行。

### 材料科学与数据处理节点

组件以原生表单暴露常用参数，并提供可组合的导入、检查、预处理、分析、统计和导出流程。主要覆盖：

| 组件类别 | 能力范围（举例） |
|---|---|
| `materials_sources` | CSV/文本、Excel、PDF、图像、SQLite/SQLAlchemy/REST、仪器文件和数值数组接入 |
| `materials_extraction` | PDF 文本与表格、OCR、图像表格识别、图表曲线数字化 |
| `materials_preprocessing` | 列筛选与派生、缺失值处理、单位换算、整形、合并和归一化 |
| `materials_quality` | 可追溯的数据质量规则、检查结果与报告 |
| `materials_analysis` | XRD、光谱、热分析、力学、显微图像、电学及相关材料分析 |
| `materials_statistics` | 分组描述、相关、显著性、多重比较、回归、预测和模型评估 |
| `materials_visualization` | 科研图、表格、CSV/Excel、HTML/Markdown 报告及图表导出 |
| `materials_batch` | 多文件、多样品、逐曲线光谱、时序和跨文件批量处理 |
| `materials_literature` | 文献元数据、证据抽取与可追溯的来源信息 |
| `materials_skills` | 科研任务规划与执行节点；Agent 侧的 Skills 预检、管理和受限调用 |

科学计算节点提供可独立测试的 Python 函数；常见数据输入保持为表格或结构化对象。通常应显式确认列映射、单位、独立实验单位、基线、分析区间和统计设计。详细方法边界见各领域手册。

### Skills、学术检索与 AI 分析

- Agent 在模型请求前确定性预检 Skills：自动加载通用规则，并按任务选择有限数量的领域规则；预检选择和版本摘要写入会话事件。
- 文献检索只查询 Crossref、OpenAlex、Semantic Scholar、Europe PMC、DataCite 和 arXiv 的学术元数据接口；不提供任意网页搜索，也不自动下载论文全文。
- “AI 分析”节点只负责对经过批准的上游数据做语言模型辅助综合，不会自行联网、读取任意本地文件或执行代码；它不取代科研计算节点。
- 含脚本的导入 Skill 只有在当前版本单独审核/信任、项目权限允许并具备 Docker 时，才可在无网络沙箱中运行 Python 脚本；不能回退到宿主机执行。

## 快速开始

### 环境要求

- Windows、macOS 或 Linux。
- 推荐使用 Python 3.10。仓库启动器以 Python 3.10 验收；包元数据声明的 Python 范围为 `>=3.10,<3.15`。
- 首次安装需要联网下载依赖；连接远程模型时需要网络。无需模型密钥即可启动应用和使用确定性示例工作流。
- 默认端口为 `7880`，仅监听本机回环地址。若使用带脚本的 Skill，还需要 Docker。

### 安装并启动

在仓库根目录运行。Windows：

```powershell
.\start_demo.bat --setup
```

macOS/Linux：

```sh
sh ./start_demo.sh --setup
```

启动器会在仓库自己的 `.demo-venv/` 中安装依赖，不会向系统 Python 或其他虚拟环境安装包。依赖齐备后，它会启动 StudyUI 和工作流画布：

- StudyUI：<http://127.0.0.1:7880>
- 工作流画布：<http://127.0.0.1:7880/canvas/>

后续启动时省略 `--setup`。检查环境且不启动服务可使用 `--check`；需要更换端口时可使用 `--port 7886`。保持启动终端开启，按 `Ctrl+C` 停止本次启动的服务。

```powershell
.\start_demo.bat
.\start_demo.bat --check
.\start_demo.bat --port 7886
```

```sh
sh ./start_demo.sh
sh ./start_demo.sh --check
sh ./start_demo.sh --port 7886
```

更多启动参数、日志位置、数据目录和常见问题见[安装、运行与排障](../../docs/demo-launcher.md)。

### 配置模型（可选）

在 StudyUI 进入 **设置 → 模型管理**，填写配置名、API 地址、模型名和密钥，保存后可测试连接并切换多个模型配置。主 Agent 需要兼容 OpenAI Chat Completions 工具调用接口。远端服务地址必须使用 HTTPS；HTTP 只允许本机回环地址。密钥存入 Windows Credential Manager 或系统凭据库，不写入工作流 JSON 或会话数据库。

没有配置模型时仍可打开画布、运行不需要模型的示例工作流和使用确定性科研节点。与外部模型对话会发送用户消息及必要的上下文；AI 分析节点会将其获批的上游数据发送给当前模型服务。请只处理已获授权、可提交给所选模型服务的数据。

## 推荐使用流程

1. 在 StudyUI 中创建或选择项目，并在设置中检查该项目的权限档位。
2. 选择一个演示案例，或在对话中说明研究问题、数据文件和希望得到的结果；对于真实数据，确认单位、样品编号和实验单位含义。
3. 查看 Agent 的计划、工作流节点和审批卡片。确认目标项目、操作范围及可能的数据外发后，再授权需要的操作。
4. 在画布中检查节点参数和连线，运行工作流；查看结果表、图、警告、报告和来源信息。
5. 修改工作流后可通过历史版本恢复；删除操作会移入可恢复目录，而不是直接永久删除。

默认权限为“项目协作”，只在用户明确授权的研究任务内允许 Agent 对当前项目工作流进行协作。还可选择“只读”“逐项审批”或“审核后沙箱 Skill”。跨项目操作、删除、安装/更新/信任 Skill、权限变更以及向模型发送 AI 节点数据等操作受一次性审批控制。权限和审批细节见[Agent Harness 说明](../../docs/agent-harness.md)。

## 演示案例与科学边界

首页提供五个可直接查看的案例：“打开参考工作流”不需要模型密钥，也不会自动执行；“载入数据，交给 Agent”用于在会话中自然语言探索。

| 案例 | 演示内容 | 重要边界 |
|---|---|---|
| 钛合金拉伸 | 弹性模量、偏移屈服和曲线图 | 演示单位和拟合区间不是实验确认；不能据此推断真实 Ti64 性能 |
| 多通道光谱 | 逐曲线基线、峰位和分组描述 | 曲线条数不等于独立样品数；案例坐标为波长，不能仅凭名称认定为拉曼位移 |
| 组间比较 | 技术重复先按试验单位聚合，再进行比较 | 独立单位按文件字段解释；合成数据中的显著性不是材料实验结论 |
| 3YSZ XRD | 仪器头文本导入和候选峰提取 | 无参考谱库时不鉴定物相，也不做结构精修 |
| 锂电池循环 | 充/放电分支、SOC–电压图和容量核对 | 只有一个循环，不能推断寿命；SOC 和容量数据存在明确限制 |

这些案例的输入由用户提供，但缺少可核验的原始实验记录，项目按合成/演示数据处理。完整参数、预期输出和警告见[五个案例说明](../../docs/demo-five-cases.md)。此外，示例目录包含合成材料工作流以及带来源和哈希追溯的公开数据示例。

## 项目结构

```text
StudyUI/
├── start_demo.bat / start_demo.sh    # Windows 与 macOS/Linux 启动器
├── scripts/start_demo.py             # 隔离安装、环境检查和服务启动
├── docs/                              # 产品运行、Harness、安全与研究说明
├── demo_datasets/                     # 五个首页演示数据
├── packages/materials-quality/
│   ├── components/                    # 经登记的 LFX 科研组件
│   ├── src/materials_quality/
│   │   ├── agent/                     # Agent、任务、权限、API、工作流存储与画布
│   │   ├── science/                   # 可独立测试的科研计算、适配器与表单
│   │   ├── batch/                     # 多文件和批量分析能力
│   │   ├── skills/                    # 科研任务规划、执行和报告能力
│   │   └── demos/                     # 演示数据目录与参考工作流
│   ├── examples/                      # 可导入流程、输入数据和端到端示例
│   ├── docs/                          # 节点、方法、批处理和开发文档
│   ├── scripts/                       # 示例生成、验收和评估脚本
│   ├── tests/                         # 单元、契约、API 和 UI 回归测试
│   └── pyproject.toml                 # 包元数据、依赖组和 pytest 配置
├── workflows/                         # 本机工作流 JSON 与历史/恢复目录
├── workspace.json                     # 本机项目与排序
└── .demo-runtime/                     # 本机数据库、设置、日志、缓存和工作台资源
```

正常情况下，`workflows/`、`workspace.json`、`.demo-runtime/`、虚拟环境和模型凭据都是本机运行数据，不应提交到代码仓库。安装包的节点源文件来自 `components/`，包构建时会将其一并装入 wheel。

## 本地数据与安全

- StudyUI 默认只绑定 `127.0.0.1`，不是用于直接暴露到公网的服务。画布与 Agent 共用本机端口。
- 工作流以 `workflows/<flow-id>.json` 保存；修改版本在 `workflows/.history/`，删除项进入 `workflows/.trash/`。本机项目与顺序保存在 `workspace.json`。
- 会话、任务、审批与工具调用事件保存在 `.demo-runtime/agent.sqlite3`；非密钥模型配置和权限保存在 `.demo-runtime/studyui-settings.json`；Skill 及其版本保存在 `.demo-runtime/skills/`。
- 用户授权后，Agent 可检查明确给出的本地数据路径。外部模型会接收相关对话上下文；经审批的 AI 分析流程还可能发送上游数据。确认数据授权与模型服务条款后再执行。
- 科研节点通常在分析副本上工作，并在可用时输出来源、输入哈希、配置和警告。运行产物由节点写入其报告或指定的输出目录。

## 开发与测试

从仓库根目录进入包目录，并创建独立开发环境。Windows PowerShell：

```powershell
cd packages/materials-quality
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,science,instruments,dev,ui-test]"
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m pytest -q
```

macOS/Linux 将虚拟环境 Python 路径改为 `.venv/bin/python`：

```sh
cd packages/materials-quality
python3.10 -m venv .venv
.venv/bin/python -m pip install -e '.[langflow,science,instruments,dev,ui-test]'
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

如需完整收集和运行测试，请安装上述全部 extras：部分 API 测试在收集阶段就需要 FastAPI；浏览器测试还需要 Playwright 和 Chromium。只安装部分依赖时，部分浏览器测试可能跳过，API 测试也可能无法收集，不能把这种结果视为完整测试通过。各依赖范围见 `pyproject.toml`；仓库同时提供 `requirements.lock` 和 Python 3.10 验收快照 `requirements-tested-py310.txt`、`requirements-ui-tested-py310.txt`。

常用定向检查：

```sh
python -m pytest tests/test_agent_stream_contract.py -q
python -m pytest tests/test_demo_reference_flows.py -q
python -m scripts.build_science_examples --verify-only
```

测试覆盖节点数据契约、单位与缺失处理、统计方法、图表/导出、工作流保存和恢复、API、权限与审批、Agent 任务/流式响应、演示流程及部分浏览器交互。需要外部模型或服务的协议测试使用模拟服务；涉及 Docker、Playwright 或 FastAPI 的验收需安装相应依赖。依赖不齐时应以 pytest 报告为准，不要把未收集或已跳过的集成测试视为通过。

## 文档索引

### StudyUI 应用

- [仓库主 README](../../README.md)
- [安装、运行与排障](../../docs/demo-launcher.md)
- [Agent Harness：权限、审批、Skills 与数据边界](../../docs/agent-harness.md)
- [Agent 可靠性与任务恢复](../../docs/agent-reliability.md)
- [五个演示案例](../../docs/demo-five-cases.md)
- [证据引导分析](../../docs/evidence-guided-analysis.md)

### 节点与示例

- [节点文档索引](docs/README.md)
- [表单操作指南](docs/node-usability.md)
- [数据接入与内容提取](docs/science-io.md)
- [预处理](docs/science-preprocessing.md)
- [材料分析](docs/science-materials.md)
- [统计与建模](docs/science-statistics.md)
- [可视化与导出](docs/science-visualization.md)
- [批量处理](docs/batch-processing.md)
- [科研 Skills 指南](docs/research-skills.md)
- [科研可靠性指南](docs/research-reliability.md)
- [九份材料科学流程示例](examples/science_flows/README.md)
- [科研技能流程示例](examples/skill_flows/README.md)
- [公开 DNA origami 数据示例及来源](examples/research_flows/03-dna-origami-nanogaps.md)

第三方组件与相关许可信息见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

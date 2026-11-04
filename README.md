# StudyUI

StudyUI 是面向材料科学研究的本地 Agent Harness。研究者通过自然语言会话管理项目、查询学术来源、导入和使用科研 Skills，并在明确授权后让 Agent 规划、创建、修改和运行科研工作流。

工作流画布使用 LFX/Langflow 的图形编辑与执行运行时；项目工作流以独立 JSON 文件保存。Langflow 自带登录、账号、助手、数据库工作流存储和通用节点库不作为 StudyUI 功能。会话、审批与调用审计保存在本机 SQLite；项目、模型设置与 Skills 也保存在本机文件中。模型密钥保存在 Windows Credential Manager 或系统凭据库中。

## 环境要求

- Windows、Linux 或 macOS
- Python 3.10（启动器固定以 Python 3.10 验证）
- 首次安装需要联网下载 Python 依赖
- 连接远端模型时需要网络；本地模型可使用回环地址

## 首次安装并启动

在仓库根目录执行：

```powershell
.\start_demo.bat --setup
```

macOS/Linux：

```sh
sh ./start_demo.sh --setup
```

启动器只在项目专用 `.demo-venv` 中安装依赖。安装完成后，它会启动 StudyUI 和内部工作流画布服务。浏览器访问：

- StudyUI：<http://127.0.0.1:7880>
- 内部工作流画布：<http://127.0.0.1:7881>（通常从 StudyUI 左侧进入）

## 后续启动、环境检查与停止

后续启动：

```powershell
.\start_demo.bat
```

macOS/Linux：

```sh
sh ./start_demo.sh
```

只读检查 Python、依赖和端口，不安装、不启动服务：

```powershell
.\start_demo.bat --check
```

保持启动终端运行。按 `Ctrl+C` 会停止本次启动的 StudyUI 和工作流服务。

## 配置 AI 模型

在 StudyUI 右上角打开“设置 → 模型管理”，填写配置名称、API 地址、模型名和 API 密钥，然后点击“保存模型”或“测试连接”。DeepSeek 默认地址为 `https://api.deepseek.com`，模型名可填写 `deepseek-flash`。密钥进入系统凭据库，不进入工作流 JSON、会话数据库或 Git。设置支持保存和切换多个模型配置。

模型需兼容 OpenAI Chat Completions 工具调用接口。远端 API 必须使用 HTTPS；HTTP 仅允许本机回环服务。

## Harness 与工作流

- 项目按课题组织会话和工作流；权限默认“项目协作”。“只读”“逐项审批”和“审核后沙箱 Skill”可在设置中切换。
- 创建、运行和迭代工作流须有明确任务授权；跨项目访问、删除、权限提升和 Skills 安装、更新、信任等操作进入一次性审批卡片。审批会显示操作及影响，并写入本地审计事件。项目权限可在设置中降档撤销；待处理审批可取消，已执行的一次性操作不提供事后撤销。
- 工作流 JSON 保存在根目录 `workflows/`，每次修改保留可恢复版本。项目和排序在根目录 `workspace.json`。
- Agent 只能使用仓库已登记的 StudyUI 科研组件。读入工作流时会把节点代码重新绑定到安装版本，并保留用户参数；未登记的节点和自定义代码不执行。
- AI 分析节点从上游接收表格和主 Agent 给出的分析要求。每次向已配置模型发送上游数据都要单独审批；子代理不联网、不读本机文件、不执行任意代码，并返回结论、证据、覆盖行数、输入哈希和限制。
- 科研检索限于 Crossref、OpenAlex、Semantic Scholar、Europe PMC、DataCite 和 arXiv 的学术元数据接口，不做一般网页搜索或声称已获取全文。
- Skills 可导入、启停、更新和追踪版本。含脚本的 Skill 必须对确切版本进行审批和信任，并在离线 Docker 沙箱运行；目前仅执行 Python Skill 脚本。

## 开发和验证

```powershell
cd packages/materials-quality
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,science,instruments,dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

Linux/macOS 将最后两行替换为 `.venv/bin/python -m pip ...` 和 `.venv/bin/python -m pytest -q`。

更详细的运行方式、模型设置、权限与故障排除见[启动说明](docs/demo-launcher.md)和[Agent Harness 说明](docs/agent-harness.md)。材料节点目录、实验输入约定与示例见[组件包说明](packages/materials-quality/README.md)。

## 仓库与本机数据

仓库提交包含源代码、测试、文档及经确认的公开示例。根目录 `workflows/`、`workspace.json`、`.demo-runtime/`、虚拟环境、数据库、日志、密钥和 IDE 设置均是本机运行数据，不纳入提交。

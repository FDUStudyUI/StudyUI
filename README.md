# StudyUI

StudyUI 是面向材料科学研究的本地 Agent Harness。研究者通过自然语言会话管理项目、查询学术来源、导入和使用科研 Skills，并在明确授权后让 Agent 规划、创建、修改和运行科研工作流。StudyUI 与工作流画布由同一个本地服务提供，工作流以 JSON 文件保存。

当前首个便携演示版为 **`beta-demo`**：

- [下载便携包](https://github.com/FDUStudyUI/StudyUI/releases/download/beta-demo/StudyUI-beta-demo-portable.zip)
- [Release 说明](https://github.com/FDUStudyUI/StudyUI/releases/tag/beta-demo)
- [SHA-256 校验文件](https://github.com/FDUStudyUI/StudyUI/releases/download/beta-demo/StudyUI-beta-demo-portable.zip.sha256)

## 便携版快速开始

便携包是可直接解压运行的源码包，不内置 Python 解释器或预装依赖。需要 Python 3.10，首次安装依赖时需要网络；不需要模型密钥也可以运行首页五个演示案例。

1. 下载并解压 `StudyUI-beta-demo-portable.zip` 到可写目录。
2. 在解压后的 `StudyUI-beta-demo/` 中执行首次安装：

   Windows：

   ```powershell
   .\start_demo.bat --setup
   ```

   macOS/Linux：

   ```sh
   sh ./start_demo.sh --setup
   ```

3. 后续启动：

   ```powershell
   .\start_demo.bat
   ```

   ```sh
   sh ./start_demo.sh
   ```

4. 浏览器打开 <http://127.0.0.1:7880>。工作流画布位于 <http://127.0.0.1:7880/canvas/>，也可从 StudyUI 左侧进入。

启动器只会在便携目录内创建 `.demo-venv/`、`.demo-runtime/` 和 `workflows/`，不会写入系统 Python 或其他项目目录。保持启动终端运行；在该终端按 `Ctrl+C` 停止本次启动的服务。默认端口为 `7880`，如被占用可使用 `--port 7886`。

### 环境要求

- Windows、Linux 或 macOS
- Python 3.10（验收版本 3.10.22）
- 首次安装需要联网下载依赖
- 连接远端模型时需要网络；本地模型可以使用回环地址
- 使用带脚本的 Skill 还需要 Docker；首次使用时需要联网获取镜像
- 确保默认端口 `7880` 可用

## 便携包包含什么

便携包含运行所需的源码、启动器、科研组件、演示数据、示例流程和文档：

- `start_demo.bat`、`start_demo.sh`、`scripts/start_demo.py`
- `packages/materials-quality/src/` 与 `packages/materials-quality/components/`
- `packages/materials-quality/examples/` 中的示例流程
- `packages/materials-quality/docs/`、根目录 `docs/` 与 `demo_datasets/`
- `pyproject.toml`、依赖锁和第三方许可说明

便携包不包含本机运行数据和开发环境，包括 `.demo-venv/`、`.demo-runtime/`、`workflows/`、`workspace.json`、`uploads/`、`StudyUI_outputs/`、数据库、日志、模型密钥、IDE 设置、测试与 CI 构建缓存。不要把这些内容复制到要分享的便携目录中。

## 配置 AI 模型

在 StudyUI 右上角打开“设置 → 模型管理”，填写配置名称、API 地址、模型名和 API 密钥，然后点击“保存模型”或“测试连接”。DeepSeek 默认地址为 `https://api.deepseek.com`，模型名可填写 `deepseek-flash`。设置支持保存和切换多个模型配置。

模型密钥保存在 Windows Credential Manager 或系统凭据库中，不进入工作流 JSON、会话数据库或 Git。远端 API 必须使用 HTTPS；HTTP 仅允许本机回环服务。主 Agent 需要模型兼容 OpenAI Chat Completions 工具调用接口。

每个模型配置可选择思考等级：跟随服务默认、关闭、低、高、最高。DeepSeek 官方 API 的默认等级为高；更高等级可能增加耗时和费用。其他兼容服务应先确认支持相应参数。

## 五个演示案例

首页提供拉伸、光谱、组间比较、XRD、电池五个演示案例。“打开参考工作流”无需模型密钥，可在表单调整分析参数并运行；“载入数据，交给 Agent”用于自然语言探索。数据范围、预期结果和科学边界见[五个案例操作说明](docs/demo-five-cases.md)。

演示数据均为用户提供的演示/合成数据，不替代真实实验记录。曲线数量不等于独立样品数，文件来源和单位假设需要研究者自行核实。

## Harness 与工作流

- 项目按课题组织会话和工作流；权限默认“项目协作”，也可切换“只读”“逐项审批”和“审核后沙箱 Skill”。
- 创建、运行和迭代工作流须有明确任务授权；跨项目访问、删除、权限提升和 Skills 安装、更新、信任等操作进入一次性审批卡片，并写入本地审计事件。
- 工作流 JSON 保存在根目录 `workflows/`，每次修改保留可恢复版本；项目和排序保存在 `workspace.json`。这些是本机运行数据，不纳入仓库或便携包。
- Agent 只能使用仓库登记的 StudyUI 科研组件。载入工作流时会重新绑定安装版本的组件实现；未知组件和自定义代码不会执行。
- 科研检索限于 Crossref、OpenAlex、Semantic Scholar、Europe PMC、DataCite 和 arXiv 的学术元数据接口，不提供一般网页搜索，也不自动下载论文全文。
- AI 分析节点只综合经批准的上游数据，不自行联网、读取任意文件或执行代码；涉及模型数据传输的运行仍按权限规则审批。

## 数据与安全

- 服务只监听本机回环地址，不是公网服务。画布与 Agent 共用同一端口。
- 会话、任务、审批与调用审计保存在 `.demo-runtime/agent.sqlite3`；非密钥模型配置和权限保存在 `.demo-runtime/studyui-settings.json`；Skills 保存在 `.demo-runtime/skills/`。
- 用户授权后，Agent 可检查明确给出的本地数据路径。连接外部模型时，相关对话上下文会发送到模型服务；经审批的 AI 分析节点还可能发送上游数据。
- 上传文件、生成报告和导出结果分别位于 `uploads/`、项目目录或 `StudyUI_outputs/`。分享便携目录前应删除这些本机数据。

## 从源码运行

```powershell
git clone https://github.com/FDUStudyUI/StudyUI.git
cd StudyUI
.\start_demo.bat --setup
```

macOS/Linux：

```sh
git clone https://github.com/FDUStudyUI/StudyUI.git
cd StudyUI
sh ./start_demo.sh --setup
```

源码仓库包含测试、CI、示例和开发文档；发布到 GitHub 的内容是源代码与经确认的演示数据，不包含 `.demo-venv/`、`.demo-runtime/`、`workflows/`、`workspace.json`、`uploads/`、`StudyUI_outputs/`、数据库、日志、密钥或 IDE 设置。

## 开发与验证

代码格式、检查命令和生成文件约定见[代码风格指南](docs/code-style.md)。

```powershell
cd packages/materials-quality
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,science,instruments,dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

Linux/macOS 将最后两行替换为 `.venv/bin/python -m pip ...` 和 `.venv/bin/python -m pytest -q`。

重新构建便携包：

```powershell
python scripts/build_portable.py
```

输出位于 `dist/StudyUI-beta-demo-portable.zip`，同时生成 `.sha256` 校验文件。

## 文档

- [安装、运行与排障](docs/demo-launcher.md)
- [Agent Harness：权限、审批、Skills 与数据边界](docs/agent-harness.md)
- [Agent 可靠性与任务恢复](docs/agent-reliability.md)
- [五个演示案例](docs/demo-five-cases.md)
- [证据引导分析](docs/evidence-guided-analysis.md)
- [材料节点包说明](packages/materials-quality/README.md)
- [科学节点输入输出](packages/materials-quality/docs/science-io.md)
- [科研可靠性指南](packages/materials-quality/docs/research-reliability.md)
- [示例工作流索引](packages/materials-quality/examples/science_flows/README.md)

第三方组件与相关许可信息见 [`packages/materials-quality/THIRD_PARTY_NOTICES.md`](packages/materials-quality/THIRD_PARTY_NOTICES.md)。

# StudyUI 材料科学组件包

本包为 StudyUI 提供可视化科研节点、科研 Skills、测试与示例工作流。应用层 Agent 负责研究对话、学术检索、工具权限和审批；LFX/Langflow 的图编辑与执行能力只作为 StudyUI 内部工作流运行时。生产示例工作流使用 JSON 文件保存，组件代码只来自仓库中经过审核的材料科学节点。

## 组件类别

| 类别 | 范围 |
|---|---|
| `materials_sources` | 表格、文本、PDF、图像、仪器数据和内嵌源数据导入 |
| `materials_extraction` | OCR、图表数字化、文献字段与证据抽取 |
| `materials_preprocessing` | 质量检查、单位处理、筛选、整形和数据合并 |
| `materials_quality` | 可追溯的数据质量规则与报告 |
| `materials_analysis` | XRD、热分析、光谱、力学、显微和电学分析 |
| `materials_statistics` | 统计检验、回归、设计评估和模型诊断 |
| `materials_visualization` | 科研图、报告及 CSV/Excel 等输出 |
| `materials_batch` | 多试样、多曲线和跨仪器批量处理 |
| `materials_skills` | 科研任务规划/执行节点及 AI 分析子代理 |

画布仅列出已安装的 StudyUI 科研组件和必要数据输入节点。Agent 只能按组件目录中的端口、类型和配置创建节点与连线。JSON 工作流加载时会重新绑定已安装组件代码，保留配置值，未知节点或自定义代码不能执行。

## 安装与开发

建议直接从仓库根目录用启动器启动 StudyUI，首次安装需要联网：

```powershell
.\start_demo.bat --setup
```

macOS/Linux：

```sh
sh ./start_demo.sh --setup
```

独立开发环境需要 Python 3.10：

```powershell
cd packages/materials-quality
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,science,instruments,dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

macOS/Linux 将 Windows 路径替换为 `.venv/bin/python`。工作台入口、AI 模型配置和排障方式见[项目启动说明](../../docs/demo-launcher.md)。

## JSON 工作流

- 当前运行工作流位于仓库根目录 `workflows/`，每个流程一个 JSON 文件。
- 保存修改前会进行版本检查；变更历史位于 `workflows/.history/<flow-id>/`，删除的流程进入可恢复的 `.trash/`。
- 可分享示例存放在 `examples/` 下。根目录 `workflows/` 和 `workspace.json` 是本机数据，不应提交。
- 工作流连线应同时保存源端口、目标端口及画布句柄。Agent 会校验节点、端口、数据类型与节点标识。

## AI 分析子代理节点

`AI 分析` 组件由主 Agent 提供分析要求，上游数据通过表格或结构化结果端口输入。输出是结论、数据依据、未解决问题、限制、覆盖范围和输入哈希。该节点只做语言模型辅助综合，不联网、不访问本地文件、不执行代码；统计计算应交给确定性科研节点。

AI 分析会将上游数据发送到已配置模型服务。Agent 运行含此节点的工作流前会创建一次性审批，审批后若图内容变化则原审批失效。画布直接运行该节点会失败关闭，请从 StudyUI 研究会话请求并批准运行。

默认输入边界：最多 4,000 行、60 列、8 MB；每个模型数据块最多 200 KB。数据过大时停止并提示缩减输入；超过 4,000 行时分析前 4,000 行并明确写出未分析范围。

## Skills 与科研检索

导入 ZIP 必须包含一个 `SKILL.md`。Skill 默认停用；安装或更新需一次性审批。Skill 版本以内容 SHA-256 追踪，更新会保留旧版本并撤销现有信任。含脚本的 Skill 必须再次审批并信任当前版本，且只允许在无网络 Docker 沙箱中执行 Python 脚本。

主 Agent 的科研文献检索限定为 Crossref、OpenAlex、Semantic Scholar、Europe PMC、DataCite 和 arXiv 元数据接口，不接受模型提供任意网页地址，不自动下载论文全文。

## 数据与示例

公开原始数据示例：[DNA Origami-scaffolded single dyes in nanogaps](examples/research_flows/03-dna-origami-nanogaps.md)。流程引用论文公开仓储的四个 Figure 3 测量 CSV，并在材料化时逐一校验 SHA-256。分析保持描述性，不将每条光谱曲线擅自视作独立生物学重复。

其余节点手册和示例目录：

- [节点操作指南](docs/node-usability.md)
- [科学节点输入输出](docs/science-io.md)
- [材料分析方法与前提](docs/science-materials.md)
- [统计节点](docs/science-statistics.md)
- [文献与证据节点](docs/science-literature.md)
- [图表与文件输出](docs/science-visualization.md)
- [批量处理](docs/batch-processing.md)
- [可靠性说明](docs/research-reliability.md)
- [示例工作流索引](examples/science_flows/README.md)

## 测试

```powershell
cd packages/materials-quality
.\.venv\Scripts\python.exe -m pytest -q
```

验收涵盖节点数据契约、科研流程 JSON 重载、端口连线、权限与审批、Skill 版本、模型密钥脱敏及文件工作流。需要网络或 Docker 的测试会使用模拟服务或明确检验失败关闭行为；公开数据复现流程需从 StudyUI 画布中运行。

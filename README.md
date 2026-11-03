# StudyUI

基于 Langflow 的可视化科研 Agent 工作流。

材料科学组件包对应《工作流节点.md》的八类、50 项功能，并增加批量科研任务与内置科研技能，包含 62 个 Langflow 原生节点，
以及测试、依赖清单和可导入示例。覆盖文件与数据库接入、OCR、质量与预处理、专业材料分析、
统计建模、绘图报告和文献证据。计算默认在部署 Langflow 的电脑或服务器运行，原始数据保留。

[材料力学测试案例](packages/materials-quality/examples/mechanics/README.md)提供正常、问题、
人工修订后三份模拟教学数据和工作流，展示分组检查、合理重复测量、来源与规则追溯。

完整说明：[packages/materials-quality/README.md](packages/materials-quality/README.md)。
新手可先看[表单操作指南](packages/materials-quality/docs/node-usability.md)，
再导入[上传、力学绘图、共享规则练习](packages/materials-quality/examples/form_flows/README.md)。
多份试样或上千条光谱可使用[批量分析指南](packages/materials-quality/docs/batch-processing.md)，无需复制每份样品的节点。
希望按科研任务使用，可先导入[三个科研技能示例](packages/materials-quality/examples/skill_flows/README.md)：
选择任务、确认单位和区间，再执行分析；普通使用无需模型或 JSON。
参见[科研技能指南](packages/materials-quality/docs/research-skills.md)。

## 开始使用

评委或首次体验用户可在 Windows 双击 `start_demo.bat`，或在 macOS/Linux 执行 `sh ./start_demo.sh`。
启动器使用项目专用环境，服务就绪后预载三个科研技能演示；首次安装需要联网。
已有环境可先运行 `start_demo.bat --check`，详见[启动器说明](docs/demo-launcher.md)与[评委运行说明](submission/05_代码运行说明.md)。

开发与测试环境：

```powershell
cd packages/materials-quality
$env:PYTHONUTF8 = "1"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[langflow,science,dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

网页编辑器接入方式及示例工作流见组件包说明。当前验证目标是 LFX 1.13.0 / Python 3.10；
团队运行版本尚未最终确认。已完成 [Langflow 1.13.0 全套节点验收](packages/materials-quality/docs/full-suite-acceptance.md)，
并提供运行时测试、wheel 安装验证和独立 UI 自动验收脚本。

## 目录约定

```text
packages/materials-quality/    # 独立组件包
.github/workflows/             # CI
```

[逐项功能与子方法对照](packages/materials-quality/docs/requirements-matrix.md)及
[连接工作流示例](packages/materials-quality/examples/science_flows/README.md)见组件包。
图像量化、谱库匹配与仪器插件需要提供相应校准或参考输入，具体条件已写入方法手册。

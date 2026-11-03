# 科研技能使用指南

版本：0.6.0。运行目标：Python 3.10、Langflow/LFX 1.13.0。

## 技能与节点

项目内置三个 Skill：批量光谱分析、材料力学分析、组间研究与绘图。
Skill 文件、参考资料和执行逻辑随安装包交付，基础分析在运行 Langflow 的电脑或服务器上执行，无需开发助手的私人技能。

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
基线可选 none/constant/linear，平滑默认关闭；平滑参数使用整数框。IQR 是逐波长四分位范围，SD 是标准差，ci95 是均值逐点 t 区间。

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

内置技能正文为 StudyUI 编写，计算复用本项目已有实现。参考了 Agent Skills 结构、Langflow 工具方式及 K-Dense 的研究方法组织。
来源、调研日期和已核对的上游文件 blob 哈希记录在安装包 `skills/resources/sources.json` 中。
pybaselines 与 lmfit 作为后续算法扩展候选，本版本未安装它们，也未声称调用这些库。

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

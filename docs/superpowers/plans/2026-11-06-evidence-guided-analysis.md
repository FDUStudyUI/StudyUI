# 有文献依据的科研分析实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 将已核查论文中的方法检索、条件检查、局部重算和证据关联接入 StudyUI，提供可操作、可复跑的科学分析。

**Architecture:** 扩展现有 science 操作、可视化表单和 Agent 工具。数值计算由确定性函数执行；方法卡明确证据与适用条件；纯计算任务图在输入和依赖一致时复用结果。保持现有工作流兼容。

**Tech Stack:** Python 3.10+、SciPy、scikit-learn、pandas、Langflow/LFX 1.13、现有 HTML/JavaScript 界面。

**Spec:** `D:/学习/智能体大赛/StudyUI可借鉴方法与实施建议_2026-11-06.md`；设计借鉴 LUMIR、SciLink、Data Interpreter、BLADE，具体科学方法另行核对原始资料。

## Global Constraints

- 普通用户使用下拉、勾选、数值和列选择输入，不要求手写 JSON。
- 不复制许可不明确的 LUMIR 源码；方法独立实现或使用已有科学库。
- 未满足输入条件不能显示为科学验证通过；检索命中不是适用性结论。
- 不自动改变用户确认的物理窗口，不自动修改原始数据。
- 学习型变换只在训练集/训练折拟合；独立测试集不得参与方法选择。
- 不触碰旧 main 和运行环境，不自动合并 PR；在 PR #8 基础上提交增量。

## Review Focus

- 相同材料但不同信号类型，以及缺失条件时，候选必须阻止自动套用。
- 逐谱标准化会丢失绝对强度；导数单位与非等距横坐标须明确。
- 样品重复或跨仪器重复不得跨训练测试两侧。
- 数据、参数、方法版本变化必须使相关下游结果失效，副作用不可缓存。
- 文献引用不得被解释为实测结果；报告中的结果引用必须能核对。

## Task 1: 方法卡与条件检查

Files: 新建 `science/method_cards.py`、`science/method_cards.json`、`science/ui_specs_methods.py` 和测试；注册新操作时由主代理统一集成。

Interface: `recommend_methods(table=None, *, config=None, data=None, tables=None) -> NodeResult`。输入目标、信号类型、坐标单位、是否允许去绝对强度；输出候选表、明确的 missing/blocked/eligible 状态、可执行映射及来源。预置卡保留核查位置和短摘录，至少覆盖 10 种方法/任务；不杜撰特定实验配方。

- [x] 先写不匹配、未知条件、组合不兼容和来源完整性测试并确认失败。
- [x] 核查原始资料，提供方法卡、确定性检索和条件校验、可视化字段。
- [x] 跑针对测试，交由独立审查。

## Task 2: 光谱与化学计量学

Files: `science/materials_curves.py`、`science/materials.py`、`science/ui_specs_materials.py`；新建 `science/chemometrics.py` 和相关测试。

Interfaces: 现有 `materials.spectra` 增加 AsLS、SNV 和 SG 导数，保留原始/基线/处理列；新增 `chemometrics(table=None, *, config=None, data=None, tables=None) -> NodeResult`，使用显式样品划分进行 PCA/PLS 分析，返回逐样品预测/得分与诊断。

- [x] 先写已知基线、多项式导数、零方差、非等距和测试集隔离测试。
- [x] 实现方法、可视化表单和单位处理，复用已有批处理链路。
- [x] 验证独立数值参考和改变测试集不影响训练拟合。

## Task 3: 有条件复用的任务图

Files: 新建 `science/analysis_plan.py` 和测试；提供可被节点调用的确定性执行接口。

Interface: `AnalysisPlanRunner.run(steps, inputs, previous=None)`；步骤 id、operation、config、dependencies 明确。只允许预登记的无副作用 science 操作；输出记录 input/config/implementation/dependency 指纹、elapsed、status、result 和复用/失效原因。失败后的运行可显式修订该步并复用无关已完成步骤；有限预算；下游依赖失败时 blocked。

- [x] 先写菱形图局部失效、失败重试、循环、未知节点、副作用拒绝、结果篡改测试。
- [x] 实现有界运行与结果校验，不对通用 Langflow 图或外部调用隐式缓存。
- [x] 提供可运行示例和计数断言，交由独立审查。

## Task 4: 接入、结论证据、独立评测与交付

Files: science catalog/form 注册和生成组件、Agent 工具、报告生成器、示例、docs、evaluation 脚本、CI。

- [x] 接入可视化节点与 Agent 方法建议工具；让真实用户路径能调用新增能力。
- [x] 报告加入观察/文献解释/待验证推测及可核对结果和方法来源。
- [x] 复用 Corn/Tecator 本地数据建立显式样品划分参考；下载数据不随意入库，保留来源、SHA256 和可复现获取说明。
- [x] 提交无需外网的合成科学验收及中间决策评测，明确不属于在线 LLM 提升实验。
- [ ] 运行相关/全量测试、静态检查、示例工作流和真实浏览器验收，独立审查后提交 PR。

## Design Decisions

完整实现这一闭环优于仅加提示词；少量面向任务的节点优于为每种算法复制一套节点。保留原有节点，将新增算法作为选择项。局部重算先限定为纯科学计算任务图，避免把网络请求、文件导出或审批操作误当作可复用计算。文献方法卡记录“方法来源”与“StudyUI 适配决定”的区别；不宣称所有卡来自某个材料实验。

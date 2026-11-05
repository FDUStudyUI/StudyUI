# StudyUI Agent Harness

StudyUI 是主 Agent 应用，并在同一服务内提供科研工作流画布和图执行引擎。项目工作流写入 `workflows/<flow-id>.json`，项目和排序写入仓库根目录 `workspace.json`，会话、审批、工具调用事件保存在 `.demo-runtime/agent.sqlite3`。非密钥模型配置和权限设置写入 `.demo-runtime/studyui-settings.json`；Skills 位于 `.demo-runtime/skills/`，密钥进入系统凭据库。

```text
研究者
  └─ StudyUI 主 Agent
       ├─ 自然语言会话与本地会话记忆
       ├─ 注册科研工具与权限/一次性审批
       ├─ 受限科研来源检索与按需加载的 Skills
       ├─ 项目内 JSON 工作流规划、编辑、校验和运行
       └─ LFX 画布与执行器
            └─ AI 分析子代理节点
```

## 权限、审批与审计

项目默认权限为“项目协作”。可在设置中选择：

| 档位 | 行为 |
|---|---|
| 只读 | 浏览项目、组件与学术来源；工作流改动和执行需单次审批。 |
| 项目协作 | 用户明确授权研究任务后，Agent 可在当前项目内创建、修改、运行和迭代工作流。 |
| 逐项审批 | 每项 Agent 工具操作都等待用户处理本次审批。 |
| 审核后沙箱 Skill | 项目协作，并允许已审核版本的 Python Skill 在离线 Docker 沙箱执行。 |

跨项目操作、删除工作流或项目、安装/更新/信任 Skill、权限提升，以及包含 AI 分析节点的工作流运行会创建一次性审批。审批卡片显示目标、影响和数据传输信息；批准、拒绝和取消均写入 SQLite 事件日志。工作流审批绑定操作参数及流程摘要，审批后流程如有变化则请求失效。审批失败、过期或状态冲突时不执行。

项目权限是可持续的项目级设置；可在设置中随时降档撤销，例如从“项目协作”切换为“只读”，降权立即生效并写入审计。尚未处理的单次审批可取消（即撤回该请求）；批准后授权立即用于该次操作并被消耗，不会留下可复用的长期审批许可，也不能在副作用完成后撤回操作本身。工作流修改可从 JSON 历史版本恢复。

编辑器 API 也会检查项目权限。Agent 和用户画布中的工作流节点仅允许仓库登记的 StudyUI 组件；加载 JSON 时以安装版本的组件代码替换内嵌副本，同时保留表单值。自定义代码节点、未经登记节点和自定义组件代码更新接口被拒绝。

## Skills

内置 Skills 以任务匹配后加载，不会每轮把整个 Skills 目录交给模型。ZIP 导入在安装前检查大小、文件数、路径穿越、符号链接及唯一 `SKILL.md`，之后通过一次性审批安装。导入 Skill 默认停用；每次更新会保留旧版本哈希和副本，信任不会跨版本继承。

Skill 说明和资源作为不可信研究输入，不能覆盖 StudyUI 权限规则。运行脚本前必须审批确切版本，只有 `skill_sandbox` 档位、当前 Skill 已启用并信任、且存在 Docker 时才执行。容器无网络、只读挂载 Skill 文件并限制 CPU、内存、进程数、运行时间和输出大小。Docker 不可用时明确失败，不回退到宿主机执行。

## AI 分析子代理

“AI 分析”组件接收上游 `DataFrame` 或结构化 `Data`，主 Agent 将经过整理的分析要求写入 `analysis_request`。该节点不会自行检索、访问本机文件或运行代码。其结果包含 `conclusions`、`evidence`、`limitations`、`unresolved`、覆盖范围、输入 SHA-256 和分析边界。

默认最多处理 4,000 行、60 列、8 MB 输入；按最多 80 行分块，并根据序列化大小继续拆分，单块最多 200 KB。超过限制会明确停止，不静默丢弃。超过 4,000 行时只分析前 4,000 行，并在覆盖和限制字段中标注未分析行数。该节点用于定性综合，不替代统计、计量或材料计算节点。

AI 节点向已配置模型发送上游数据，所以 Agent 发起包含该节点的流程运行时会先请求本次审批。审批绑定工作流摘要；运行期间也会由节点执行上下文验证批准状态。经画布直接运行的此类流程会失败关闭，并提示通过 StudyUI 会话申请审批。

## 学术检索与模型

文献搜索仅调用固定白名单：Crossref、OpenAlex、Semantic Scholar、Europe PMC、DataCite 和 arXiv。检索最多每源 10 条、响应体限制 3 MB，不允许用户或模型指定任意 URL，并禁止自动跟随重定向。工具返回的是元数据；除非用户提供并单独处理全文，不得声称已阅读论文全文。

提供 Zenodo 记录编号或链接时，DataCite 查询可以按对应 DOI 精确获取仓储元数据；未查询到内容或服务报错会明确返回，不把检索失败当成论文结论。

模型配置保存在本机 JSON 文件中，密钥通过系统凭据库保存。主 Agent 使用 OpenAI-compatible 工具调用接口；AI 分析节点使用同一活动模型但不带工具。远端服务必须 HTTPS，本机回环 HTTP 可用。每次聊天都会把用户消息及必要的研究上下文发给该模型服务。

每个模型配置保存思考等级：`default` 不发送等级控制，DeepSeek 官方服务默认启用 `high`；`none` 发送关闭思考，`low`、`high`、`max` 分别开启相应等级。主 Agent 与 AI 分析子代理共用活动模型的设置；对其他服务选择非默认等级前，应确认其兼容 DeepSeek 参数。DeepSeek 工具调用要求把模型返回的 `reasoning_content` 在后续请求中传回：StudyUI 将其保存在本机会话数据库中用于延续上下文，不显示在会话消息接口；旧会话没有保存的内容以空字段表示，不能恢复丢失的历史思考内容。更高等级可能增加时延与 token 消耗，长请求仍受网络和超时限制。

## 数据与文件

- JSON 工作流在保存时自动快照至 `workflows/.history/`，删除的工作流移至 `workflows/.trash/`。
- 工作流与项目操作作用于本地项目目录；读取、编辑和运行前校验项目归属。
- 用户在本会话明确给出的本地 CSV、TSV、TXT、RAS 或 Excel 路径可由文件检查工具读取，用户可以撤销读取；工具返回文件哈希、格式、结构、可能的表头和稀疏标签统计，不返回数值测量行。文本候选标签可能包含数据内容，会发给所配置的模型；仅提供有权交给该模型处理的文件。文件大小和工作簿解压大小有上限，逐项审批模式下检查也须审批。
- 节点运行产物留在节点指定或运行时目录；报告和图表中的来源、哈希及覆盖信息由科研节点提供。
- Agent 可接收指定统计/特征节点的有界派生摘要；分组统计中无法确认至少两个观测的组会隐藏数值，以免将单个测量伪装为汇总。摘要不替代完整导出表，也不能证明独立性。
- 用户请求研究报告时，Agent 可通过受项目权限和审计约束的 `write_research_report` 创建独立 Markdown 附件；节点导出的运行记录用于追溯，不能替代对研究结果、证据与限制的说明。报告的科学结论仍须根据实际数据和来源核验。
- 会话、工具调用、审批申请和决策事件存储于 `.demo-runtime/agent.sqlite3`，不发送到模型数据库。
- 用户消息、Skill 指令、组件定义、检索元数据和明确批准发送的上游数据会到达配置的模型服务。不要在没有数据授权时运行包含 AI 分析节点的流程。

## 相关实现

- Agent、工具和对话：[harness.py](../packages/materials-quality/src/materials_quality/agent/harness.py)
- 权限档位：[permissions.py](../packages/materials-quality/src/materials_quality/agent/permissions.py)
- Skills 导入和版本：[skill_registry.py](../packages/materials-quality/src/materials_quality/agent/skill_registry.py)
- 离线沙箱：[skill_sandbox.py](../packages/materials-quality/src/materials_quality/agent/skill_sandbox.py)
- AI 分析节点：[ai_analysis.py](../packages/materials-quality/components/materials_skills/ai_analysis.py)
- JSON 工作流存储：[workflow_files.py](../packages/materials-quality/src/materials_quality/agent/workflow_files.py)
- 运行与验收命令：[demo-launcher.md](demo-launcher.md)

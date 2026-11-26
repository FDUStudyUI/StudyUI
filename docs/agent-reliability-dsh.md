# Agent 引擎：DeepSeek Harness（DSH）与可靠性设计

本文记录 StudyUI 在可靠性改造后的 agent 架构。改造目标来自一次 5 任务对照实验：在相同 provider / 模型（deepseek-v4.1-flash）下，MatOS 的 DSH 宿主完成了全部任务且交付物数值正确；旧版自研 harness 出现单任务 40+ 次审批循环、90 秒模型预算超时失败、因科学前提不确定而拒绝交付等问题。

## 架构

```
浏览器 → FastAPI（会话 / 权限 / 审批 / 审计 / 工件 / SSE）
        → TaskManager
        → AgentEngine 选择
             ├─ dsh-sdk  官方 DeepSeek Harness Python SDK（JSON-RPC，逐会话常驻）
             ├─ dsh      DSH headless CLI（NDJSON 事件流，一轮一进程）
             └─ legacy   旧版进程内 harness（保留回退）
        → 科学节点库（70 组件 / 48 科学操作，仍为确定性 Python）
```

- **agent 循环交给 DSH**：默认使用官方 `deepseek-harness-sdk`（MIT）驱动 DSH SDK profile；进程按会话常驻，支持 `session/resume` 恢复、`approval/request` 原生审批、`/permission` 原生权限切换。
- **StudyUI 保留**：项目/会话/SQLite 审计、权限档位、工件收集、科学节点与表单、画布与 UI。
- **确定性科学入口**：`python -m materials_quality.science_tools list|show|run`，供 DSH 的 Bash 工具直接调用；返回 JSON（含 warnings 与 NodeResult.data）。

### 引擎选择顺序

`agent_engine` 设置（`STUDYUI_AGENT_ENGINE` 环境变量优先）：

1. 显式 `"dsh-sdk"` / `"dsh"` / `"legacy"`；
2. 未设置时：SDK 可用 → `dsh-sdk`；否则 headless 可用 → `dsh`；否则 `legacy`。

SDK 缺失或无法启动时自动回退 headless，并在审计中记录 `dsh_sdk_unavailable`。

## 引擎选择

设置文件 `.demo-runtime/studyui-settings.json` 顶层 `agent_engine`：

- `"dsh"`：强制 DSH；
- `"legacy"`：强制旧 harness；
- 未设置：DSH 可用则 DSH，否则回退 legacy（并写 `dsh_unavailable` 审计事件）。

环境变量 `STUDYUI_AGENT_ENGINE` 优先于设置文件，便于排障。

首次运行 `start_demo.py --setup` 会调用 `scripts/setup_dsh.py` 自动安装固定版本 `@deepseek-ai/dsh`（默认 0.2.2-rc.5）到 `.demo-runtime/dsh`，创建 `studyui`（headless）与 `studyui-sdk`（SDK）两个 profile 与全局 `AGENTS.md` 指令。缺少 Node 24/npm 时跳过并回退 legacy。Python SDK 作为可选依赖：

```powershell
.\.demo-venv\Scripts\python.exe -m pip install -e "materials-quality[dsh-sdk]"
.\.demo-venv\Scripts\python.exe scripts\setup_dsh.py
```

## Provider 与协议

- DSH 说话对象是 **Anthropic Messages** 兼容端点。`dsh_engine.map_base_url()` 自动转换：
  - `api.deepseek.com` → `api.deepseek.com/anthropic`
  - 其他地址原样使用（需为 Anthropic 兼容网关）
- profile 禁用两个只认 DeepSeek 官方端点的请求扩展（`session-log-deepseek`、`plugin-package-inventory-deepseek`），以兼容其他 Anthropic 网关。
- 密钥来自 StudyUI 模型配置（OS 凭据库），以 `DEEPSEEK_API_KEY` 注入子进程；BASE URL 以 `DEEPSEEK_BASE_URL` 注入。

## 权限与沙箱（放行模型）

StudyUI 权限档位映射为 DSH headless 参数：

| StudyUI 档位 | DSH SDK 模式 | 审批行为 |
|---|---|---|
| `read_only` | `/permission read-only`（沙箱只读 + ask） | 所有升级请求一律拒绝 |
| `project_collaboration` | `workspace-write`（默认） | 工作区内直接执行；沙箱升级自动放行（记录审计） |
| `per_action` | `/permission read-only`（沙箱只读 + ask） | 每次写入/命令升级都会生成 StudyUI 一次性审批，批准后 `allowed-once` 执行 |
| `skill_sandbox` | `workspace-write` | 同 project_collaboration |

headless（`dsh`）引擎的映射沿用启动参数；`per_action` 在 headless 下没有审批应答通道，自动改走 legacy。

**审批桥接**：SDK 的 `approval/request` 由常驻泵线程处理，`_tool_permission` 根据档位裁决。`per_action` 时先注册等待者、再写入 SQLite `approvals`（action=`dsh.tool`，含工具名与摘要），任务保持运行并阻塞在引擎侧；UI 通过 `approval_pending`/`approval_resolved` 进度事件即时显示审批卡片。`/api/approvals/{id}/approve|reject|cancel` 直接调用 `decide_approval`（绕过 SessionBusy），**三种结果都会唤醒等待者**：批准回复 `allowed-once`，拒绝/取消回复 `rejected`；超时（默认 900 秒，`STUDYUI_DSH_APPROVAL_TIMEOUT`）使审批失效并回复 `rejected`。

**沙箱自动降级**：SDK 会话在 workspace-write 下若宿主无法授予 Windows ACL（`SetNamedSecurityInfoW Win32 5`），引擎检测工具结果中的错误后执行 `/permission danger-full-access` 并重跑一次本轮，结果记录 `permission_fallback`。headless 引擎有等价的进程级降级。

**临时目录**：DSH 的 Windows 沙箱要求临时根在工作区之外。StudyUI 启动器把 `TEMP` 指向 `.demo-runtime/tmp`（工作区内），因此引擎为 DSH 设置独立的、保证在工作区之外的临时目录（`%LOCALAPPDATA%\StudyUI\dsh-tmp` 或 `~/.studyui/dsh-tmp`）。

## 会话与恢复

- 每个 StudyUI 会话在 SQLite `engine_sessions(session_id, engine, engine_session_id)` 中保存 DSH 会话 id（`dsh-sdk` 与 `dsh` 各自记录）。
- SDK 引擎进程按 **StudyUI 会话**常驻（池键包含会话 id、工作目录、模型与端点）；删除会话时释放对应 runtime。下一轮直接沿用同一 runtime 与 session；服务重启后使用 `resume_session` 恢复历史，恢复失败会清空 engine session 并新建会话（审计 `dsh_session_reset`）。
- 每轮都有硬性截止时间（`STUDYUI_DSH_TIMEOUT_SECONDS`，默认 30 分钟）与取消检查：看门狗在超时或收到取消请求时关闭并丢弃该 runtime，任务以 failed/cancelled 结束，不会长期占用会话任务槽。取消入口：`POST /api/sessions/{id}/tasks/{task_id}/cancel`。
- 启动时会使所有遗留的 `dsh.tool` 待审批失效（审计 `approval_invalidated`），避免服务重启后出现无法处理的审批。
- 每轮显式应用权限 preset（`/permission read-only|workspace-write`）；应用失败会 fail-closed 并审计 `dsh_permission_apply_failed`。ACL 降级到 `danger-full-access` 只影响该轮，下一轮恢复映射档位。

## 事件与审计

每个 DSH 轮次写入：

- `dsh_turn_started`：权限档位、是否续跑、模型；
- `dsh_turn_finished`：状态、工具调用数、token 用量、权限降级标记；
- 工具步骤（tool_call/tool_result 摘要）进入任务结果 `tool_steps`，UI 的时间线与审计界面继续可用。

DSH 事件映射到 StudyUI 的进度事件：SDK 的 `assistant/message` → `content_chunk`（delta，含推理增量）、`tool/call` → `tool_start`（id/name/title/icon）、`tool/result` → `tool_end`（step）、每步 usage → `usage`；headless 的 `text`/`thinking` → `content_chunk`/`reasoning`（delta），`tool_call`/`tool_result` → `tool_start`/`tool_end`，`step_end` → `usage`。任务结果中的 `tool_steps` 与 `token_usage` 由引擎从持久事件汇总，不再为空。

## 已知边界

- `per_action` 在 **headless**（`dsh`）引擎下无法交互审批（fail-closed），会自动路由回 legacy；SDK 引擎（默认）通过原生 `approval/request` 完整支持逐项审批。
- Headless `--json` 事件流是**提交点投影**：`text`/`thinking` 在步骤完成时到达，不是逐 token 流式。UI 仍能显示步骤级内容，但没有逐字流式效果。
- DSH 的 `web_search` 依赖 DeepSeek 官方凭据；在非 DeepSeek 官方端点上不可用。文献检索请使用科学节点/CLI（`science_tools run lit.search ...`），后续将以 host 工具形式接管。
- `danger-full-access` 降级时，agent 与 StudyUI 同一个 OS 账户运行，能读到进程环境中的模型密钥。共享主机上应改用低权限账户，或使用有 ACL 权限的目录让 `workspace-write` 沙箱生效。
- 便携包尚未内置 Node 24 运行时；`setup_dsh.py` 依赖本机 Node/npm。后续可将 Node 与 DSH 一并打入便携包。
- 科学操作通过 CLI 暴露；后续升级为 MCP stdio 服务器以获得逐工具 schema 与授权。

## Phase 2 设计结论（来自并行架构 review）

对 DSH 0.2.2 的官方接口做了逐项核对，结论：

1. **改用官方 Python SDK**（`deepseek-harness-sdk`，MIT）承载 JSON-RPC 传输、initialize / session/prompt / session/resume / 通知与 server-to-client 请求；Python 侧只保留 StudyUI 的策略与事件投影。这能恢复逐 token 流式与原生权限回调，替代当前的 headless CLI 路径。
2. **工具 schema 需转换**：DSH 的 `defineTool` 使用隐式属性表（逐属性 `required: true`），不接受根级 JSON Schema 与 `minLength/minItems/minimum` 等关键字。StudyUI 的 host 工具（科学操作、文献检索、工作流动作）需要 `to_dsh_parameter_spec()` 转换器。
3. **审批二选一**：v1 统一走 DSH 原生 `ask` + `tools/pre-execute` 回调（映射到 `_create_tool_approval` 与任务暂停），不要另建 pause store；审批恢复沿用现有 `approval-resume-*` 续接任务。
4. **幂等回执**：宿主工具副作用按 `(task_id, tool_name, sha256(args), flow_digest)` 记录 `executing/completed` 回执；重复调用返回已存结果，`executing` 状态要求人工复核，保证 kill/restart 后的 exactly-once。
5. **模型路由**：DSH initialize 会解析精确的 provider/model；需在 provisioning 时生成全部 StudyUI 模型配置的 provider 列表，或在每轮用 `--patch` 注入当前模型。
6. **原生工具与宿主工具分离**：`read/write/edit/bash/web` 由 DSH 原生执行（保留沙箱与 diff 卡片），只有 StudyUI 注册的 host 工具走 `studyui/tool/execute`。
7. **Windows 进程树**：用 `CREATE_SUSPENDED + Job Object(KILL_ON_JOB_CLOSE)` 保证 DSH 子进程与孙进程在取消/退出时被彻底回收。
8. **范围控制**：v1 只做引擎接缝 + SDK host + 事件投影 + host 科学/文献工具 + 暂停/恢复审批 + 基础任务恢复；MCP 传输、detached 工作流、预算账本、自动重扫等延后。


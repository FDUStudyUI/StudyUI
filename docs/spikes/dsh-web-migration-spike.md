# DSH Web 迁移 P0 去风险 Spike

- 日期：2026-11-26
- 目标：在改产品代码前，验证「StudyUI 前端切换为 DSH Web」的四个硬假设
- 环境：Windows 11 / `@deepseek-ai/dsh` **0.2.2-rc.5** / Node **24.22.1** / Python `mcp` **1.30.0** / Playwright Chromium
- 约束：所有探针在临时目录运行；**未修改**仓库代码、DSH 安装目录或 `dsh-web-frontend/dist`

## 结论：GO（4/4）

| 假设 | 结论 | 关键证据 |
|---|---|---|
| DSH Web 可独立启动，token/cookie 链路可用 | **GO** | 401 → 303+Set-Cookie → 200；端口冲突退出 1 |
| StudyUI 品牌可插件化，无需改 dist | **GO** | 手写 lazy-CJS 插件生效；侧栏显示 SU / StudyUI；标题守卫生效 |
| MCP stdio 可保持 JSON-RPC 纯净 | **GO** | 业务 print/fd1 写入全部落到 stderr，stdout 4/4 行合法 JSON |
| 画布可作为 DSH 面板 + 同源 iframe 保留 | **GO** | `admit()` 401/200；keyed `main` 面板加载 iframe 成功 |

---

## 1. DSH Web 启动与鉴权

### 命令

```text
node <runtime>/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js \
  --profile web --no-open --host 127.0.0.1 --port 7899
```

`DSH_HOME` 指向临时目录，首次启动自动创建 shipped `web` profile。

### 实测结果

| 检查 | 结果 |
|---|---|
| 就绪信号 | stdout 恰好出现 1 次 `dsh web: http://127.0.0.1:7899/?token=...` |
| 无 token `GET /` | **401** |
| token URL `GET /?token=...` | **303** + `Set-Cookie` |
| 带 cookie `GET /` | **200** `text/html` |
| 页面基线标题 | `DeepSeek Harness`（服务端注入后的 index） |
| 同端口二次启动 | 退出码 **1**，stderr 指向端口失败 |
| profile 结构 | `profiles/web/{package.json,cordis.patch.yml,cordis.yml,pnpm-workspace.yaml}` |
| 默认 bundles | `@deepseek-ai/dsh-base` + `@deepseek-ai/dsh-web-app` |

### 对 P1/P2 的含义

- 启动器必须只认 `dsh web:` stdout 行作为就绪信号，不要用 TCP/health 轮询。
- token 是进程级完全控制凭据：终端只打印脱敏 URL，浏览器打开原始 URL。
- DSH 端口被占用会明确失败，因此 7880 必须先 preflight。

---

## 2. StudyUI 品牌（名称 / 标题 / Logo）

### 已验证

1. **host 侧 `tapIndex` 可改写服务端 index**：`<title>` 改为 `StudyUI`，`apple-mobile-web-app-title` 改为 `StudyUI`。
2. **SPA 启动后会回写标题**：仅改 index 不够；客户端插件必须加 `MutationObserver` 标题守卫（每 1s 兜底），实测最终 `document.title === "StudyUI"`。
3. **客户端插件可以手写 lazy-CJS，不需要 esbuild/tsdown**：
   ```js
   window.__ModuleLoader__.load({ id: `studyui-probe`, factory: require => {
     const react = require("react")
     // ... exports.apply / exports.inject
     return module.exports
   }})
   ```
   仅依赖 baseline 模块（`react` / `react/jsx-runtime`）。
4. **`dsh.client` 声明生效**：
   ```json
   "dsh": { "client": { "platform": "web", "inject": [
     "@deepseek-ai/dsh-client-ui-renderer",
     "@deepseek-ai/dsh-client-ui-sidebar",
     "@deepseek-ai/dsh-client-ui-layout"
   ] } }
   ```
5. **侧栏品牌槽位生效**：注册 `sidebar.brand.mark` / `sidebar.brand.name`，并 `disabled: true` 掉 `ui-brand-official` 后，侧栏显示 `SU` + `StudyUI`，无 “DSH Local Build”/DSH 字标。
6. **bundle 路由**：浏览器实际走 combo（`/plugins/??...,studyui-probe/client.js&rev=...`，实测 **200**）；直接 `/plugins/studyui-probe/client.js` 返回 404，不能硬编码直链。
7. **无 console / page error**。

### 截图证据

`%TEMP%\studyui-dsh-spike\brand_probe.png`（临时目录，不随仓库分发）

### 待 P3 完成

- manifest / favicon / apple-touch / icon 资产路由与 index 链接改写。
- StudyUI Logo 资产（当前探针用 `SU` 占位）。
- 浏览器 tab 标题、PWA manifest 名称的端到端断言。

> 按用户决定：**不替换 DSH 已构建文案**（onboarding/settings 等仍显示 “DeepSeek Harness”）。

---

## 3. MCP stdio 纯净性

### 关键实现

```python
transport_fd = os.dup(1)
os.dup2(2, 1)
sys.stdout = sys.stderr
real = TextIOWrapper(os.fdopen(transport_fd, "wb", buffering=0), encoding="utf-8")
async with stdio_server(stdout=anyio.wrap_file(real)) as streams:
    await server.run(*streams, server.create_initialization_options())
```

`mcp 1.30.0` 的 `stdio_server(stdin=None, stdout=None)` 支持传入自定义流。

### 实测结果

| 检查 | 结果 |
|---|---|
| initialize | 成功，`serverInfo.version = 1.30.0` |
| tools/list | 3 个工具，schema 合计 455 字节 |
| `tools/call` noisy（内部 `print` + `os.write(1, ...)`） | 返回 `noisy ok` |
| stdout 行 | **4/4 合法 JSON，0 条 invalid** |
| 业务噪声 | 全部出现在 **stderr**，stdout 无 `BUSINESS NOISE` |

### 对 P4 的含义

- 科学栈/LFX/pandas 的 stdout 输出不会破坏 JSON-RPC。
- 工具面保持紧凑（≤20 个），长任务用 submit + poll，避免 60s `tools/call` 超时。
- 启动时懒导入重模块，保证 `tools/list` 在启动预算内。

---

## 4. 画布面板与鉴权

### 已验证

1. **host 路由鉴权**：注册 `prefix` 路由 `/studyui/probe`，先调用 `ctx.connection.admit(req)`：
   - 无 cookie → **401**
   - 带 DSH cookie → **200**
2. **keyed `main` 面板**：客户端注册 `sidebar.panellist`（label `StudyUI Canvas`）+ `ctx.slots.register({ name: 'main', key: PANEL_ID }, Panel)`。
3. **iframe 面板可用**：点击侧栏入口后，`main` 面板渲染同源 iframe `http://127.0.0.1:7899/studyui/probe`，内容为 `StudyUI Canvas Probe`。
4. **命名空间安全**：所有 StudyUI 路由以 `/studyui/*` 前缀，不占用 DSH 的 `/api`；DSH 页面/连接正常，无 console 错误。
5. 标题守卫在面板切换后仍保持 `StudyUI`。

### 待 P5 完成

- Langflow dist 的 `<base href="/studyui/canvas/">` 改写与 SPA fallback。
- `/studyui/api` → 7881 的反向代理（POST body、SSE、取消）。
- 路径穿越防护、Host/Origin 校验、未授权 401/403 的自动化测试。
- 画布 bridge 的绝对 `/api` 路径改写。

---

## 5. 对原计划的修订

| 原假设 | 修订 |
|---|---|
| 品牌插件需要 tsdown/esbuild 构建链 | **不需要**：手写 lazy-CJS 即可；保留 `check-build` 校验 wrapper/依赖 |
| 仅 `tapIndex` 改标题即可 | 需要**客户端标题守卫**，因为 SPA 会回写 |
| 用 slot priority 覆盖官方品牌 | 更简单：直接 `disabled: true` 掉 `ui-brand-official` |
| 插件 bundle 直链可访问 | 走 combo URL；不要硬编码 `/plugins/<pkg>/client.js` |
| 画布同源代理可行但未验证 | 已验证路由 + `admit()` + iframe；Langflow 细节留 P5 |

## 6. 更新后的阶段

- **P0** 去风险 Spike（本文件，完成）
- **P1** `studyui-web` profile / DSH_HOME / DeepSeek 凭据
- **P2** 启动器：`start_demo.bat` → `dsh web`，7880 + 7881 sidecar，token 脱敏与生命周期
- **P3** StudyUI 品牌插件（名称/标题/Logo/manifest）
- **P4** MCP 科学工具 + DSH 原生审批
- **P5** 画布插件（`/studyui/canvas` + `/studyui/api`）
- **P6** 画布运行统一到 DSH 对话 + 单次审批
- **P7** 旧入口重建为 DSH 面板（五案例卡片、材料任务表单、工作流侧栏）
- **P8** 便携打包
- **P9** 测试 / CI 收敛
- **P10** 文档、清理、数据边界

## 7. P1 入口条件

- [x] DSH web 可启动且鉴权链路可用
- [x] 品牌插件路线可行（无构建链依赖）
- [x] MCP stdout 纯净方案可行
- [x] 画布面板 + 鉴权可行
- [x] 确认 P1 的 profile 命名（`studyui-web`）与 `start_demo.bat` 薄 bootstrap（密钥从 keyring 读取）

## 8. 实施进度

### P1 已完成（2026-11-26）

- `materials-quality/src/materials_quality/agent/dsh_web.py`：`studyui-web` profile 幂等创建、DSH_HOME 与 workspace 隔离、官方端点校验、keyring 取 key、环境剥离、token 脱敏。
- `scripts/setup_dsh.py --web` 与 `--check`：只读检查、幂等安装；`--check` 不再写 profile。
- 自动回退：激活模型非官方且只有一个官方 profile 时自动使用并打印提示；可用 `STUDYUI_WEB_MODEL_PROFILE=<id>` 固定。
- 单测：`test_dsh_web_profile.py` + `test_dsh_web_env.py` 共 12 项通过。

### P2 已完成（最小可用）

- `start_demo.bat` / `start_demo.sh` 默认传 `--web`；`start_demo.py --web` 直接启动 DSH Web。
- `--check` 只读；token 只打印脱敏 URL，日志同样脱敏；Ctrl+C/退出后释放端口。
- 源码模式自动用 `.demo-venv` 重新执行；便携模式直接使用内置 Python。
- 真实启动验证：ready 行、401、token 脱敏、端口释放均通过。
- Python sidecar 在 P5 接入（7881）。

### P3 已完成

- `dsh-plugins/studyui-dsh/`：
  - host：`tapIndex` 改写标题/manifest/favicon，注册 `/studyui/manifest.webmanifest`、`/studyui/favicon.svg`（`connection.admit()` 鉴权）。
  - client：`sidebar.brand.mark` / `sidebar.brand.name` + 标题守卫。
- `ensure_web_profile` 之外新增幂等 `install_studyui_plugin()`；禁用 `ui-brand-official`。
- 真实 Chromium 验证：`<title>StudyUI</title>`、侧栏 `S / StudyUI`、manifest `name=StudyUI`、favicon 200、未授权 401、无 console 错误。
- 单测：`test_studyui_brand_plugin.py` 5 项通过。

### P4 已完成

- `materials-quality/src/materials_quality/agent/mcp_server.py`：14 个紧凑工具，stdio JSON-RPC。
- 启动时预加载 numpy/pandas/scipy/matplotlib(Agg) 与全部科学模块，规避 Windows 上“事件循环内导入 C 扩展”的死锁；executor + `anyio.sleep` 轮询执行工具。
- fd1 重定向到 stderr，transport 保留原始 fd；业务输出不污染协议。
- 工具：`list/describe/run_science_operation`、`list/get/run_workflow`、`workflow_task_status`、`cancel_workflow_task`、`list/get_material_task`、`list/load_demo_dataset`、`inspect_table`、`studyui_info`。
- profile 通过 `@deepseek-ai/dsh-mcp-client` 独立行注册（`serverName: studyui`），与用户自建 MCP 服务互不覆盖。
- 验证：`--selftest`、原始 JSON-RPC、DSH 实际拉起 MCP 进程、科学操作 0.5s、workflow 后台任务完成。
- 真实模型 E2E（额度恢复后）：`mcp__studyui__studyui_info` 返回 `operation_count=48`；`mcp__studyui__run_science_operation(stats.distribution)` 返回成功并生成直方图/QQ 图。

### P5 已完成

- `start_demo.py --web` 先启动 Python sidecar（默认 7881）并等待 `/api/health`，再启动 DSH；`--backend-port` 可覆盖；退出时同时停止。
- host 插件：
  - `/studyui/canvas` 静态资源 + SPA fallback + `<base>`/API 重写；
  - `/studyui/api/*` → 7881 `/api/*`；
  - `/studyui/canvas/api/*` → `/canvas/api/*`；
  - `/studyui/api/v1/*` → `/canvas/api/v1/*`；
  - `/studyui/canvas/health(_check)` exact 代理；
  - `/studyui/ws` upgrade 代理（sidecar 当前无 WS 路由，保留扩展点）。
- client：`sidebar.panellist` + keyed `main` iframe 面板“工作流画布”。
- 验证：未授权 401、base/rewrite、health JSON、flows API 200、iframe 加载 Projects/New Flow、无 console 错误（仅 vendor Radix a11y warning）。

### P6 已完成（提示词桥接）

- canvas bridge 在嵌入时把“运行工作流”改为 `postMessage({type:'studyui-run-workflow', flowId})`；独立 `/canvas/` 仍走旧路径。
- 面板通过 `ctx.sessions` / `ctx.uiSession` 取当前 DSH 会话并 `prompt(..., 'queue')`，由 agent 调用 `mcp__studyui__run_workflow`。
- 验证：消息进入当前 DSH 会话，画布显示“已发送到 DSH 会话”；模型工具调用能力已由 P4 的真实 E2E 验证。画布运行请求在随后额度再次耗尽时未完成（QUOTA）。

### P7 已完成（入口重建）

- “材料任务”面板：18 张任务卡按 3 个任务组三列排布，示例数据五列平铺，顶部概览 pills；一屏内完成，无长滚动。
- “示例数据 · 五案例”：五个 demo dataset，点击后 agent 调用 `mcp__studyui__load_demo_dataset` 载入工作区并分析。
- “工作流画布”面板保留完整 Langflow 编辑器与 Projects/flows 侧栏。
- 未逐字段重建旧材料表单；由 DSH agent + MCP 工具按需补参（当前产品取舍）。

### 工作流管理与主题统一（2026-11-26 追加）

- 工作流管理改为 **DSH 面板内的原生列表**：新建/刷新/打开，显示所属项目与更新时间；不再显示 vendor 的 Projects 落地页/侧栏。
- 编辑器使用 DSH 顶栏（返回、流程名、所属项目、运行），保留左侧组件面板（节点库）。
- 隐藏剩余 vendor chrome：vendor 顶栏、Playground/Share、浮动“运行工作流”条、组件更新错误 toast、Flow needs review 浮层。
- 画布背景/表面/文本/边框/字体统一为 DSH；**主题跟随 DSH 的浅色/深色/跟随系统**：客户端读取 `body[data-ds-dark-theme]`（来源偏好 `html[data-ds-theme-source]`），通过 `postMessage({type:'studyui-canvas-theme'})` 同步到 iframe，切换 `#body.dark`、画布/节点/组件面板配色及面板顶栏，无需刷新；保留 StudyUI 品牌主色。
- DSH 代理转发 sidecar 时剥离 `Origin`/`Referer`，修复画布 PATCH 保存被 sidecar 同源中间件 403 的问题。
- 既有后台行为：`custom_component/update` 仍会返回 403（组件代码版本校验，旧 `/canvas/` 同样），其 UI 已隐藏，不影响流程加载与保存。

### P8 部分完成

- `build_portable.INCLUDE_DIRS` 已加入 `dsh-plugins`；`install_studyui_plugin(source=ROOT/dsh-plugins/...)` 支持便携布局。
- 待：实际 Windows 构建 + 离线 smoke。

### 节点表单压缩（2026-11-26 追加）

- 新增 `materials_quality/agent/node_layout.py`：数据/表格/来源/输出路径/ui_mode/config_json 与列选择器保持可见，其余可选参数折叠进 Advanced。
- 策略接入画布流 GET/列表（`workflow_api.public()`）与组件目录 `/api/v1/all`，已有节点与新增节点都生效；不修改组件代码、保存值或执行逻辑。
- `ResearchSkillPlanner` 增加任务感知核心字段：input_table/task/request + 本任务 4 个关键列；49 字段的节点默认只显示 7 个。
- 科学/可视化节点（如 `ScienceVizSpectra` 35 字段、`BatchSpectrumAnalyzer` 33 字段）默认只显示输入、来源与关键列。
- 画布内隐藏 vendor 的 Update required / Flow needs review / 组件错误 toast；sidecar 停止改为杀进程树，避免端口残留。

### 工作流可用性、加载与人类直接运行（2026-11-26 追加）

- **首次打开**：sidecar 启动时后台预热 LFX 组件目录；首次打开从约 8 秒降到 **1.3 秒**。
- **加载体验**：画布注入 StudyUI 品牌加载遮罩（S / StudyUI / 正在加载工作流…），覆盖 vendor 空壳/Langflow 痕迹；编辑器就绪后移除并向父页发送 `studyui-canvas-ready`；面板显示“正在加载…”，20 秒超时提供“重新加载”。
- **人类直接运行**：`POST /api/workflows/{id}/run` + 内存 FIFO 队列（单 worker、状态/结果/取消），不经过 agent；面板“直接运行”提交并轮询，显示“直接运行完成 / 查看详情”；运行记录在列表页可取消/打开。
- **模板**：`POST /api/v1/flows/{id}/copy` 从原始存储复制（避免画布句柄格式问题）；面板每行提供“复制”，复制示例后直接编辑。
- **Agent 联动**：保留“交给 Agent”（当前 DSH 会话调用 MCP `run_workflow`）；MCP 新增 `copy_workflow`，agent 可从模板创建工作流并运行。
- **人工画布权限**：浏览器创建/编辑/复制属于人工操作，不再受 agent 的 `per_action` 限制；`read_only` 仍拒绝直接运行。
- **示例提示词**：五个 demo 数据集改为动作优先的自然语言（“帮我算一下…/帮我比较…”）；面板发给 agent 的示例、材料任务、运行工作流提示词均不再包含 MCP 工具名、flow/dataset id 或操作码，由 agent 自行选择工具。
- **参考 ComfyUI**：采用队列、运行历史、取消、模板复制等交互，代码为原创实现；未复制 GPL 代码。

### 当前限制

- DSH 模型 E2E：`studyui_info`（48）与 `run_science_operation`（成功）已通过；画布运行 E2E 因额度再次耗尽未完成。
- 旧材料表单未逐字段重建；由 agent 驱动。
- 便携归档尚未实际构建验证。
- 画布 bridge 的“在 StudyUI 中查看完整报告”链接仍指向旧会话；P6 的 DSH 对话是权威结果面。
- DSH 内部文案（onboarding/settings 等）保留（按用户决定）。

### 运行方式

```bat
start_demo.bat                  :: DSH Web + StudyUI 品牌 + 画布/材料面板
start_demo.bat --check          :: 只读检查（含 7880/7881）
start_demo.bat --backend-port 7881
set STUDYUI_WEB_MODEL_PROFILE=<profile-id>
start_demo.bat                  :: 固定使用指定模型 profile
```

- 侧栏入口：工作流画布、材料任务。
- 激活模型非官方且仅有一个官方 profile 时自动回退并提示。


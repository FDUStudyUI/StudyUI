# MatOS 工具接入说明

本文说明 StudyUI 如何以只读目录的方式接入 [MatOS](https://github.com/DingyangLyu/MatOS) 的工具资产与调用方式，并保持 StudyUI 既有的 MCP、sidecar、资产图谱与治理接口不变。

- 目标：让智能体和治理视图可以发现、描述并按需调用 MatOS 工具。
- 非目标：不复制 MatOS 源码，不替代 MatOS runtime，不在缺少依赖时伪造成功。
- 来源快照：MatOS `distribution/benchmark-minimal`，commit `a50fd7613346a59f13e87a8bc368d0cec048585d`（2026-10-25）。

## 1. 工具目录

目录由 `scripts/build_matos_catalog.py` 从 MatOS 的 `asset.json`、`input.schema.json` 和 `prompt.md` 生成，产物为
`src/materials_quality/matos/catalog_data.json`。生成器只读取 JSON/Markdown，不导入、不安装、不执行 MatOS 代码。

目录共 **18** 个工具资产：**14 个外部工具**（有 `tool.py` 执行器与 `input.schema.json`）和 **4 个 builtin pack**。

| 工具 ID | 名称 | 类型 | 家族 | 调用方式 |
|---|---|---|---|---|
| `agent-orchestration` | Agent Orchestration | builtin pack | builtin-pack | MatOS asset MCP server |
| `atomistic-toolchain-catalog` | Atomistic Toolchain Catalog | external | atomistic-simulation | `matos assets run-tool` |
| `battery-electrochem-catalog` | Battery Electrochemistry Catalog | external | battery-electrochemistry | `matos assets run-tool` |
| `conda-environment-catalog` | Conda Environment Catalog | external | runtime | `matos assets run-tool` |
| `conda-environment-manager` | Conda Environment Manager | external | runtime | `matos assets run-tool` |
| `deep-research-search` | Deep Research Scholarly Search | external | deep-research | `matos assets run-tool` |
| `document-parse` | Document Parse (local files) | external | document | `matos assets run-tool` |
| `files-core` | Files Core | builtin pack | builtin-pack | MatOS asset MCP server |
| `gemini-vision-analyze` | Gemini Vision Analyze | external | multimodal | `matos assets run-tool` |
| `literature-access` | Literature Access | external | academic-research | `matos assets run-tool` |
| `local-toolchain-preflight` | Local Toolchain Preflight | external | local-toolchain | `matos assets run-tool` |
| `materials-runtime-inventory` | Materials Runtime Inventory | external | materials-runtime | `matos assets run-tool` |
| `mlip-model-catalog` | MLIP Model Catalog | external | mlip | `matos assets run-tool` |
| `mp-query` | Materials Project Query | external | mcp | `matos assets run-tool` |
| `scip-toolchain-catalog` | SCIP Toolchain Catalog | external | optimization | `matos assets run-tool` |
| `shell-core` | Shell Core | builtin pack | builtin-pack | MatOS asset MCP server |
| `web-read` | Web/PDF Read | external | web-research | `matos assets run-tool` |
| `web-research` | Web Research | builtin pack | builtin-pack | MatOS asset MCP server |

每个目录条目包含：名称、版本、描述、tags、权限声明、调用方式、执行入口、MCP 名称、超时、JSON input schema、必需/探测的二进制与 Python 包、必需环境变量、网络需求、来源路径与可用性策略。

### 必需依赖与探测项

`required_binaries` 是执行该工具本身必需的可执行文件；`probed_binaries` / `probed_python_packages` 是工具会检查的可选科研依赖，缺失时由 MatOS 返回结构化诊断，而不是 StudyUI 报假成功。

- `conda-environment-manager`：`conda`、`pip`。
- `conda-environment-catalog`：`conda`。
- `mp-query`：`MP_API_KEY`（网络）。
- `gemini-vision-analyze`：`GEMINI_API_KEY`（网络）。
- `atomistic-toolchain-catalog`、`local-toolchain-preflight`、`scip-toolchain-catalog` 等：探测 QE、LAMMPS、SCIP、xTB 等外部求解器；StudyUI 不要求安装这些求解器即可列出目录。
- builtin pack：只能由 MatOS asset MCP server 运行，`matos assets run-tool` 明确拒绝。

## 2. StudyUI 暴露的接口

### 2.1 MCP 工具（stdio）

`materials_quality.agent.mcp_server` 新增三个工具，stdout 仍只用于 JSON-RPC：

| 工具 | 作用 | 关键参数 |
|---|---|---|
| `list_matos_tools` | 列出目录与实时可用性 | `family`, `kind`, `tool_id`, `available_only` |
| `describe_matos_tool` | 返回完整定义与 input schema | `tool` |
| `run_matos_tool` | 校验输入并调用 MatOS CLI | `tool`, `input`, `timeout_seconds` |

`tool` 接受 `mp-query`、`tool:mp-query`、`tool:mp-query@1.0.0`、`mp_query` 或 `mcp__matos_asset__mp_query` 等写法。

### 2.2 sidecar REST

`materials_quality.agent.matos_api` 注册在现有 FastAPI sidecar 上，和 DSH Web 共用单端口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/matos/status` | 检测 `matos` CLI 与安装提示 |
| `GET` | `/api/matos/tools` | 目录列表，支持 `family`、`kind`、`tool_id`、`available_only` |
| `GET` | `/api/matos/tools/{tool}` | 单个工具定义 |
| `POST` | `/api/matos/tools/{tool}/run` | body 即 MatOS 工具输入对象；可用 `?timeout_seconds=` 覆盖超时 |

REST 与 MCP 共用 `materials_quality.matos.runner`，行为一致。POST body 必须是 JSON object，否则返回 422；未知工具返回 404。

### 2.3 资产图谱与治理

`build_default_asset_graph()` 会登记 18 个 `T:matos.<id>` 资产：

- `metadata.provider = "MatOS"`，`provider_repository`、`provider_license`、`provider_notice`、`source_commit`。
- `metadata.source_ref = "tool:<id>"`、`source_asset_path` 指向 MatOS 包内 `asset.json`。
- `metadata.category = "matos"`，`metadata.availability` 为 `requires_matos_cli` 或 `matos_runtime_only`。
- `required_binaries`、`required_env`、`network_required` 等依赖信息。
- `R:workflow_planner` 通过 `MOUNT` 边挂载全部 MatOS 工具资产，供规划/治理视图发现。

`/api/governance/scope` 返回 `matos_tools` 列表；`docs/scope-and-limitations.md` 包含自动生成的 MatOS 接入章节。

## 3. 调用约定

MatOS `run-tool` 的标准输入输出是 JSON object：

```json
// stdin input
{"formula": "SiO2"}
```

```bash
matos assets run-tool tool:mp-query --input-file - --json
```

StudyUI 的 `run_matos_tool` 先按 `input.schema.json` 做 Draft 2020-12 校验，再构造固定 argv：

```text
<matos> assets run-tool <tool-ref> --input-file - --json
```

不会使用 shell，也不会把用户输入拼进命令行。输入通过 stdin 传入，stdout/stderr 被捕获后解析。

成功结果保留 MatOS 的 `result`：

```json
{
  "ok": true,
  "status": "completed",
  "tool": "mp-query",
  "tool_ref": "tool:mp-query",
  "call_method": "matos assets run-tool",
  "exit_code": 0,
  "timed_out": false,
  "stderr": "",
  "result": {"count": 1, "entries": []}
}
```

## 4. 可用性与失败语义

CLI 检测顺序：

1. `STUDYUI_MATOS_CLI`（推荐，显式路径或命令名）。
2. `MATOS_CLI`。
3. `MATOS_HOME/bin/matos`。
4. `PATH` 中的 `matos`。

检测只使用 `Path.is_file()` / `shutil.which()`，不会执行候选程序。

`run_matos_tool` 的 `status` 可能为：

| status | 含义 |
|---|---|
| `completed` | MatOS 返回 `ok: true` 且进程退出码为 0 |
| `failed` | 输入合法，但 MatOS 工具返回 `ok: false` 或非零退出码 |
| `timeout` | 超过工具超时或 `timeout_seconds` |
| `unavailable` | 未找到 `matos` CLI，或 CLI 无法启动 |
| `matos_runtime_only` | builtin pack，不能通过 `run-tool` 执行 |
| `invalid_input` | 输入不是 JSON object 或不满足 schema |
| `not_found` | 工具 ID 未在目录中 |

所有失败都返回 `ok: false`、`error` 和（适用时）`install_hint`，不会返回伪造的 `result`。

安装提示：

```text
Install MatOS and expose its `matos` CLI on PATH, or set
STUDYUI_MATOS_CLI=/path/to/matos. StudyUI never vendors or executes the
downloaded MatOS source tree.
```

可选工作目录：`STUDYUI_MATOS_WORKDIR` 或 `MATOS_WORKDIR`，用于让 MatOS 从指定项目目录解析资产；未设置时继承 sidecar 进程当前目录。

## 5. 安全与许可

- 本仓库不复制 MatOS Python 源码；只复用工具名称、描述、权限声明与 JSON schema 等元数据。
- 下载的 MatOS 仓库被视为不可信数据：接入层不会自动执行克隆目录中的脚本。
- 外部工具调用固定 argv、无 shell、stdin JSON、输出有界；超时上限 3600 秒。
- MCP 业务输出不写 stdout；REST 仅绑定现有 loopback sidecar。
- MatOS 采用 PolyForm Noncommercial License 1.0.0。Required Notice：
  `Required Notice: Copyright 2026 The MatOS Authors (https://github.com/DingyangLyu/MatOS)`。
  完整声明见 `materials-quality/THIRD_PARTY_NOTICES.md` 与 `LICENSE`。

## 6. 测试

```bash
cd materials-quality
python -m pytest tests/test_matos_integration.py tests/test_asset_graph.py tests/test_mcp_server.py -q
```

覆盖：目录完整性（18/14/4）、别名解析、Draft 2020-12 schema 校验、缺少 CLI 的 unavailable 行为、builtin pack 拒绝路径、模拟 CLI 执行/失败/超时、MCP handler、REST 路由、资产图谱来源与 planner MOUNT。

测试不会调用真实 MatOS、也不会要求安装 QE/LAMMPS/SCIP 等求解器。

## 7. 重新生成目录

```bash
cd materials-quality
python scripts/build_matos_catalog.py \
  --matos-root /path/to/MatOS \
  --commit <matos-commit>
```

生成器只读取 MatOS `distribution/benchmark-minimal/assets/packs/**/tools/*/` 下的元数据文件。

# StudyUI harness evaluation (MatOS-style)

This is the reproducible harness comparison requested for the MatOS-style
evaluation. It is intentionally small and deterministic: six fixed materials
tasks, strict answer contracts, repeated runs, JSON/Markdown logs, and no judge
model.

## What the MatOS audit contributed

The public MatOS repository was cloned read-only into a temporary directory and
its documentation/scripts were read; its code was never installed or executed.
The adopted methodology comes from `docs/benchmarks.md`, the 28-asset
`distribution/benchmark-minimal` profile, and
`knowledge:materials-benchmark-task-pitfalls`:

- pin one model and one effort level for every harness;
- use a fixed materials/chemistry task set covering mechanics, XRD, thermal
  analysis, regression, battery cycling and data quality;
- score task success, numerical/evidence correctness and tool use separately;
- record turns, tool calls, latency and concrete failure modes;
- repeat runs and keep raw logs;
- record unavailable harnesses instead of inventing results.

MatOS itself is a third-party repository whose benchmark needs
`scripts/matos-setup.sh` (Bun), a provisioned DSH runtime, public
MatTools/SciAgentGym/ResearchClawBench data and its own credentials. The task
forbids installing/executing the GitHub clone, and the local machine lacks those
prerequisites, so the local probe reports MatOS unavailable. A separate,
pre-existing MatOS server was available through this machine's SSH config and
was later used read-only for the remote n=6 comparison below; the GitHub clone
was never executed.

## Model pinning

- Requested: **DeepSeek v4.1 flash**.
- Pinned id: `deepseek-flash` on `https://api.deepseek.com`.
- The official model listing on 2026-11-27 exposes `deepseek-flash` and
  `deepseek-v4-pro`; MatOS's benchmark scripts use `deepseek-flash` as the
  flash route. The OpenCode gateway also advertises `deepseek-v4.1-flash`; this
  benchmark uses the official id because the local DSH credential store already
  contains a verified official key, and it keeps every solver on one route.
- The key is read from `DEEPSEEK_API_KEY` or the existing
  `~/.dsh/.credentials.yaml`; it is never printed or written to a log.
- A tiny probe (`GET /models` plus one chat completion) is recorded in
  `probe.json`/`summary.json` on every run. If the route is unavailable, the
  report says so and harness failures are not scored as capability results.

## Harnesses

| Harness | What is run | StudyUI tools/prompts? |
|---|---|---|
| `studyui` | StudyUI's Python agent harness (`StudyUIAgent`, its registered tools, system prompt and skill preflight) | yes |
| `native_dsh` | The installed DeepSeek Harness headless profile (`dsh headless`) | no; no StudyUI MCP, prompts or project instructions |
| `claude_code` | Installed Claude Code CLI with `--bare`, pointed at DeepSeek's Anthropic-compatible route and `deepseek-flash` | no |
| `codex` | Installed Codex CLI using its existing DeepSeek V4.1 Flash provider configuration | no |
| `matos` (local) | No local MatOS binary; the local probe reports unavailable | n/a |
| `matos_remote` | Pre-existing MatOS server via the `matos-server` SSH alias, same six fixtures and model; read-only comparison in a new run directory | n/a (MatOS agent) |

The local 72-run table covers the first four harnesses. The remote MatOS
comparison is separate (n=6, one repetition) and is reported below; the local
`matos` row remains unavailable.

Availability is probed each run. A harness that is not detected or cannot reach
the pinned model is recorded with a reason and skipped.

## Fixed tasks

| Task | Domain | Deterministic target |
|---|---|---|
| `mechanics_modulus` | mechanics | E = 200 GPa, UTS = 500 MPa from a tensile CSV |
| `xrd_dspacing` | XRD | highest peak 35.4°, Bragg d = 2.534 Å at Cu Kα1 |
| `thermal_mass_loss` | TGA | 40.0% total loss, 60.0% residual mass |
| `arrhenius_activation_energy` | statistics | Ea = 0.8500 eV, R² = 1.000000 |
| `battery_retention` | battery | 80.0% retention at cycle 100, mean CE 99.70% |
| `data_quality_audit` | data quality | 3 missing cells, 2 duplicates, 2 negative, 2 high-temperature rows |

Fixtures live in `materials-quality/testfixtures/harness_bench/` and are
regenerated deterministically by `generate_fixtures.py`. Prompts are in
`tasks.json`; every prompt names the file path and columns and requires one
strict JSON object at the end.

## Scoring

Each run is scored deterministically:

- **Task success**: every numeric/integer/string check passes, every required
  evidence regex matches the final answer, a final answer exists, and the
  harness completed.
- **Numerical correctness**: fraction of numeric/integer/string checks passed.
- **Evidence correctness**: fraction of required evidence regexes passed.
- **Tool-use correctness**: at least one tool call plus the task's tool-evidence
  regex over the recorded tool transcript. This is separate from task success,
  so a lucky mental answer cannot claim tool-use credit.
- **Efficiency**: turns, tool calls, tool errors, latency and token usage where
  the harness reports them. Tool errors are recorded separately from task
  success: a harness can recover and still pass, but the error remains visible.
- **Turns are harness-defined**: StudyUI counts model requests (a tool-call
  request plus a final-answer request), while native DSH and Codex count one
  outer turn that may contain many tool calls. Read turns together with tool
  calls, tool errors and latency.
- **Failure modes**: timeout, harness error, no final answer, no JSON, wrong or
  missing value, missing evidence, no tool call, tool evidence mismatch.

No LLM judge is used.

## Reproducing

```bash
# Probe the machine and the model route (never prints keys).
.demo-venv/Scripts/python.exe materials-quality/scripts/evaluate_harnesses.py probe

# Minimal credible run: all available harnesses, all six tasks, one repetition.
.demo-venv/Scripts/python.exe materials-quality/scripts/evaluate_harnesses.py run \
  --harnesses studyui,native_dsh,claude_code,codex --repeats 1

# Final repeated run.
.demo-venv/Scripts/python.exe materials-quality/scripts/evaluate_harnesses.py run \
  --harnesses studyui,native_dsh,claude_code,codex --repeats 3

# Profile the StudyUI first-request context without model calls.
.demo-venv/Scripts/python.exe materials-quality/scripts/profile_harness_tokens.py
```

Raw artifacts are written below
`materials-quality/artifacts/harness-bench/` (gitignored). A run directory
contains `summary.json`, `summary.md`, `comparison.csv`, `aggregate.json`, and
per-run `request.json`, `result.json`, `score.json` and raw harness transcripts.
Only this document, the harness, fixtures and summarized results are committed.

## Results

- Run id: `final-fastpath3-3rep`
- Timestamp: 2026-11-26T20:00:31+00:00
- Git commit: `73e12f3325c5` (dirty=True)
- Model probe: available=True model_ids=['deepseek-flash', 'deepseek-v4-pro'] chat_latency_s=0.38
- Design: 6 tasks × 3 repetitions × 4 available harnesses.

### Overall

| Harness | Runs | Success | Numerical | Evidence | Tool use | Turns | Tool calls | Tool errors | Latency (s) | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| studyui | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 2.00 | 2.06 | 0.00 | 5.74 | 3404 |
| native_dsh | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 4.11 | 1.61 | 27.51 | 6715 |
| claude_code | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 3.72 | 2.72 | 0.00 | 7.53 | 2048 |
| codex | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 5.94 | 0.94 | 37.65 | 126245 |

### Per task

| Task | studyui | native_dsh | claude_code | codex |
|---|---|---|---|---|
| arrhenius_activation_energy | 1.00 (3) | 1.00 (3) | 1.00 (3) | 1.00 (3) |
| battery_retention | 1.00 (3) | 1.00 (3) | 1.00 (3) | 1.00 (3) |
| data_quality_audit | 1.00 (3) | 1.00 (3) | 1.00 (3) | 1.00 (3) |
| mechanics_modulus | 1.00 (3) | 1.00 (3) | 1.00 (3) | 1.00 (3) |
| thermal_mass_loss | 1.00 (3) | 1.00 (3) | 1.00 (3) | 1.00 (3) |
| xrd_dspacing | 1.00 (3) | 1.00 (3) | 1.00 (3) | 1.00 (3) |

Cells show task success rate and run count. Tool errors are recorded separately from task failure: a harness can recover and still pass, but the error remains visible.

### Failure modes and tool errors

- **studyui**: failures=none; runs with tool errors=0/18; mean tool errors=0.00
- **native_dsh**: failures=none; runs with tool errors=16/18; mean tool errors=1.61
- **claude_code**: failures=none; runs with tool errors=0/18; mean tool errors=0.00
- **codex**: failures=none; runs with tool errors=10/18; mean tool errors=0.94

### StudyUI optimization before/after

| Metric | Before (`final-3rep`) | After (`final-fastpath3-3rep`) | Claude Code (after) |
|---|---:|---:|---:|
| Task success | 1.000 | 1.000 | 1.000 |
| Numerical correctness | 1.000 | 1.000 | 1.000 |
| Evidence correctness | 1.000 | 1.000 | 1.000 |
| Tool use | 1.000 | 1.000 | 1.000 |
| Turns | 2.56 | 2.00 | 3.72 |
| Tool calls | 2.83 | 2.06 | 2.72 |
| Tool errors | 0.17 | 0.00 | 0.00 |
| Latency (s) | 11.72 | 5.74 | 7.53 |
| Input tokens/run | 36090 | 3404 | 2048 |

The optimization keeps every task passing while removing the redundant workflow/canvas context, the full skill texts and the unused workflow tool schemas from the direct-analysis path. Tool errors drop because the remaining battery/quality/regression/thermal config aliases are normalized or self-documented.

### Token composition (first request, tiktoken cl100k estimate)

| Component | Before | After | Change |
|---|---:|---:|---:|
| System prompt | 6,780 | 212 | -96.9% |
| Tool schemas | 5,763 | 782 | -86.4% |
| Skill preflight context | 3,493 | 84 | -97.6% |
| Folder authorization | 125 | 35 | -72.0% |
| User message | 171 | 171 | +0.0% |
| **Total** | **16,332** | **1,284** | **-92.1%** |

The after profile is measured by `profile_tokens.py` against the same mechanics task. The before profile is the same measurement on the pre-optimization harness. tiktoken cl100k is an estimate; the provider's own tokenizer differs, but the proportional change is the relevant result.

### Token accounting (harness-reported)

| Harness | Reported input | Cache-read | Total prompt tokens |
|---|---:|---:|---:|
| studyui | 3404 | 2681 (inside input) | 3404 |
| native_dsh | 6715 | 51819 | 58534 |
| claude_code | 2048 | 4800 | 6848 |
| codex | 126245 | 111424 (inside input) | 126245 |

StudyUI and Codex report cached prompt tokens inside `input_tokens`; Claude and native DSH report cache reads separately. The total column adds separate cache reads so the comparison is not biased by reporting convention.

### StudyUI vs native DSH

- Success: StudyUI 1.000 vs native DSH 1.000 (delta +0.000).
- Tool use: StudyUI 1.000 vs native DSH 1.000.
- Turns: StudyUI 2.00 vs native DSH 1.00.
- Tool calls: StudyUI 2.06 vs native DSH 4.11.
- Tool errors: StudyUI 0.00 vs native DSH 1.61 per run.
- Latency: StudyUI 5.74 s vs native DSH 27.51 s.
- Input tokens: StudyUI 3404 vs native DSH 6715 per run.

### StudyUI vs Claude Code

- Success: StudyUI 1.000 vs Claude Code 1.000.
- Tool use: StudyUI 1.000 vs Claude Code 1.000.
- Turns: StudyUI 2.00 vs Claude Code 3.72.
- Tool calls: StudyUI 2.06 vs Claude Code 2.72.
- Tool errors: StudyUI 0.00 vs Claude Code 0.00.
- Latency: StudyUI 5.74 s vs Claude Code 7.53 s.
- Reported input tokens: StudyUI 3404 vs Claude Code 2048 per run.
- Total prompt tokens (cache-aware): StudyUI 3404 vs Claude Code 6848 per run.

Claude Code's reported input token count excludes cache-read tokens, while StudyUI's includes cached prompt tokens; Codex's count is cumulative across its internal turn. The cache-aware total adds Claude/native separate cache reads, so the comparison is not biased by reporting convention. Raw counts remain a rough cost signal, not a billing statement.

The residual raw-input gap is Claude's lower reported count (2,048 vs 3,404) despite StudyUI's lower cache-aware total (3,404 vs 6,848): Claude excludes its 4,800 cache-read tokens and needs fewer prompt tokens per request, while StudyUI spends one extra completion to call a deterministic tool and sends the three analysis-tool schemas. Removing that structure would trade away tool-use correctness and the deterministic guards, so the gap is documented rather than optimized away.

### Pre-improvement StudyUI baseline

The same evaluator ran the pre-improvement harness from a detached worktree at the original commit (`fe4f109`) on representative tasks.

| Harness | Runs | Success | Numerical | Evidence | Tool use | Turns | Tool calls | Tool errors | Latency (s) | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| studyui | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 3.00 | 5.00 | 1.00 | 12.00 | 41367 |

| Task | studyui | native_dsh | claude_code | codex |
|---|---|---|---|---|
| data_quality_audit | 0.00 (1) | - | - | - |
| mechanics_modulus | 0.00 (1) | - | - | - |

### MatOS remote comparison (pre-existing server)

The local machine has no MatOS binary, so the local probe reports `matos`
unavailable. A pre-existing MatOS instance was available through the
`matos-server` SSH alias and was used read-only with the same six fixtures,
prompts, model family and deterministic scoring. No MatOS settings,
installation or upgrade were changed; the run only created a new directory
under `/root/yield-test/runs/` and new sessions. The provider key was sourced
from the server's existing `/root/.config/matos/matos.env` and was never
printed or copied.

**Verified environment**

- Ubuntu 24.04.5 LTS; `/opt/MatOS` at commit `a50fd7613346a59f13e87a8bc368d0cec048585d`, package `1.0.0`.
- Services listening on `127.0.0.1:17473` and `127.0.0.1:17474`; both `/health` probes returned HTTP 200.
- DSH runtime bundle `3da3e21aa6eb1def0ed0f35d5fb8d847`; model `deepseek-v4.1-flash`, provider `deepseek-official`, role `research-scientist`, context profile `full`, effort `high`, 45 tools and 15 selected assets (recorded in `matos.turn.context.assembled`).

**Exact command shape** (run in each task directory; the prompt was the same
fixture prompt used by the local suite):

```bash
export PATH="/root/.local/share/matos/toolchain/bun-v1.3.14/bin:/root/.local/share/matos/toolchain/node-v24.18.0-linux-x64/bin:$PATH"
set -a; source /root/.config/matos/matos.env; set +a
export MATOS_DSH_MODEL=deepseek-v4.1-flash MATOS_DSH_EFFORT=high
export MATOS_DSH_PROFILE=matos-yield MATOS_DSH_HOME=/root/yield-test/dsh-home
timeout 1800 /opt/MatOS/bin/matos run --role research-scientist \
  --context-profile full --max-turns 30 --model deepseek-v4.1-flash "$(cat prompt.txt)"
```

**Results** (6 tasks × 1 repetition; all answers were numerically correct):

| Task | Success | Numerical | Evidence | Tool use | Tool calls | Tool errors | Latency (s) | Prompt tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| arrhenius_activation_energy | 1 | 1.00 | 1.00 | yes | 7 | 0 | 29 | 197,113 |
| battery_retention | 1 | 1.00 | 1.00 | yes | 5 | 0 | 20 | 176,177 |
| data_quality_audit | 1 | 1.00 | 1.00 | yes | 11 | 0 | 45 | 371,751 |
| mechanics_modulus | 1 | 1.00 | 1.00 | yes | 12 | 1 | 46 | 493,983 |
| thermal_mass_loss | 1 | 1.00 | 1.00 | yes | 4 | 0 | 20 | 138,225 |
| xrd_dspacing | 1 | 1.00 | 1.00 | yes | 7 | 0 | 39 | 246,179 |
| **Mean / overall** | **1.000** | **1.000** | **1.000** | **1.000** | **7.67** | **0.17** | **33.17** | **270,571** |

MatOS records one outer turn per task but 11.33 model requests on average. Its
token total is the sum of DSH `inputTokens` and `cacheReadTokens` across the
task's sessions (including session-title/feedback overhead): mean input
71,681, cache read 198,891, output 3,336. The one tool error was an exploratory
shell call in the mechanics task; it recovered and still passed.

**Cross-harness comparison**

| Harness | n | Success | Tool use | Tool calls | Tool errors | Latency (s) | Prompt tokens/run |
|---|---:|---:|---:|---:|---:|---:|---:|
| StudyUI | 18 | 1.000 | 1.000 | 2.06 | 0.00 | 5.74 | 3,404 |
| Claude Code | 18 | 1.000 | 1.000 | 2.72 | 0.00 | 7.53 | 6,848 |
| Native DSH | 18 | 1.000 | 1.000 | 4.11 | 1.61 | 27.51 | 58,534 |
| Codex | 18 | 1.000 | 1.000 | 5.94 | 0.94 | 37.65 | 126,245 |
| MatOS (remote) | 6 | 1.000 | 1.000 | 7.67 | 0.17 | 33.17 | 270,571 |

StudyUI ties MatOS on task success, numerical/evidence correctness and tool use,
and beats it on tool calls (2.06 vs 7.67), tool errors (0.00 vs 0.17), latency
(5.74 vs 33.17 s) and prompt tokens (3,404 vs 270,571). MatOS uses a full
45-tool role/context composition and multiple model steps per outer turn; its
token accounting includes cache reads and auxiliary sessions, so the token gap
is partly a harness-architecture difference rather than a model difference.
MatOS used the `deepseek-v4.1-flash` id through the `deepseek-official` provider,
while StudyUI/native DSH/Claude used the official `deepseek-flash` id and Codex
used its local `ccs-opencode/deepseek-v4.1-flash` gateway. MatOS was run once
per task rather than three times; the local four harnesses retain the 3-repetition
table. The MatOS result files are under the gitignored
`materials-quality/artifacts/harness-bench/matos-studyui-20261127b/` and the
summarized numbers are in this table.

## Environment findings and blockers

- The official DeepSeek model listing returned `deepseek-flash` and
  `deepseek-v4-pro`; a one-request probe returned model `deepseek-flash`. The
  key was present in the DSH credential store and was never printed.
- StudyUI, native DSH and Claude Code used the official
  `https://api.deepseek.com` route with `deepseek-flash`. Claude Code used the
  Anthropic-compatible `/anthropic` route with `--bare`.
- Codex 0.167 no longer accepts `wire_api = "chat"` (its official
  configuration requires `responses`). DeepSeek's official endpoint is
  chat-completions, so Codex used its existing installed
  `ccs-opencode/deepseek-v4.1-flash` provider through the local
  Responses-compatible gateway. It is still the DeepSeek V4.1 Flash family,
  but the route is not byte-identical to the other three harnesses. A
  Responses-to-chat proxy would be needed for a strict same-endpoint Codex run.
- Native DSH's PowerShell tool hit a Windows sandbox ACL error
  (`windows-acl workspace grant failed`) repeatedly on this host. DSH
  recovered by reading the file and using its bundled diagnostic skill, and
  still passed the tasks, but recorded tool errors and extra tool calls. The
  benchmark kept `workspace-write` for comparability; StudyUI's direct tools
  did not hit this path. A full-access run or a repaired workspace ACL would
  remove the error but change the permission posture.
- The local machine has no MatOS binary, so the local probe reports `matos`
  unavailable. A pre-existing MatOS server (`matos-server` SSH alias,
  Ubuntu 24.04.5, `/opt/MatOS` commit `a50fd76`, ports 17473/17474 healthy)
  was used read-only for a separate n=6 comparison; no settings, installation
  or upgrade were changed. The server's existing provider env was sourced but
  keys were not printed or copied. The local 72-run table still excludes MatOS;
  the remote table is separate. The read-only GitHub clone used for methodology
  was never executed.
- The benchmark is small: six synthetic tasks, one model, three repetitions.
  The fixtures are deterministic and published with the harness, but the
  result should be read as a reproducible smoke comparison, not a general
  materials-science leaderboard.
- Token counts are harness-reported and not perfectly comparable: native DSH
  reports cached-input tokens separately, and Codex's input count is cumulative
  across its internal turn. The table uses the reported input tokens as a
  rough cost signal, not a billing statement.
- The final run used the working tree at commit `2d58f5a` plus the evaluator,
  role-allowlist and report refinements committed with this document
  (`dirty=True` in the run manifest). The exact code and fixtures are in the
  same commit as this report.
- The optimized `final-fastpath2-3rep` / `final-fastpath3-3rep` runs used the
  working tree at `73e12f3` plus the direct-analysis fast path, compact tool
  results and config normalization committed with this report. The six
  benchmark prompts all trigger that path (absolute file path plus a
  numeric/audit verb, no workflow verb). `final-fastpath2-3rep` is retained as
  the intermediate run that exposed the last thermal retry; the definitive
  reported run is `final-fastpath3-3rep`.

## Changes made to StudyUI

The pre-improvement StudyUI harness could inspect file structure but had no way
to read or compute on numeric data from an authorized file. On a smoke task it
answered `{"capacity": null}` after inspecting the CSV, because its only tools
were workflow-oriented. The benchmark identified this as a missing-tool gap,
not a model gap.

Changes implemented in this branch:

- Added `run_science_operation` to the dialogue harness: it runs an allowlisted
  deterministic science operation (mechanics, XRD, spectra, thermal,
  preprocessing, statistics, regression) on an authorized table and returns
  computed `data`, warnings and aggregate table summaries.
- Added `analyze_battery_cycles`: per-cycle battery capacity, retention and
  Coulombic-efficiency summary, including mean CE over cycles 2..N.
- Added `audit_table_quality`: deterministic missing-cell, exact-duplicate,
  negative-value and range-violation counts without modifying the source.
- Wired table-path authorization through the existing
  `_authorized_research_file` boundary and the read-only `data.inspect`
  permission action; operations that create files or move data are excluded.
- Kept the documented data boundary: the tools return computed fields and
  aggregate statistics, not raw measurement rows.
- Added concise system-prompt guidance to use the deterministic tools for
  numeric questions, to skip a redundant structure inspection when the user
  already supplied the path/columns/units, and to correct a reported
  configuration error once instead of repeating it.
- Added `available_columns` and required-field context to tool errors, and
  battery-column validation with actionable suggestions.
- Added the new tools to the characterization, data-quality and planner role
  allowlists so opt-in role routing does not hide them.
- Added a deterministic direct-analysis fast path: it detects a single
  authorized file plus a numeric/audit request, uses a compact system prompt,
  sends only the three direct-analysis tool schemas, keeps an audited but
  compact skill digest instead of the full skill texts, and returns compact
  tool results without the redundant derived table summaries.
- Normalized common operation config aliases (thermal `kind`/units, mechanics
  units, regression `validation_split`, distribution `columns`) and treated a
  battery `cell_id` value as a filter when it is not a column name. An
  unrecognized thermal `kind` now defaults to the operation's documented `tg`
  default with a normalization note. This removed the remaining recoverable
  battery/quality/regression/thermal tool errors.
- The intermediate fast-path run (`final-fastpath2-3rep`) exposed two thermal
  `kind` retries; the definitive `final-fastpath3-3rep` run after the default
  fix is the one reported in the Results tables.
- Tool-error steps now include the exception message, and config may be passed
  as a JSON string; both make recovery auditable and reduce blind retries.
- Added the fast-path, compact-result, alias-normalization and battery
  inference tests.
- Fixed the benchmark adapters to close stdin for external harnesses, separate
  tool errors from task failure, and avoid double-counting DSH cached tokens.
- Added deterministic unit tests for the new tools, scoring and prompt
  rendering.

The final report records the before/after comparison and any remaining gap.

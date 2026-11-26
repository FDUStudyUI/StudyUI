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
forbids installing/executing the clone, and none of those prerequisites were
present, so MatOS is reported as unavailable rather than run.

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
| `matos` | Not installed/authenticated; never executed | n/a |

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
```

Raw artifacts are written below
`materials-quality/artifacts/harness-bench/` (gitignored). A run directory
contains `summary.json`, `summary.md`, `comparison.csv`, `aggregate.json`, and
per-run `request.json`, `result.json`, `score.json` and raw harness transcripts.
Only this document, the harness, fixtures and summarized results are committed.

## Results

- Run id: `final-3rep`
- Timestamp: 2026-11-26T18:48:38+00:00
- Git commit: `2d58f5a094df` (dirty=True)
- Model probe: available=True model_ids=['deepseek-flash', 'deepseek-v4-pro'] chat_latency_s=0.29
- Design: 6 tasks × 3 repetitions × 4 available harnesses.

### Overall

| Harness | Runs | Success | Numerical | Evidence | Tool use | Turns | Tool calls | Tool errors | Latency (s) | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| studyui | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 2.56 | 2.83 | 0.17 | 11.72 | 36090 |
| native_dsh | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 5.11 | 1.56 | 31.05 | 6699 |
| claude_code | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 3.94 | 2.94 | 0.00 | 8.47 | 2070 |
| codex | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.00 | 7.06 | 1.00 | 42.00 | 149141 |

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

- **studyui**: failures=none; runs with tool errors=3/18; mean tool errors=0.17
- **native_dsh**: failures=none; runs with tool errors=16/18; mean tool errors=1.56
- **claude_code**: failures=none; runs with tool errors=0/18; mean tool errors=0.00
- **codex**: failures=none; runs with tool errors=11/18; mean tool errors=1.00

### StudyUI vs native DSH

- Success: StudyUI 1.000 vs native DSH 1.000 (delta +0.000).
- Tool use: StudyUI 1.000 vs native DSH 1.000.
- Turns: StudyUI 2.56 vs native DSH 1.00.
- Tool calls: StudyUI 2.83 vs native DSH 5.11.
- Tool errors: StudyUI 0.17 vs native DSH 1.56 per run.
- Latency: StudyUI 11.72 s vs native DSH 31.05 s.
- Input tokens: StudyUI 36090 vs native DSH 6699 per run. StudyUI pays for its larger system prompt and skill preflight, but it uses fewer tool calls and has lower wall-clock latency than native DSH, and its direct tools avoid the native DSH Windows ACL tool-error path.

### Pre-improvement StudyUI baseline

The same evaluator ran the pre-improvement harness from a detached worktree at the original commit (`fe4f109`) on representative tasks.

| Harness | Runs | Success | Numerical | Evidence | Tool use | Turns | Tool calls | Tool errors | Latency (s) | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| studyui | 2 | 0.000 | 0.000 | 0.000 | 1.000 | 3.00 | 5.00 | 1.00 | 12.00 | 41367 |

| Task | studyui | native_dsh | claude_code | codex |
|---|---|---|---|---|
| data_quality_audit | 0.00 (1) | - | - | - |
| mechanics_modulus | 0.00 (1) | - | - | - |

The baseline failure modes are concrete: mechanics stopped at a
`build_material_workflow` approval request and returned no numeric answer;
data quality lacked a deterministic quality-audit tool and missed the duplicate
count. The improved harness answers both directly and passes both 3/3 in
`final-3rep`.

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
- MatOS was not installed or authenticated. Running it would require
  `scripts/matos-setup.sh` (Bun), a provisioned DSH runtime, the public
  MatTools/SciAgentGym/ResearchClawBench data, and its own credentials. The
  task forbids installing or executing the read-only clone, so MatOS is
  reported as unavailable rather than faked.
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
- Fixed the benchmark adapters to close stdin for external harnesses, separate
  tool errors from task failure, and avoid double-counting DSH cached tokens.
- Added deterministic unit tests for the new tools, scoring and prompt
  rendering.

The final report records the before/after comparison and any remaining gap.

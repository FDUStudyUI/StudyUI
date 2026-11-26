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
- **Efficiency**: turns, tool calls, latency and token usage where the harness
  reports them.
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

_To be filled from the committed run. The final report records the exact run id,
model probe, availability, overall table, per-task table, failure modes and the
StudyUI-vs-native-DSH deltas._

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
  computed `data`, warnings and a bounded table preview.
- Added `analyze_battery_cycles`: per-cycle battery capacity, retention and
  Coulombic-efficiency summary, including mean CE over cycles 2..N.
- Added `audit_table_quality`: deterministic missing-cell, exact-duplicate,
  negative-value and range-violation counts without modifying the source.
- Wired table-path authorization through the existing
  `_authorized_research_file` boundary and the read-only `data.inspect`
  permission action; operations that create files or move data are excluded.
- Added concise system-prompt guidance to use the deterministic tools for
  numeric questions and to avoid claiming that numeric data is unreadable.
- Added deterministic unit tests for the new tools and their schemas.

The final report records the before/after comparison and any remaining gap.

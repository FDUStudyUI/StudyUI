# Research reliability V2 implementation plan

> **For agentic workers:** Use superpowers:executing-plans for integration and superpowers:dispatching-parallel-agents for disjoint scientific, contract and evaluation domains. Each change follows red/green verification; one independent whole-change review precedes delivery.

**Goal:** Implement V2 correctness fixes, an independently scored spectral evaluation and a minimal transferable scientific data contract, keeping ordinary operation in Langflow forms.

**Architecture:** Extend existing scientific functions and the two research components; preserve legacy feature aliases and 62-node discovery. A versioned semantic contract travels in table metadata and result/batch envelopes and is explicitly bound into research plans. Independent analytic generators score against known parameters rather than copying the analysis implementation.

**Tech Stack:** Python 3.10, existing pandas/SciPy/Pint/LFX/Langflow dependencies; pytest, Ruff and Playwright. No shared-environment installation or editor rebuild.

**Spec:** `docs/superpowers/specs/2026-11-03-research-reliability-v2.md`, sections 3–6, 9–11 (snapshot of user-approved V2). User explicitly requested direct implementation of correctness, independent evaluation and minimal contract. Autonomous repair loops and broad performance rewrites are outside this increment.

## Global constraints

- Continue isolated `feat/research-skills` workspace; submit updated PR #6, do not merge main.
- Preserve original data, identifier types, legacy `lambda10_*` aliases and pre-existing workflows; legacy physical candidates never become confirmed mode assignments.
- Existing table-fingerprint algorithm remains versioned and unchanged; semantic contract gets its own canonical SHA-256.
- One curve may contain repeated curve IDs across different coordinates; sample and independent-unit roles may share a column when they represent the same entity.
- Low-sample and degenerate inference must be explicit; curve count alone never establishes independence.
- Model proposals remain allowlisted and cannot grant scientific confirmation.
- No arbitrary code execution, downloads of private experimental data or automatic external messaging.

## Review focus

1. Candidate rules produce different outputs on a true competing-peak case; aliases and units remain consistent downstream.
2. A window-external strong peak cannot silently alter an explicitly configured threshold; legacy adaptive behavior remains identified as such.
3. Singleton/constant bootstrap, small independent units and nested curves produce honest estimability states.
4. Semantic changes invalidate cached plans even when numeric data stay identical; contracts survive batch serialization, execution, frontend save/reopen and file export.
5. Legal same-column entity roles and long-table repetitions are accepted while incompatible roles, cross-group identities and wrong-granularity inference are rejected or restricted to description.

## Task 1 — Spectral numeric correctness (disjoint domain)

**Files:** `science/materials_curves.py`, `science/materials.py`, `science/spectrum_batch.py`, new `tests/test_spectral_reliability.py`.

**Interfaces:** Existing `analyze_spectra(table, config)` and `peak_records(x,y,config)` remain callable. Config gains `prominence_mode` (`legacy_relative`, `absolute`, `noise_reference`), `noise_window` in native x units, `noise_multiplier`, optional `peak_distance_x`; existing `prominence` still explicitly overrides implicit legacy selection. Candidate rule uses existing `lambda10_selection` internally. Add canonical candidate aliases (`window_candidate_nm`, `selection_rule`, `candidate_count`, `ambiguous`, `detection_status`) and group completion/detection counts. Any bootstrap interval records status/reason and is withheld for n<3 under the documented default policy or degenerate empirical resampling.

- [ ] Write and observe failures for singleton interval, threshold interference, rule/alias consistency, physical spacing and nonuniform coordinates.
- [ ] Implement minimal numerical fixes with explicit diagnostics; no automatic mode assignment.
- [ ] Run new and existing spectrum/materials regressions; report compatible interfaces.

## Task 2 — Minimal semantic contract (disjoint domain)

**Files:** new `science/table_contract.py`; `science/langflow_adapter.py`; `batch/packet.py`; new `tests/test_table_contract.py`.

**Interfaces:** `make_contract(table, *, granularity, roles, experimental_design=None, aggregation=None, derived_from=None, units_state=None) -> dict`; `read_contract(table) -> dict|None`; `attach_contract(table, contract) -> DataFrame`; `contract_identity(table) -> str|None`; `propagate_contract(source, target, operation, parameters=None) -> DataFrame`. Schema `studyui-table-contract/1`, table attrs key `contract`; canonical JSON hash. Roles are named column strings and can legally share compatible entity columns. Explicit semantic input checking, no numeric ordering of granularities. Contract-preserving single-table operations and safe aggregation/history; incompatible/unknown transformations safely clear/restrict semantics with provenance, never invent independence. Batch serialization explicitly preserves and validates the contract. Research plan integration belongs to Task 4.

- [ ] Observe failure for metadata-only fingerprint changes, same-column entity roles and serialization roundtrip.
- [ ] Implement bounded validation/hash and pure attach/propagate functions; preserve legacy no-contract behavior.
- [ ] Integrate scientific result envelope and batch transport; test mismatches/tampering and old workflows.

## Task 3 — Independent evaluation (disjoint domain)

**Files:** new `evaluation/` module, `scripts/evaluate_reliability.py`, new `tests/test_reliability_evaluation.py`, optional fixed evaluation manifest/example files. Do not edit Task 1/2 files.

**Interfaces:** Deterministic analytic spectrum generators return input and independent ground truth, split dev/holdout by mechanisms/parameter cells and seeds. Evaluation compares legacy-relative, explicit threshold and declared-noise strategies with both candidate rules. Include out-of-window interference, competing peaks, edges, nonuniform grid/noise, invalid inputs and legitimate IDs. CLI produces per-case CSV/JSON, aggregate metrics with denominators and uncertainty where justified, environment/version/seed/config and source hashes. Default 200–500 scored tasks, minimal deterministic test subset. No assumed accuracy target fabricated after seeing holdout.

- [ ] Add failing generator/score/split tests, verify failures.
- [ ] Implement real function execution scored against analytic truth and independent acceptance tolerances.
- [ ] Run frozen dev/holdout evaluation, retain failures and costs; output honest ranges rather than universal promises.

## Task 4 — Research integration, inference and visual forms (root)

**Files:** `skills/planning.py`, `skills/native.py`, `skills/tasks.py`, `skills/model.py`, `skills/execution.py`, `skills/reporting.py`, components under `materials_skills`, relevant `science/catalog.json` and form schema, new focused tests.

**Interfaces:** Native candidate rule/threshold/noise/physical-distance controls; optional curve→sample/independent-unit declaration with explicit confirmation. Contrast task allows compatible `sample_id == experimental_unit`; small n default descriptive path, explicit model-based small-n opt-in when scientifically declared. Add original-unit group difference CI with design-aware aggregation via existing functions and no pseudoreplication. Plans include input contract identity and the effective analysis contract; no-contract legacy plans must be regenerated. Result tables/feature contracts reflect actual grain and never infer physical mode or experimental independence from curve count. Model suggestions cannot confirm new scientific conditions.

- [ ] Write red tests for stale-contract plans, legal role alias, group counts/difference CI and native rule changes.
- [ ] Implement and test all API/CLI/form paths, attach contracts to output tables and bind caches.
- [ ] Update examples with unchanged old expectations and add competing-peak, small-sample and nested-unit demonstrations.

## Task 5 — Delivery verification and PR

**Files:** version metadata, docs/research-reliability.md, acceptance/evidence index, example builders, CI workflow, scripts/ui_skill_acceptance.py or focused V2 UI script.

- [ ] Run targeted red/green checks then full regression, Ruff, graph examples and ordinary wheel install/discovery.
- [ ] Run real isolated UI: configure rules/threshold through controls, no JSON typed; save/reopen; compare candidates; show small-n status, units and contract in reports.
- [ ] Run frozen independent holdout evaluation and record interpretation/limits. Validate links and report files.
- [ ] Obtain independent review; fix important findings with regression tests; verify final exact commit.
- [ ] Commit/push, update PR #6 description/title and await exact-head test/ui CI; ready for review, no merge.

Progress is recorded locally in `.superpowers/sdd/2026-11-03-research-reliability-v2/progress.md`.

# Research Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver three bundled research skills with validated plans, deterministic execution, native Langflow forms, optional model suggestions and reproducible examples.

**Architecture:** A versioned plan binds the input table and skill bundle. Only registered scientific tasks execute; native nodes and CLI share planning and execution. Model output is an untrusted proposal validated by this same contract.

**Tech Stack:** Python 3.10, pandas, existing SciPy/matplotlib scientific functions, LFX/Langflow 1.13, standard-library HTTP, pytest and Playwright.

**Spec:** `docs/superpowers/specs/2026-11-03-research-skills-design.md`

## Global Constraints

- Python 3.10; no upgrades to shared environments or breaking old ports.
- Units, spectral windows, mechanics fit intervals and statistical design require explicit inputs.
- Raw data preserved; stale or altered plans rejected; reports escaped and all artifacts hashed.
- Bundled skills work from a normal wheel. Model is optional and cannot execute arbitrary code.

## Review Focus

- Ambiguous columns must block rather than silently select the first alias.
- A changed table, units metadata, skill or plan must invalidate execution.
- Missing candidates and failed samples must retain identity and not become zeros.
- Model proposals must reject extra keys, forbidden parameters and unknown tasks without leaking secrets.
- Native inputs must remain visible and preserve values after serialization/import.

### Task 1: Registry and plans

**Files:** `src/materials_quality/skills/{registry,planning}.py`, bundled `resources/`, `tests/test_research_skill_plans.py`.

**Interfaces:** `list_skills()`, `load_skill(id)`, `inspect_skill(path)`; `make_plan(table, task, request, parameters, proposal)`, `validate_plan(table, plan)`.

- [ ] Test missing metadata, unsafe paths, ambiguous mappings, required units and data/plan tampering; watch failures.
- [ ] Implement bundled registry, schema proposals, explicit validation and signed-content fingerprints.
- [ ] Verify tests, then commit.

### Task 2: Scientific execution and deliverables

**Files:** `skills/{execution,tasks,reporting}.py`, `tests/test_research_skill_execution.py`.

**Interfaces:** `execute_plan(table, plan, output_dir=None)` returns result object with table/features/curves/groups/report/artifacts/summary.

- [ ] Test 8 spectra (16 peaks, candidate means 715/755), mechanics E=200000 and yield≈202.01, technical replicate aggregation and raw preservation.
- [ ] Implement task dispatch through existing functions, figures, self-contained HTML, CSV and manifest; preserve failure rows.
- [ ] Test missing candidates, degenerate studies and plot warnings; commit after green.

### Task 3: Optional model and CLI

**Files:** `skills/model.py`, `skills/__main__.py`, `tests/test_research_skill_model_cli.py`.

**Interfaces:** `suggest_plan(table, request, ...)` feeds strict model proposals to `make_plan`; CLI lists/previews/plans/runs.

- [ ] Test local fake HTTP service, payload contains schema/summary only, response limits, failure handling and no-key mode.
- [ ] Implement bounded requests and CLI without automatic installs or arbitrary actions.
- [ ] Verify CLI execution and safe errors; commit.

### Task 4: Native components and examples

**Files:** `components/materials_skills/{research_planner,research_executor}.py`, native helper, `scripts/build_skill_examples.py`, `tests/test_research_skill_components.py`.

**Interfaces:** Planner emits Data plan + Message; executor accepts plan and table, emits result/features/curves/groups/report/artifacts/summary.

- [ ] Test native code loading, form field visibility, cache changes, graph JSON roundtrip and all three runnable examples.
- [ ] Implement task-specific native fields and portable workflows; update discovery checks and documentation.
- [ ] Verify with real browser and ordinary wheel; commit.

### Task 5: Full verification and review

**Files:** Chinese guide, source/compatibility records, CI additions and skill evaluation cases.

- [ ] Run full regression, Ruff, executable examples, wheel discovery and real UI acceptance.
- [ ] Fresh whole-branch review; fix important findings and rerun relevant verification.
- [ ] Push feature branch, create PR, verify exact-head CI and report scope accurately.

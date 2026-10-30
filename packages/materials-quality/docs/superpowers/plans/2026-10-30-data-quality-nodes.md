# Langflow data quality nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver six non-destructive Langflow quality checks, an aggregator, tests and an executable sample flow.

**Architecture:** Deterministic pandas/Pint check functions with native Langflow component adapters. Typed DataFrame and Data outputs preserve graph compatibility; no LLM calls are needed.

**Tech Stack:** Python 3.10+, pandas 2.x, Pint 0.24.4, lfx 1.13.0, pytest, ruff.

**Spec:** docs/superpowers/specs/2026-10-30-data-quality-nodes-design.md

## Global Constraints
- Input tables and their index are never mutated.
- Configuration errors raise ValueError.
- Initial verification target: lfx==1.13.0, Python 3.10+, pandas 2.x, Pint 0.24.4.
- No guessed units, no automatic conversion.
- Publish a feature branch/PR to the confirmed destination; no merge is implied.

## Review Focus
- Duplicate/non-integer indexes: findings use stable row positions (Task 1).
- Empty tables and zero reports: no misleading all-clear (Task 1).
- Unknown/ambiguous units, affine temperatures: explicit findings/errors (Task 2).
- Non-finite, constant, small-group numbers: no invalid thresholds (Task 2).
- UI import and exported graph: exercise actual LFX, not mocked ports (Task 3).

### Task 1: Report contract, schema, missing, types and duplicates
**Files:** src/materials_quality/{common,checks,aggregate}.py; tests/test_checks.py; pyproject.toml.
**Interfaces:** check_schema/check_missing/check_types/check_duplicates(table, explicit keyword configuration) -> dict; aggregate_reports(reports, finding_limit=500) -> dict.
- [ ] Write hand-derived behavioral tests, including missing aliases, zero rows,
  repeated indexes, strict datetime/category rules and full duplicate groups.
- [ ] Run pytest tests/test_checks.py; expect failures because check functions do not exist.
- [ ] Implement common report builder and these checks, without changing source tables.
- [ ] Run pytest tests/test_checks.py; expect all pass; commit.

### Task 2: Units and outliers
**Files:** src/materials_quality/{units,outliers}.py; tests/test_units_outliers.py.
**Interfaces:** check_units(table, source_units, expected_units, columns=None, finding_limit=500) -> dict; check_outliers(table, columns, method, bounds=None, multiplier=1.5, mad_threshold=3.5, group_by=None, finding_limit=500) -> dict.
- [ ] Write independent MPa/Pa, Celsius, inline mixture, constant MAD, IQR,
  grouped-baseline, malformed-parameter and non-finite tests.
- [ ] Run pytest tests/test_units_outliers.py; expect missing-feature failures.
- [ ] Implement dimensional checks and non-destructive outlier flags.
- [ ] Run complete pytest suite; expect all pass; commit.

### Task 3: Native nodes and executable example graph
**Files:** components/materials_quality/*.py; src/materials_quality/langflow_support.py; scripts/{build_example,run_example}.py; tests/test_components.py; examples/*.
**Interfaces:** six check components output table, findings and report; aggregator consumes Data list and outputs Data, findings DataFrame and Message. Outputs grouped explicitly.
- [ ] Write integration tests using actual lfx component objects, custom-code loading
  and graph deserialization; assert field/row findings rather than template wording.
- [ ] Run integration tests; expect missing-component/graph failures.
- [ ] Implement adapters, fixtures and graph generation/execution scripts.
- [ ] Execute exported workflow with LFX; expect six completed checks, dirty-data
  findings, clean-data behavior and preserved input; run full suite; commit.

### Task 4: Delivery and review
**Files:** README.md; docs/contract.md; CI; dependency lock; verification notes.
- [ ] Document install, loader path, provisional compatibility, each node's fields,
  output contract, fixture origin and scientific limitations.
- [ ] Run full pytest, lint, package build, fresh-install/example verification.
- [ ] Obtain one independent whole-change review; fix significant issues with
  regression tests and rerun checks.
- [ ] Commit, publish to confirmed group repository branch/PR, read back remote
  files/commit and report exact delivery state.

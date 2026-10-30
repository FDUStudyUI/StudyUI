# Shared data quality implementation plan

> **For agentic workers:** Use superpowers:executing-plans, implement tasks in order with test-first behavior and one final independent review.

**Goal:** Deliver shared quality rules, traceable reports, an executed mechanics case and real Langflow UI acceptance.

**Architecture:** Existing pure checks remain intact. A context/dispatch module adds immutable rule binding and non-destructive missing-value views; thin native adapters consume it. Generated graphs remain self-contained JSON.

**Tech Stack:** Python 3.10, pandas 2.x, Pint 0.24.4, LFX/Langflow 1.13.0, pytest, Playwright.

**Spec:** ../specs/2026-10-30-shared-quality-design.md

## Global constraints

- Preserve original data and indexes; no automatic cleaning or unit conversion.
- Use native Langflow components; no frontend fork or cloud model required.
- Synthetic data must be explicitly labeled; file metadata is a declaration, not authenticated provenance.
- Existing pure-check API and legacy report support remain compatible.

## Review focus

- Equal-sized tables with different values or row order must not share a summary.
- Context or source edits and stale rules must be detected before execution.
- Missing sentinels must not enter type/unit/statistical baselines.
- Repeated specimens under different conditions/replicates are legitimate.
- UI acceptance must exercise the real served application, not an imitation page.

### Task 1: Shared context and report traceability

Files: src/materials_quality/context.py, aggregate.py; tests/test_context.py.
Interfaces: make_context(table, rules, source=None, rule_set_id='custom', rule_set_version='1'); run_check(table, check_id, parameters=None, context=None, finding_limit=500).

- [x] Write failing tests: stable/changed fingerprints, invalid/tampered rules/context, sentinel exclusion, source identity, cross-table/rules summaries and legacy policy.
- [x] Run pytest tests/test_context.py; confirm missing API/behavior failures.
- [x] Implement typed hashing, validated context, shared execution and strict traced aggregation.
- [x] Run full pytest and commit.

### Task 2: Native integration and mechanics case

Files: components/materials_quality/quality_context.py and __init__.py, src/materials_quality/langflow_support.py; examples/mechanics/*, scripts/build_mechanics.py, tests/test_mechanics.py, scripts/verify_install.py.
Interfaces: MaterialQualityContext.build_context -> Data; every check receives optional quality_context Data; build_mechanics creates portable flows with summary ID MaterialQualitySummary-demo.

- [x] Write failing native-loader/context port and mechanics expected-finding tests (clean/dirty/corrected and legitimate repeats).
- [x] Run those tests; confirm expected failure.
- [x] Implement native integration and deterministic case assets, manual correction record, full six-check graphs, expected manifest.
- [x] Run entire suite, native stored-flow and wheel discovery checks; commit.

### Task 3: Real UI acceptance and submission

Files: scripts/ui_acceptance.py, docs/ui-acceptance.md, docs/contract.md, README.md, verification.md, .github/workflows/materials-quality.yml.
Interfaces: Langflow 1.13.0 loopback service; Playwright browser real UI; screenshot and JSON evidence.

- [x] Install isolated Langflow UI, launch bound to 127.0.0.1, import and run stored cases using actual browser controls; test an error and inspect screenshots/results.
- [x] Correct any discovered defects using reproducing tests; document exact environment and acceptance evidence.
- [x] Run lint, full tests, stored-flow execution and clean wheel verification; independent review; fix important findings.
- [ ] Push feature branch, create PR to the team repository and verify GitHub CI and remote commit.

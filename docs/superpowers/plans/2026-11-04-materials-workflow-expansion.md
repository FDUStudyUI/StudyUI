# Materials workflow expansion

> **For agentic workers:** Execute the independently testable domains in parallel, then integrate and request independent review.

**Goal:** Associate experiment results by specimen safely, apply traceable calibration, and provide electrical/photoresponse and battery-cycle workflows.

**Architecture:** Reuse the V2 table semantics, native forms, batch execution and reports. Extend safe joins and calibration through existing operations. Group genuinely new calculations into one electrical node and one battery node. Deliver connected examples, analytic tests and real-data comparisons with documented sources.

**Tech stack:** Python 3.10, pandas, SciPy, LFX 1.13, pytest, Playwright, GitHub Actions.

- [x] P0 association: strict specimen master joins, duplicate/missing/cardinality evidence, unit and grain checks, native forms and regression tests. Keep existing generic merge compatible.
- [x] P0 calibration: explicit blank/reference/linear calibration, per-group repeatability, preserve units and source evidence, visual controls, regression tests.
- [x] P1 electrical: per-curve I–V fitting and step photoresponse metrics with explicit windows, validated units and structured features, native form and analytic tests.
- [x] P2 battery: use battery cycling as the initial P2 track. Per-cell discharge capacity, retention, optional comparable charge efficiency, native form and analytic tests. Independently compare against a public instrument dataset.
- [x] Integrate importable workflows demonstrating cross-instrument association, calibration of a second modality and battery cycling. Retain synthetic/real-data distinctions and evidence.
- [ ] Run lint, meaningful domain/graph tests, full regression, wheel/component discovery and browser validation. Review, commit and push. Check GitHub workflow results for the submitted SHA.

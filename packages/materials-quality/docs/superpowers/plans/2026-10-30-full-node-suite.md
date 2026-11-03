# Complete materials node suite implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for independent domains, TDD for behavior changes and independent reviews before integration.

**Goal:** Implement all fifty entries and all submethods in 工作流节点.md, integrate native Langflow nodes and deliver tested connected examples.

**Architecture:** Preserve existing quality API. Add a shared NodeResult contract, pure domain operations, declarative catalog and independently loadable native adapters. Domain implementation runs in separate files concurrently; parent integrates and validates.

**Tech Stack:** Python 3.10, Langflow/LFX 1.13.0, pandas/Pint, SciPy/scikit-learn/statsmodels, matplotlib/scikit-image, PyMuPDF/pdfplumber/RapidOCR, requests.

**Spec:** ../specs/2026-10-30-full-node-suite-design.md

## Global constraints

- All fifty source entries and listed submethods are acceptance criteria.
- Preserve original data/files and existing public node/check APIs.
- No fabricated scientific, OCR, reference or literature results.
- Deterministic offline CI plus separately verified live-service smoke tests.
- Source and generated text assets use LF, UTF-8; hashes remain portable.

## Review focus

- Malformed/ambiguous files, unsupported formats and OCR failures must not silently yield success.
- Calibration, units and grouping must accompany quantitative scientific results.
- Paired tests, train/test leakage, multiple comparisons and invalid baselines require explicit handling.
- Literature claims require valid source spans and identifiers.
- Native port types, file uploads, wheel discovery and connected execution must be verified beyond core functions.

### Task 1: Shared contracts and requirement ledger

Files: science/contracts.py, tests/test_science_contracts.py, docs/requirements-matrix.json, docs/development/full-suite-progress.md.
Interfaces: NodeResult, require_table, numeric_matrix, artifact_path, read_path as in spec.
- [x] Write/observe failing contract tests, then implement utilities.
- [x] Generate fifty-entry matrix preserving source subrequirements and assign all operation keys.
- [x] Run baseline and contract tests, commit.

### Task 2: Data sources and extraction

Files: science/io_nodes.py, science/extract_nodes.py and owned supporting files; tests/test_science_io*.py, tests/test_science_extract*.py; docs/science-io.md.
Interfaces: twelve operations in spec, CATALOG metadata, NodeResult.
- [x] Implement via failing tests first, including actual generated PDF/image/database fixtures and HTTP test service.
- [x] Verify supported instrument formats and plugin conversion, OCR/table/chart calibration and every source submethod.
- [x] Review domain and record test evidence.

### Task 3: Statistics, models, figures and report exports

Files: science/statistics.py, science/visualization.py and support files; owned tests/docs.
Interfaces: fourteen operations in spec; no fitting before data split; read-back artifact checks.
- [x] Implement all statistical/multiple-comparison/regression/predictive/evaluation methods with independent numeric expectations.
- [x] Implement every plot family and CSV/Excel/templated report exports; verify contents and figure data.
- [x] Review domain and record evidence.

### Task 4: Materials analysis

Files: science/materials.py and supporting files; tests/test_science_materials*.py; docs/science-materials.md.
Interfaces: six operations in spec; explicit calibration/reference inputs.
- [x] Implement full XRD/spectral/thermal/mechanics/image submethods using analytic synthetic truth.
- [x] Verify fits, known peak widths/areas/modulus/yield/integral/morphology and reference matching, with appropriate degeneracy errors.
- [x] Review domain and record evidence.

### Task 5: Preprocessing, literature and quality gaps

Files: science/preprocessing.py, science/literature.py, quality extension modules and owned tests/docs.
Interfaces: twelve new operations plus backwards-compatible quality extensions.
- [x] Implement explicit auditable table transforms and all missing quality submethods with regression tests.
- [x] Implement search/metadata/evidence extraction/comparison/source records/grounded summaries; deterministic fixtures and public API smoke.
- [x] Run and review tests.

### Task 6: Native nodes and complete validation

Files: science/catalog.py, science/langflow_adapter.py, generated components, scripts/build_science_examples.py, tests/test_science_components.py, examples/science, README, CI, pyproject/locks.
Interfaces: fifty-entry requirement matrix; fifty-two formal components including existing context/summary; portable graphs and artifacts.
- [x] Write failing catalog/native loader/port/flow tests, implement adapters and generate forty-four components.
- [x] Build connected cross-domain examples covering all categories and validate every node/method, dependency absence paths and artifact readback.
- [x] Full suite, lint, wheel, real UI imports/runs; independent final review and verified fixes.
- [x] Update capability matrix and beginner docs, submit repository PR and verify CI/remote readback.

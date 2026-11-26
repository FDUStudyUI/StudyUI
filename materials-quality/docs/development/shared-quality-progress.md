# Execution ledger — 2026-10-30-shared-quality.md

Baseline: b57e8fb, 92 tests passed in package directory. Initial root-directory pytest used the wrong pythonpath and failed collection; rerun in the documented package directory passed. Remote has only main at b57e8fb, no origin/main tracking ref locally; worktree branched from verified HEAD.

Pre-flight: Task 1 context output is consumed by Task 2 native adapters and mechanics graph; shared rules override node parameters; no conflict. Task 2 graphs and installed component set are consumed by Task 3 UI/wheel acceptance; discovery count becomes eight. Existing examples keep manual configuration and gain local provenance.

Ruling: user explicitly authorized implementing the proposed improvements and submitting tested work; continue without another design approval question. Use an isolated worktree and feature PR.

Task 1: in progress.

Final independent review: four Important findings (NumPy temporal/int fingerprint collision; columns=None sentinel handling; explicit empty missing-token list; pandas timedelta compatibility), no Critical or Minor findings. All reproduced RED, fixed together by preserving typed temporal values and passing missing semantics explicitly into pure checks. 125/125 full suite passed, lint passed. Reviewer separately executed committed mechanics JSON files: 0/8/0 findings.

Ruling: replace temporary masking with explicit optional missing_tokens parameters in pure types/units/outliers — authoritative shared semantics and exact values are more important than avoiding small backwards-compatible API additions; default legacy semantics preserved. Unsupported exotic scalar objects still fail closed with a clear hashing error.

Ruling: review exclusions are accepted boundaries: source-file authenticity is not claimed, mechanics data are synthetic, Tool Mode/new UI features remain outside the user-selected scope. Real browser acceptance remains required and in progress, not waived.

Wheel verification: regular 0.2.0 install in separate verification environment discovered eight nodes and executed all five stored flows, including 0/8/0 mechanics findings. The uv-created verification environment has no pip module; use uv pip install --python, not python -m pip.
`nTask 1/2: implemented, 118 tests passing; RED shared context 21 failures -> GREEN; native/mechanics 4 failures -> GREEN. Corrected serialization edge IDs before connection and explicitly preserved object values when masking missing sentinels (large-int regression RED -> GREEN). Fixture manifest includes both incompatible and mixed unit warnings. Task 3 in progress: isolated real UI installation.

Current suite: 128 passed, lint clean, regular wheel verified eight components and five stored graphs. Browser install bottleneck traced to pythonhosted download route; an Aliyun PyPI mirror throughput probe was 1 MiB in 1.14 seconds, so switch only the isolated UI installer to that mirror.

Task 1: complete. Task 2: complete. Task 3 local acceptance: complete.
Final verification: original environment 128 passed / 4 upstream warnings, full UI environment 128 passed / 7 upstream warnings, Ruff clean, fresh wheel eight components / five stored flows. Real Chrome UI 0/8/0, expected failure/restoration, no page errors/API HTTP failures; screenshots inspected. 17 wheel/core/component files matched source SHA-256. GitHub PR and CI verification pending.

Delivery regression: Windows CRLF -> Git LF normalization changed source/evidence byte digests. Three checkout-simulation tests reproduced failures. Normalized case CSVs and generated JSON to LF, regenerated all case manifests and reran real UI. Final result: 131 passed in both environments (4/7 upstream warnings); lint and wheel five-flow verification passed. UI 0/8/0 and invalid-rule recovery passed; source/report/file digests agree.

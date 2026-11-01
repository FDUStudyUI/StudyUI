# Batch processing and native input implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for disjoint tasks and fresh review.

**Goal:** Process multiple files or grouped specimens with one reusable native-form flow.
**Architecture:** A typed batch Data envelope carries isolated item tables and reports through the existing science adapter.
Three batch components handle input, shared quality rules and collection; safe opt-in migration upgrades old JSON controls.
**Tech Stack:** Python3.10, Langflow/LFX1.13.0, existing pandas/scientific stack, pytest, Playwright.
**Spec:** docs/batch-design.md.

## Global constraints

- Preserve existing main checkout/running environment and all52original components.
- Raw files, units, numerical algorithms, source hashes, precision and legacy JSON semantics remain intact.
- Native forms for ordinary use; no mandatory JSON or per-sample graph duplication.
- No deleting team workflow nodes without the actual supplied graph. No automatic merge of this new PR.

## Review focus

- Full curves, not rows, are independent jobs; never mix specimens in a fit.
- Failed jobs and absent tables remain distinguishable from successful empty results.
- No cross-job cache, rule, filename or output-directory contamination.
- Legacy form migration must not introduce differing defaults or model task routing.
- Multiselect uploads and conditional field refresh must work in real Langflow1.13, including asynchronous selection.

## Tasks

- [x] A: RED codec/source tests; implement batch.packet and batch.source with native source component.
  Verify precision/dtypes/index/attrs roundtrip, duplicate filenames, grouped keys, limits and item errors.
- [x] B: RED migration tests; implement --prefer-forms, science/quality native conversion and clear fallbacks.
  Verify safe default old mode, current JSON nodes, old native nodes, model inference and connected outputs.
- [ ] Parent: RED per-item execution/cache/output tests; integrate science adapter and create batch quality/collector components.
  Verify20item numeric parity, one-error isolation, output identity and original nodes/flows.
- [x] C: concise stable public docs; archive development notes, fix relative links and preserve necessary scientific scope.
- [ ] Parent: build fixed-size batch examples, actual native multi-file/grouped-table browser acceptance and regression coverage.
- [ ] Fresh independent whole-branch review; fix reproducible findings, full suite/Ruff/wheel and legacy flow checks.
- [ ] Push feature branch, create PR, verify exact-head remote test/ui checks. Record CI status in PR and handoff.

## Additional research requirements from the team

- [x] D: complete-curve spectrum task, peak features, per-curve/group summaries and explicit-window λ₁₀ candidates.
  Paper definition: coupled lowest-energy plasmon resonance, not a ten-percent threshold. No universal 710 nm setting.
- [x] E: SeriesDynamics, ContrastStudy, BatchImageAnalyzer and multi-key grouped statistics, with independent experimental units.
- [ ] F: bounded instrument-array browsing/reading (HDF5, NetCDF, Zarr), selected axes and channel quality.
- [ ] G: chronological holdout, walk-forward blocked CV, model comparison and declared residual/trend intervals.
- [ ] H: safe derived columns, per-group normalization and spectral mean/band plots.
- [ ] Parent: feature ports, schema-aware unit propagation, native compact fields, portable examples and browser acceptance.

Canvas grouping, generic cross-node schema subscriptions and a custom tree widget require Langflow editor changes.
Component deliverables use native field refresh, typed outputs, task descriptions and reusable example workflows;
they must not claim modifications to upstream editor behavior.

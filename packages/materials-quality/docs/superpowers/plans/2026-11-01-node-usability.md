# Node usability implementation plan

> **For agentic workers:** use superpowers:subagent-driven-development for isolated domain tasks and fresh review.

**Goal:** Make all supported nodes practical for beginners without mandatory JSON and correct their ports.
**Architecture:** Declarative per-operation field/port contracts feed native Langflow controls and one validated
configuration composer. Keep legacy JSON loading explicit and preserve numerical and provenance contracts.
**Tech Stack:** Python 3.10, LFX/Langflow 1.13.0, existing scientific dependencies, pytest, Playwright.
**Spec:** `docs/node-ui-design.md`.

## Global constraints

- All existing 50 source entries and 52 formal components remain available.
- Do not change raw data, scientific definitions, source hashing, units or key redaction.
- No JSON required for ordinary workflows; expert JSON remains an explicit advanced/legacy path.
- Work in `feat/node-ui-v2`; retain the user's main application and data.

## Review focus

- A form default must not overwrite a legacy JSON value, including false/zero/empty values.
- Hidden method-specific values must not leak into another method's execution.
- Genuine empty tables and no-table operations must remain distinguishable.
- Saved old flows and regenerated portable flows must execute with correct provenance.
- Controls must render and execute in real Langflow, not only Python unit tests.

## Tasks

- [x] Parent: RED tests for typed controls, effective config precedence, capabilities and no-table behavior;
  implement `ui_types.py`, `ui_schema.py`, ports and adapter/generator integration.
- [x] Domain A: `ui_specs_materials.py`, `ui_specs_visualization.py`, domain tests: controls/contracts for
  materials, four figure nodes and two export nodes. No numerical code or common adapter changes.
- [x] Domain B: `ui_specs_statistics.py`, `ui_specs_literature.py`, domain tests: all statistical and literature
  operations, including method-dependent controls. No numerical/common changes.
- [x] Domain C: `quality_ui.py`, original eight quality components/support and focused tests: shared rule form,
  per-check controls and explicit legacy JSON compatibility. No science adapter changes.
- [x] Parent: IO/extraction/preprocessing specs, generator output and catalog contracts; migration tool,
  regenerated examples, native integration and old-flow reproductions.
- [x] Fresh independent review; fix reproducible issues. Full pytest, Ruff, wheel and real browser tests.
- [x] Document usability inventory and limitations; push branch/create PR.

Completion gate: verify both remote jobs for the final head of PR #4. The live GitHub Checks and final handoff
record that outcome; this plan is a pre-CI implementation snapshot.

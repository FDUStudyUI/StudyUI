# Publication plotting implementation plan

**Goal:** Apply reusable MCM/CUMCM scientific visualization principles to the existing Langflow nodes.
**Architecture:** Shared Matplotlib styling/export helper; preserve all scientific computations and input rows.
**Backend:** Existing Python/Matplotlib, no skill-path dependency in installed code.

The user's earlier direct-execution preference continues; use the existing workflow without a new design approval gate.
Style-only adaptation: restrained semantic colors, redundant marks, readable final sizes, transparent uncertainty,
source integrity and real visual QA. Competition paper layouts/page counts are outside this change.

## Figure contract

Quantitative plots explain observed comparisons or diagnostics. No new causal conclusions or significance tests.
Input DataFrame and existing numeric plot_data remain the source of truth. Physical units follow declared/table
metadata. Explicit synthetic examples have a visible label. Comparisons preserve every observation.

Default preview output remains PNG and existing explicit formats stay valid. `profile: paper` uses a 150 mm
canvas, editable vector text, PNG/SVG/PDF/600 dpi TIFF, a machine-readable figure card and caption. It does not
claim real experimental validation. Color/marker identity is stable across plots; explicit color_map overrides it.

## Work

- [x] RED tests: stable semantic styles, no global Matplotlib/RNG leak, editable vector text/final dimensions,
  four-format readback, source fingerprint/precision, visible synthetic identity, uncertainty definitions.
- [x] Shared style/export helper and plotting integration, including distribution histogram/Q-Q.
- [x] Improve raw-observation overlays, specimen grouping/legend, zero-centered correlation, prediction/residual labels.
- [x] Paper gallery with data/config/captions; inspect contact sheet, full-resolution and final-size previews.
- [x] Native workflow/report integration; no duplicate TIFF/PNG previews; regenerate portable examples.
- [x] Independent review, focused and full regressions, wheel; CI configured for updated PR #3.
  Final remote check status and readback are verified after push and reported in the task delivery.

## Risks to check

No per-process font/color state leak between threaded Langflow nodes; no missing glyphs hidden in publication exports;
no clipped legends/annotations or misleading small-sample KDE; no disappearing observations; no labels claiming units
that disagree with values; exact numeric plot_data unchanged; old PNG-first artifact contract retained.

Local complete: 432 regression tests; nine real browser flows; six figure bundles and independent review passed.
Locked environment: 430 passed; final remote CI status remains visible on PR #3.

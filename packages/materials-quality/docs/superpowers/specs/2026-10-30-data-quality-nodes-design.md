# Materials data quality components

## Approved scope
The user requested the previously proposed six Langflow data-quality checks and one
report aggregator, with tests, an executable example flow, and submission to the
FDUStudyUI GitHub group. The source backlog is preserved in `docs/reference-workflow-nodes.md`.
The private destination FDUStudyUI/StudyUI and local Git access have been verified.

## Design and alternatives
Use independent Python checks with thin native Langflow Component adapters. This
keeps numerical behavior testable without a model, and tests integration against
the real pinned LFX runtime. A single monolithic checker would hide per-check
configuration; a bespoke REST protocol would add a second integration contract.
The user selected native Langflow components in the preceding discussion.

## Runtime and packaging
- Initial verification target: lfx==1.13.0, Python 3.10+, pandas 2.x, Pint 0.24.4.
- This is a provisional tested target, not the team's confirmed deployment version.
- New isolated local Git repository on feat/data-quality-nodes; no existing worktree
  or user code is modified. Later integrate into the provided team repository.
- Install the Python package, and point LANGFLOW_COMPONENTS_PATH at `components`.
- Each category contains __init__.py. Each node is a direct Component subclass.
- Input tables and their index are never mutated. Table outputs use lfx DataFrame;
  structured reports use lfx Data; the aggregate also exposes a Message summary.
- Configuration errors raise ValueError. Detected quality problems are completed
  checks with findings, never execution failures disguised as successful results.

## Report contract
schema_version, check_id, execution_status, passed, dataset dimensions, metrics,
total_findings, returned_findings, truncated, findings and parameters. Findings
have code, severity, column, zero-based row_position, original row_index and a
human-readable reason. A bounded preview does not change full counts/verdicts.
Raw index labels cannot replace row_position because labels can repeat.
No checks, failed/unavailable checks and empty input must not yield an all-clear.

## Seven components
1. Schema: required columns, explicit aliases, ambiguous aliases and missing fields.
   Aliases are reported without renaming input columns.
2. Missing: actual nulls and explicitly configured tokens; per-column, per-row,
   optional group counts and missing-pattern summaries. Blank strings default to missing;
   scientific strings such as NA are not assumed missing unless configured.
3. Types: explicit number/integer/string/boolean/datetime/category rules. Date parsing
   uses an explicit format. Missing cells are left to the missing check. No coercion
   is written back. Reject non-finite numbers and bool-as-number.
4. Units: explicit source/expected units and inline quantities, dimensional
   compatibility and mixed-unit flags. No guessed units, no automatic conversion.
   Absolute temperature units must be parsed correctly. Unknown metadata is a
   configuration error; unknown inline units produce findings.
5. Duplicates: full rows or explicit key columns, flag every member of a duplicate
   group; repeated experiments remain data, not records to delete automatically.
6. Outliers: explicit numeric columns, physical bounds, IQR or MAD; optional groups.
   Non-numeric/non-finite values and insufficient baselines are reported. For zero
   MAD, flag deviations from the repeated median and record this fallback.
7. Aggregate: combine valid reports, reject malformed reports, retain per-check
   results and bounded findings, and explicitly represent no-check/empty input.

## Acceptance
- Hand-calculated numerical fixtures, parameter rejection, duplicate indexes,
  preservation of input, missing tokens, datetime format, incompatible and offset
  units, non-finite values, constant data, small groups and truncation.
- Real Langflow/LFX component loading and execution, outputs/ports verified.
- Importable flow JSON generated from native component templates; execute the
  exported graph through the runtime, assert actual report contents, no API keys.
- Clean-table, dirty-table and invalid-configuration examples with clear provenance
  (hand-authored test fixtures, not real experimental data).
- README in Chinese, setup, contract, limitations and reproducible test commands.
- Publish a feature branch/PR to the confirmed destination; no merge is implied.

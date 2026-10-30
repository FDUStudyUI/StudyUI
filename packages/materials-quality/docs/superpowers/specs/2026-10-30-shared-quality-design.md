# Shared rules, traceability and mechanics demonstration

User authorization: implement the three improvements selected in chat, test them and submit to FDUStudyUI/StudyUI. No additional approval gate is needed for routine implementation choices.

## Approach and scope

Keep the existing pure checks and native Langflow adapters. Add one native context node rather than duplicating rules in six nodes or introducing a separate service. The context binds a frozen JSON ruleset and declared source metadata to a typed SHA-256 table fingerprint. Each check accepts the same optional context. Without a context, existing node settings still work and gain table traceability. Pure-function legacy reports remain readable but explicitly have unverified provenance.

Shared rules are authoritative when connected: checks must be explicitly configured, unknown fields are errors, missing tokens apply consistently to value checks through explicit optional parameters, and grouping is taken from the shared rules. No value replacement is performed. Duplicate identity columns remain unchanged. Statistical checks are for review, never automatic deletion.

## Contract

Context schema `materials-quality-context/1`: dataset descriptor (rows, columns, fingerprint), source metadata (dataset_id, source_name, optional declared source_sha256), rule_set_id, rule_set_version, rules_sha256, rules. Rules schema: `missing_tokens`, `group_by`, `checks` keyed by schema/missing/types/units/duplicates/outliers, with keyword arguments of existing pure functions. Per-check missing_tokens/group_by overrides are rejected in shared mode. Finding preview limit remains node-local.

Reports retain v1 fields and add provenance: mode (shared/local), dataset descriptor, source, full effective rules/check parameters and fingerprints. Summary rejects mixed datasets, shared rulesets, shared/local modes or traced/legacy envelopes, and duplicate check IDs. Legacy-only summaries explicitly state provenance is unverified. No signature or proof of file authenticity is claimed: table fingerprint binds in-memory values, declared source digest records user metadata.

## Mechanics case

Provide deterministic synthetic tensile-test records for specimens at 25/80 degrees Celsius, with specimen, condition and replicate identifiers. Legitimate repeats are allowed; duplicate complete measurement identities are flagged. Include clean, dirty and researcher-corrected variants, source CSV digests, explicit rules and an expected-finding manifest independent of executing checks. Inject a missing sentinel, format error, incompatible inline unit, duplicate identity and within-condition outlier. Preserve raw data, record manual corrections separately and recheck. All numbers and thresholds are educational, not a physical standard or real laboratory measurement.

## Acceptance

Existing 92 tests remain passing. New regression tests cover input/rule edits invalidating context, stable deep-copy fingerprints, original index/order preservation, source/rule tampering, cross-dataset aggregation, shared sentinel consistency, repeated measurements and grouped thresholds. Real Langflow 1.13.0 UI must discover nodes, import workflows, render connected ports, run checks and expose results, including an intentional error. Capture screenshots, browser console and machine-readable acceptance results. Verify wheel and CI; submit a feature branch and PR rather than overwriting shared main.

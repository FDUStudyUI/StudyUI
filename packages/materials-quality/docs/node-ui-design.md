# Node usability redesign

The November 1 review identifies real usability defects: all scientific nodes share generic ports,
every normal operation requires JSON, and missing table results masquerade as empty tables.
The user requested direct implementation and a documented usability improvement inventory.

## Decisions

- Keep Python 3.10 and Langflow/LFX 1.13.0. Do not change scientific algorithms or raw data.
- All 44 scientific operations receive native, operation-specific controls: choices, numeric values,
  column selectors accepting custom names, lists, key/value mappings and structured editable tables.
  Complex exceptional options remain available in advanced JSON, with explicit configuration mode.
- Include the eight original quality/context/summary nodes: normal shared rule editing and common
  checks must work without JSON. Connected shared rules remain authoritative.
- Ports follow operation capabilities. Distinguish actual data inputs from optional provenance context.
  Report export and selected multi-source operations accept report collections; only real file readers expose file upload.
  Never expose an always-absent table output. A requested unavailable conditional table fails clearly.
  Native unit checking exposes converted_table only after explicit opt-in; blocked conversion raises.
  Legacy JSON retains flagged unavailable tables solely for existing report-chain compatibility.
- Preserve old saved JSON configuration and existing port identifiers where meaningful. New forms have
  an explicit mode; direct legacy config_json-only callers keep their original settings. Provide a migration
  tool and regenerate supported workflows; do not silently discard unsupported old edges.
- Use meaningful icons, Chinese help, good defaults, method-dependent visibility and actionable validation.
  Candidate column names may be refreshed when table/file metadata is available; custom names remain
  possible. Do not claim automatic cross-node column discovery when Langflow has not supplied metadata.
- Cache identity, source hashes, units, secrets redaction and full-precision data remain intact.
- Keep the running user's original main environment and saved flows intact. Test an isolated app instance.

## Acceptance

All operations have native form definitions verified through SDK construction and serialization.
Representative actual UI acceptance covers upload, image import, preprocessing, mechanics, plotting/report export and
shared-quality rules without typing JSON. A mechanics graph has typed
strain/stress selectors, unit dropdowns and elastic interval bounds. Image import offers image metadata,
never a fake empty table. All 50 source requirements, 52 formal components and scientific outputs remain.
Native graph roundtrips, legacy compatibility, wheel install, original examples, nine connected science
flows, and real browser actions must pass. Document implemented improvements and bounded follow-ups.

## Shared schema interface

`ui_types.field(path, label, kind='str', *, default=None, choices=(), advanced=False, info='', when=None,
required=False)` returns a JSON-compatible descriptor. Paths use dotted dictionary keys. Kinds are
`str`, `list`, `int`, `float`, `bool`, `choice`, `dict`, `range`, `table`, `json`.
`range` is a pair of optional numeric controls; `dict` is a native key/value editor; `json` is advanced only.
`when` maps controlling config paths to allowed values, e.g. `{'method': ['range']}`.
UI names are `cfg_` + path with dots replaced by underscores (ranges append `_min` and `_max`).
Optional descriptor keys may include `table_schema`, `converter`, `suggestions` if an actual need exists;
coordinate additions before changing the shared interface.

Domain modules export `SPECS: dict[str,list[dict]]` and `CONTRACTS: dict[str,dict]`. Contracts use
`table_output: bool`, `artifacts_output: bool`, `upload_types: list[str]`, `icon: str`; conditional table
availability can additionally declare `table_methods` with its controlling `method_path`.
The parent owns common construction/composition, capabilities, generator and integration.

# SDD ledger — plan: docs/superpowers/plans/2026-11-01-node-usability.md

Base: 0262f0d; branch feat/node-ui-v2; user authorized review changes and usability improvements directly.
Existing direct-execution preference applies; no new design/merge approval is requested.

## Pre-flight

| Tasks sharing interface/files | Producer / consumer | Ruling |
|---|---|---|
| Parent / domain A+B | ui_types.field descriptors / common schema composer | Freeze contract in spec; domains own only assigned specs/tests. |
| Parent / domain C | SDK runtime / eight quality nodes | Separate quality_ui helper; parent does not change langflow_support.py. |
| Generator / adapter / migration | new fields and stable port IDs / old JSON workflows | Explicit mode; compatibility tests before regeneration. |
| Domain contracts / parent ports | table/artifact/upload availability / native outputs | No invented empty table; conditional absence must fail clearly. |
| Each domain task / its tests | form config reproduces existing pure operation inputs | No scientific algorithm changes. |
| Parent / browser | serialized controls / real UI render and run | Validate both schema and actual interaction. |

## Progress

- GitHub connector can read organization/private PR; local main and origin/main match.
- Review reproduced by source inspection: generic I/O and empty DataFrame fallback.
- Skills: receiving-code-review, brainstorming (prior direct-execution opt-out), writing-plans,
  using-git-worktrees, test-driven-development, parallel agents and requesting-code-review.
- Four domain implementations cover 44 science operations and eight original quality nodes.
- Initial full run: 488 passed, two interface regressions found; focused regression run after fixes: 36 passed.
- Independent review reproduced seven issues (unset numeric coercion, numeric list types, old JSON defaults,
  repeated list values, delimiter whitespace, serialized visibility, refresh controllers); fixes under re-review.
- Multiple-source provenance is retained only on report export, multi-table merge, model prediction,
  XRD reference/instrument analysis, performance and statistical plots; ordinary nodes do not expose this port.
- Native unit conversion now hides converted_table unless explicitly enabled and rejects unavailable conversion;
  legacy JSON keeps flagged unavailable tables solely for existing report-chain compatibility.
- Separate real UI acceptance runs on loopback 7871 with fresh headless Edge; user's 7860 app is untouched.
- Safe flow migration preserves original files and custom code, validates every replaced-node edge,
  and reports unsupported parameters rather than silently dropping them.
- Real UI mechanics passed: actual CSV upload 401 rows, native column/unit/range edits,
  elastic modulus 200000 MPa, yield stress 202.01005025125627 MPa, seven edges retained and HTML PNG decoded.
- Browser import exposed hidden connected provenance port removal; serialized connected ports now remain visible.
- All nine example factories now produce forms for all 50 pre-report scientific nodes plus nine report nodes;
  conservative parameter import retains exact JSON fallback if explicit values cannot be represented.
- Migration tests use a compact static baseline fixture ZIP, avoiding Git-history dependence in shallow CI clones.
- Version 0.4.0; CI includes real native-form acceptance in addition to original quality/science UI runs.
- Full regression, rebuilt nine-flow numerical oracles, wheel installation and final independent review in progress.
- First integration passed 534 tests, nine numerical flow oracles, all nine science browser flows,
  three original quality browser cases and four new native-form browser cases. Wheel discovery found52nodes
  and all five original stored workflows passed; installed wheel also executed all nine science flows.
- Fresh review then found task selectors could be overridden by upstream model/vectors; native dispatch now
  enforces the selected task and records it in cache/provenance. Six new core regressions passed (29 core tests total).
- Visual QA prompted explicit field order, including lower before upper bounds. Final rebuild/retest follows.
- Final verification passed: 555 tests in162.71s, Ruff clean; rebuilt nine flows/44operations/148edges,
  read back57artifacts and rechecked11fixture hashes. Final regular wheel discovers52nodes and runs
  five original plus nine science graphs. After final server restart, browser four form cases,
  nine science flows and three original quality cases all passed. Machine evidence and screenshots saved.
- Independent closure review found no actionable remaining issues. GitHub push/PR and exact-head CI pending.
- PR #4 submitted. First remote run passed core tests (549 passed; optional UI modules/CJK font skipped),
  science rebuilds, wheel, original quality UI and all nine science UI flows. New-form upload selection exposed
  an asynchronous auto-select/toggle race in the acceptance harness, reproduced deterministically and fixed.
- After the fix, all four real native-form cases passed again and the full local suite passed556tests in156.22s.
  Production components remain unchanged by this harness fix; final remote checks run against the updated PR head.

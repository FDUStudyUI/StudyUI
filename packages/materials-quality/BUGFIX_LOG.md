# Verified bug-fix ledger

Only independently reproducible defects with a regression test and a passing
verification run are counted. Test-fixture corrections and feature work are not
counted. The requested 100-fix target is a goal, not a claim that has already
been met.

**Verified fixes: 112 / 100 target** (rounds 2–3; see the sections at the end)

## 001 — Permanent model HTTP errors were retried

- **Reproduction:** `tests/test_agent_model_retry.py::test_authentication_error_is_not_retried`
  returned HTTP 401 six times with exponential waits, although changing a key or
  endpoint is required to recover.
- **Root cause:** every `HTTPError` was treated as transient by the retry loop.
- **Fix:** retry only HTTP 408, 425, 429, and 5xx responses; permanent client
  errors fail immediately. Same-origin redirects remain supported.
- **Regression verification:** `pytest tests/test_agent_model_retry.py -q` —
  **21 passed**.

## 002 — Stale workflow approvals were consumed before validation

- **Reproduction:** `tests/test_harness_controls.py::test_changed_workflow_invalidates_approval_before_execution`
  changed a workflow after requesting approval. The approval was marked approved
  before the stale digest was checked, sending an invalid authorization into the
  workflow failure/recovery path.
- **Root cause:** approval state was committed before checking the exact workflow
  snapshot.
- **Fix:** validate the snapshot first and explicitly invalidate stale approvals.
- **Regression verification:** the name-change cases in the targeted harness
  control tests passed.

## 003 — A cross-project approval did not bind the workflow's project

- **Reproduction:** `tests/test_harness_controls.py::test_changed_workflow_invalidates_approval_before_execution`
  and `::test_cross_project_approval_is_invalidated_if_flow_moves_during_dispatch`
  moved an approved workflow to another project, including between approval
  validation and dispatch.
- **Root cause:** the approval digest omitted `folder_id`; cross-project
  authorization was tied to the flow ID but not its approved destination.
- **Fix:** include the project in the digest, preserve it in the approval, and
  recheck the project at dispatch and execution time.
- **Regression verification:** both stale-snapshot tests passed; execution was
  not dispatched.

## 004 — Batched tools continued after an approval gate

- **Reproduction:** `tests/test_agent_model_retry.py::test_pending_approval_stops_later_tool_calls_in_the_same_model_round`
  returned a workflow run and a later read tool in the same model response.
  Previously the later tool could execute before the user approved the run.
- **Root cause:** the tool-call loop did not treat `pending_approval` as a stop
  condition.
- **Fix:** record later calls as not run, return a waiting-approval result, and
  make no further model request until the approval decision.
- **Regression verification:** the model retry test file passed with **21 tests**.

## 005 — Approval execution did not resume the one-sentence research task

- **Reproduction:** `tests/test_agent_task_legacy.py::test_approved_agent_tool_resumes_the_research_task`
  approved a workflow run requested by the Agent. The operation ran, but no
  follow-up Agent task was started to finish validation/reporting.
- **Root cause:** approval dispatch returned only the tool result and discarded
  the suspended research objective.
- **Fix:** schedule a durable continuation task with the approved tool result as
  untrusted context; retain the original project/session permissions.
- **Regression verification:** the approved run executes once and a continuation
  produces the final research response.

## 006 — Resolved approvals left their task permanently waiting

- **Reproduction:** the task outcome test in
  `tests/test_agent_task_legacy.py::test_approved_agent_tool_resumes_the_research_task`
  observed the original task after approval; it remained `waiting_approval` even
  though the operation had run.
- **Root cause:** task records were never updated when an approval was decided.
- **Fix:** resolve the matching approval in persisted task results, keep tasks
  waiting while other approvals remain, and close the task when the last one is
  resolved. The UI updates the original task status as well.
- **Regression verification:**
  `tests/test_agent_tasks.py::test_task_waits_for_every_approval_and_closes_after_the_last_decision`
  and the end-to-end continuation test passed.

## 007 — Invalid or partial model streams were replayed

- **Reproduction:** `tests/test_agent_stream_contract.py` showed malformed SSE
  events, incomplete tool fragments, oversized lines, and disconnects after
  emitted text being retried. The client could duplicate a model request after
  already exposing part of its response.
- **Root cause:** stream parse and read errors fell through the general retry
  path used for transient non-streaming responses.
- **Fix:** fail malformed streams without replay; retry a read interruption only
  when no response content has been emitted. Cancellation still propagates.
- **Regression verification:**
  `pytest tests/test_agent_stream_contract.py tests/test_agent_model_retry.py -q`
  — **37 passed**.

## 008 — Direct LFX output values were discarded

- **Reproduction:** the file executor returned empty `outputs` for dictionary,
  scalar, and Pydantic-wrapped table results, including the regression cases in
  `tests/test_workflow_files.py`.
- **Root cause:** serialization assumed every result was an LFX `RunOutputs`
  object with an `.outputs` attribute.
- **Fix:** preserve bounded direct values and serialize table DataFrames as up
  to 100 records, with an omission marker for larger tables.
- **Regression verification:** `pytest tests/test_workflow_files.py -q` —
  **18 passed**.

## 009 — Creating a default project broke approved workflow creation

- **Reproduction:**
  `tests/test_advanced_features_phase4.py::test_approval_execution_without_intent_or_group_permits_action`
  failed when an approved build in an ungrouped session needed a project.
- **Root cause:** `Store.create_project()` returns the project ID string, but the
  workflow builder indexed that string as a dictionary.
- **Fix:** use the returned project ID directly.
- **Regression verification:** the approval test passed and verified both the
  initial workflow creation and the subsequent approved report creation.

## 010 — Explicit no-header null fell back to the first data row

- **Reproduction:** the approved hardness workflow's native run failed with
  `id_columns must be a unique list of existing column names`. A saved
  `cfg_header: null` was treated as an absent form value, so the importer used
  its default header row (`0`) instead of the selected data having no header.
- **Root cause:** generic empty-value handling dropped an explicitly supplied
  `None` before the `nullable_int` converter could preserve it.
- **Fix:** retain explicit null for nullable-integer form controls while keeping
  the normal default for controls that were not supplied.
- **Regression verification:**
  `tests/test_node_ui_contracts.py::test_explicit_null_header_is_preserved_as_no_header`
  passed; the corrected 23-import workflow subsequently completed and its
  statistics matched the source workbooks. Full suite: **1386 passed, 5 skipped**.

## 011 — Multi-level grouping was rejected when the single-group field was blank

- **Reproduction:** a grouped-statistics node with valid `group_by=["metric"]`
  but an empty legacy `group` field failed with `请填写分组列` before execution.
- **Root cause:** form validation enforced the single-group field before
  considering the supported multi-level grouping override.
- **Fix:** allow a non-empty `group_by` list to satisfy the grouping
  requirement, while retaining a clear error when both grouping settings are
  absent.
- **Regression verification:**
  `tests/test_node_ui_contracts.py::test_group_by_satisfies_grouped_statistics_group_requirement`
  passed, including execution of the grouped-statistics operation; the corrected
  hardness workflow returned all 17 expected groups. Full suite:
  **1386 passed, 5 skipped**.

## 012 — Directory names controlled workflow intent detection

- **Reproduction:** the one-sentence request “我想研究一下九种铜合金的性质，数据是
  `C:\...\铜合金机械测试_原始实验数据...`” was classified as a build/run request
  because the intent regex scanned words inside the absolute path. Without those
  path words, the same research objective was not consistently recognized as a
  complete local-analysis task.
- **Root cause:** authorization intent was inferred from unfiltered prompt text,
  so filesystem names could grant operations while ordinary research phrasing
  failed to grant the intended task.
- **Fix:** mask absolute local paths before intent detection; recognize a natural
  research objective plus a material/data target as build-and-run authorization
  within the existing project permission boundary; explicit refusals still win.
  The system prompt now says a one-sentence research goal plus an authorized
  local data directory is sufficient and that directory names are not intent.
- **Regression verification:**
  `tests/test_harness_controls.py::test_plain_language_copper_alloy_research_request_authorizes_full_local_analysis_task`
  `::test_plain_language_research_request_passes_project_workflow_authorization`,
  `::test_one_sentence_materials_request_completes_skill_preflight`, and
  `tests/test_agent_model_retry.py::test_agent_prompt_uses_repository_metadata_and_stops_duplicate_runs`;
  **123 targeted tests passed**. Full suite: **1389 passed, 5 skipped**.

## 013 — Valid workflows were rejected by path validation while generated output paths were unchecked

- **Reproduction:** `tests/test_bugfix_harness_workflow_paths.py::test_template_field_metadata_is_not_treated_as_a_filesystem_path`
  and `::test_empty_template_path_field_does_not_block_workflow_run` rejected any
  workflow containing a standard Langflow path field (even with an empty value)
  with "此本地路径未授权给当前项目"; `::test_workflow_run_rejects_output_directory_outside_project[cfg_output_dir]`
  accepted an export node writing outside the project-authorized directories.
- **Root cause:** the local-path collector recursed into Langflow field metadata
  (`name`/`display_name`/`info`) as if it were a path, matched only bare key
  names, and had no `cfg_` normalization or generated output keys.
- **Fix:** validate only a path field's `value`, normalize the `cfg_` prefix, add
  `output_dir`/`ocr_config_path`/`model_path`/`manifest_path`, keep HDF5 in-file
  keys untouched.
- **Regression verification:** pristine HEAD: **5 failed, 1 passed**; fixed tree:
  **6 passed**; related harness suites **155 passed**.

## 014 — Declined run/build requests were treated as explicit authorization

- **Reproduction:** `tests/test_bugfix_harness_intent_authorization.py::test_declined_run_request_does_not_authorize_execution`
  (7 phrasings), `::test_declined_build_request_does_not_authorize_canvas_changes`,
  and `::test_declined_run_phrase_requires_approval_instead_of_automatic_execution`
  showed "不用运行工作流"、"不必调整工作流"、"没必要修复工作流"、"勿运行工作流" etc.
  parsed as positive intent; `_authorize_tool(run_workflow)` returned allowed=True.
- **Root cause:** the negation vocabularies missed 不用/不必/没必要/用不着/不打算/勿,
  and run/build each used separate regexes.
- **Fix:** one shared `REQUEST_NEGATION` pattern plus a clause-aware
  `_negated_request_before()` helper, wired into run/build/research-task parsers.
- **Regression verification:** pristine HEAD: **24 failed, 1 passed**; fixed tree:
  **25 passed**.

## 015 — Declined destructive/approval requests still authorized actions

- **Reproduction:** `tests/test_bugfix_harness_intent_authorization.py::test_agent_cannot_cancel_approval_after_user_declines_cancellation`
  authorized the Agent's `cancel_approval` tool from the message "不要取消这个审批";
  the delete/skill/report/proposal cases in the same file also matched positive
  intent.
- **Root cause:** delete/skill/cancel helpers searched for the verb substring
  without any negation check; report/proposal used a narrow negator list.
- **Fix:** reuse the shared negation machinery; cancel checks negation before the
  verb or after the noun; delete/skill scan all occurrences and accept only
  non-negated ones.
- **Regression verification:** part of the 25 intent tests above; the approval
  remained `pending` after the declined cancellation.

## 016 — One malformed metadata record discarded a whole literature provider page

- **Reproduction:** `tests/test_bugfix_harness_academic_search.py::test_single_incomplete_record_does_not_discard_provider_results`
  returned 0 records plus an opaque warning for Crossref/OpenAlex/Europe PMC/
  Semantic Scholar/DataCite pages containing one null field.
- **Root cause:** unguarded `.get(...)[0]` chains and slicing on nullable list,
  dict and string fields, with no per-record isolation.
- **Fix:** `_dict_items()`/`_first_text()` guards in all five JSON parsers;
  provider-wide network/HTTP/XML failures still surface as warnings.
- **Regression verification:** pristine HEAD: **5 failed, 1 passed**; fixed tree:
  **6 passed**.

## 017 — Non-finite floats broke the strict-JSON contract at response boundaries

- **Reproduction:** `tests/test_bugfix_harness_json_boundary.py::test_turn_response_replaces_non_finite_workflow_values`
  and `::test_bounded_tool_content_replaces_non_finite_values`: a successful
  canvas run containing NaN/inf was persisted as `status=failed` by
  `allow_nan=False`, produced invalid JSON over HTTP, and violated the documented
  "tool replies are valid JSON" contract.
- **Root cause:** no finite-number normalization between node results and the
  JSON boundaries.
- **Fix:** recursive depth-bounded `_strict_json_value()` mapping non-finite
  floats to `null`, applied to the final turn response and bounded tool content.
- **Regression verification:** pristine HEAD: **2 failed**; fixed tree:
  **2 passed**.

## 018 — Decimal-comma files were split on the decimal mark

- **Reproduction:** `tests/test_science_import_identity.py::test_decimal_comma_does_not_guess_mixed_thousands_and_decimal_notation`
  (the pre-existing baseline failure) returned two columns `[1.234, 2.0]` for
  `value\n1.234,56\n2,5` instead of keeping the ambiguous raw cells.
- **Root cause:** delimiter auto-detection always sniffed with `",;\t|　"`; with
  `","` declared as the decimal separator the sniffer split values at the
  decimal comma.
- **Fix:** when `decimal_separator == ","`, infer the separator only from
  `";\t|　"`; a single-column file uses a character absent from the file so the
  values stay in one column. Explicit delimiters are unchanged.
- **Regression verification:** pristine HEAD: **1 failed, 2 passed**; fixed tree:
  **3 passed**, including the previously failing identity test.

## 019 — Declared UTF-8 encoding leaked a byte-order mark into the first column

- **Reproduction:** `tests/test_bugfix_scienceio_import_encoding.py::test_explicit_utf8_encoding_does_not_keep_byte_order_mark_in_header`
  imported a UTF-8-with-BOM CSV with `encoding="utf-8"` as columns
  `['\ufeffvalue', 'note']`, so column-name checks failed.
- **Root cause:** the explicit-encoding branch returned `raw.decode(encoding)`
  without stripping a decoded U+FEFF; only the `auto` branch used `utf-8-sig`.
- **Fix:** strip a decoded leading U+FEFF in the explicit branch (any encoding).
- **Regression verification:** pristine HEAD: **3 failed**; fixed tree:
  **3 passed**.

## 020 — BOM-less UTF-16 text was decoded as UTF-8 NUL garbage

- **Reproduction:** `tests/test_bugfix_scienceio_import_encoding.py::test_bomless_utf16le_source_is_detected_instead_of_nul_split_garbage`
  and `::test_bomless_utf16be_source_is_detected`: UTF-16LE/BE files without a BOM
  (common instrument exports) produced NUL-laden header names and values.
- **Root cause:** auto detection only recognized UTF-16 via BOM; NUL bytes are
  valid UTF-8, so the UTF-8 fast path accepted the file.
- **Fix:** for even-length input containing NULs predominantly in odd (LE) or
  even (BE) positions, decode as `utf-16-le`/`utf-16-be` and accept only if no
  NUL remains; the detected encoding is reported.
- **Regression verification:** pristine HEAD: **2 failed**; fixed tree:
  **2 passed**.

## 021 — Read-only SQL guard rejected valid SELECTs containing literals or comments

- **Reproduction:** `tests/test_bugfix_scienceio_sql_guard.py::test_select_with_literal_semicolon_and_write_words_is_accepted`
  and `::test_select_with_semicolon_inside_comment_is_accepted` rejected
  `select * from samples where note in ('a;b','delete','into')` and
  `select 1 -- x; y` as multiple statements / write operations.
- **Root cause:** the single-statement and forbidden-keyword regexes scanned raw
  query text, so literal values and comments were treated as SQL tokens.
- **Fix:** a `_sql_without_literals` scanner blanks line/block comments and
  quoted literals/identifiers before the checks (MySQL `/*! */` content is kept
  so it is still checked); unterminated literals/comments raise a clear error.
- **Regression verification:** pristine HEAD: **3 failed, 5 passed**; fixed tree:
  **8 passed**, while genuine multiple statements, write operations and
  `load_extension` remain rejected.

## 022 — JCAMP XFACTOR was not applied to the X increment

- **Reproduction:** `tests/test_bugfix_scienceio_instrument_factors.py::test_jcamp_xfactor_scales_delta_x`
  returned x = `[4.0, 5.0, 6.0]` instead of `[4.0, 4.001, 4.002]` for a JCAMP-DX
  file with FIRSTX=4000, LASTX=4002, NPOINTS=3, XFACTOR=0.001;
  `::test_jcamp_explicit_deltax_also_scales_with_xfactor` showed the same for an
  explicit DELTAX.
- **Root cause:** the first X was multiplied by XFACTOR but the computed/declared
  step was used unscaled.
- **Fix:** scale the step by XFACTOR: `step = float(DELTAX or (last-first)/(count-1)) * xf`.
- **Regression verification:** pristine HEAD: **2 failed**; fixed tree:
  **2 passed**; YFACTOR handling unchanged.

## 023 — Unit conversion silently rounded exact large integers through float

- **Reproduction:** `tests/test_bugfix_scienceio_unit_precision.py::test_unit_conversion_refuses_to_round_large_exact_integer`
  converted 9007199254740993 Pa to Pa as 9007199254740992.0, and
  `::test_unit_conversion_reports_inline_quantity_precision_loss_too` showed the
  same for inline quantities.
- **Root cause:** conversion always did `float(magnitude)`, discarding the exact
  Decimal used by `common.numeric`.
- **Fix:** refuse conversion when an integral magnitude is not exactly
  representable as a float; non-integral and representable integers convert as
  before.
- **Regression verification:** pristine HEAD: **2 failed, 1 passed**; fixed tree:
  **3 passed**; existing unit/temperature tests unchanged.

## 024 — export.table CSV verification crashed on pandas nullable booleans

- **Reproduction:** `tests/test_bugfix_sciencestats_export_bool.py::test_csv_export_roundtrips_nullable_boolean_columns`
  failed with `Unable to parse string "True" at position 0` while exporting a
  table containing a pandas `boolean` extension column.
- **Root cause:** readback classification recognized only str/object text columns;
  BooleanDtype fell into the numeric branch and `pd.to_numeric` was applied to
  the CSV text `True`/`False`.
- **Fix:** treat bool dtypes as text columns during export/readback comparison.
- **Regression verification:** pristine HEAD: **1 failed, 1 passed**; fixed tree:
  **2 passed**.

## 025 — Grouped CV crashed with a cryptic metrics error on a singleton fold

- **Reproduction:** `tests/test_bugfix_sciencestats_cv_fold_sizes.py::test_grouped_cv_with_singleton_unit_names_the_undersized_fold`
  and `::test_grouped_cv_with_singleton_unit_fails_clearly_for_model_comparison`
  failed with "at least two aligned one-dimensional observed/predicted values
  required" for an imbalanced grouped design.
- **Root cause:** `_evaluation_splits` validated only `folds <= n//2`; GroupKFold
  can legally create a 1-sample validation fold, which `_metrics` then rejects.
- **Fix:** `_check_fold_sizes()` applied to random/grouped CV splits, requiring
  at least two training and two test observations and naming the undersized fold.
- **Regression verification:** pristine HEAD: **2 failed**; fixed tree:
  **2 passed**; balanced CV results unchanged.

## 026 — export.report aborted on NaN/inf in result payloads

- **Reproduction:** `tests/test_bugfix_sciencestats_report_nonfinite.py::test_html_report_tolerates_non_finite_numeric_result_payloads`
  and `::test_markdown_report_tolerates_non_finite_numeric_result_payloads`
  failed with "Out of range float values are not JSON compliant: nan" and wrote
  no report file.
- **Root cause:** `_text()` serialized payloads with `allow_nan=False` without
  normalizing non-finite floats.
- **Fix:** recursive `_json_safe()` mapping non-finite floats (including NumPy
  scalars) to `null` before strict serialization.
- **Regression verification:** pristine HEAD: **2 failed**; fixed tree:
  **2 passed**; escaping and embedded-image handling unchanged.

## 027 — Missing provenance values corrupted the claim registry and citations

- **Reproduction:** `tests/test_bugfix_litskills_literature_evidence.py::test_claim_registry_roundtrip_tolerates_missing_provenance`
  raised "source registry record conflicts with source provenance: page" for an
  extract→sources roundtrip with missing page/confidence/doi;
  `::test_citation_never_renders_missing_provenance_values` produced
  `https://doi.org/nan` and `page nan`.
- **Root cause:** `evidence()` copied every location field present as a key, so
  NaN markers were treated as values and NaN != NaN declared a conflict;
  `citation()` used truthiness and `is not None` checks, and `float('nan')` passes
  both.
- **Fix:** omit missing location fields in `evidence()`; `citation()` treats
  missing/blank identifiers as absent and falls back to the source id.
- **Regression verification:** pristine HEAD: **6 failed**; fixed tree:
  **6 passed**.

## 028 — Saved literature source registry was not strict JSON

- **Reproduction:** `tests/test_bugfix_litskills_literature_evidence.py::test_saved_source_registry_is_strict_json`:
  `lit.sources(config={"save": True})` wrote `literature-sources.json` containing
  bare `NaN` tokens, breaking strict JSON readers.
- **Root cause:** `json.dumps(result.data, ...)` used `allow_nan=True` and raw
  Python/NumPy values.
- **Fix:** serialize `json_value(result.data)` with `allow_nan=False`.
- **Regression verification:** part of the **6 passed** above; the saved file
  parses with a refusing `parse_constant`.

## 029 — Null HTTP timeout in JSON config raised TypeError

- **Reproduction:** `tests/test_bugfix_litskills_literature_evidence.py::test_http_timeout_must_be_numeric`:
  `request_json` with `{"timeout": null}` raised
  `TypeError: float() argument must be ... not 'NoneType'`.
- **Root cause:** `float(cfg.get("timeout", 20))` outside a conversion guard.
- **Fix:** guard the conversion and raise the documented ValueError with an
  actionable message.
- **Regression verification:** included in the **6 passed** above.

## 030 — Null relative_tolerance in literature.compare raised TypeError

- **Reproduction:** `tests/test_bugfix_litskills_literature_evidence.py::test_compare_rejects_null_relative_tolerance`:
  JSON config `{"relative_tolerance": null}` raised TypeError instead of the
  documented ValueError.
- **Root cause:** unguarded `float(cfg.get("relative_tolerance", 0))`.
- **Fix:** guarded conversion to a clear ValueError.
- **Regression verification:** included in the **6 passed** above.

## 031 — A malformed Crossref record raised AttributeError

- **Reproduction:** `tests/test_bugfix_litskills_literature_evidence.py::test_crossref_malformed_record_is_value_error`:
  a record whose `published` is a list (or whose author entries are non-objects)
  escaped as `AttributeError: 'list' object has no attribute 'get'`.
- **Root cause:** `_crossref_record` assumed item/date dicts and author lists of
  dicts.
- **Fix:** validate record/date/date-parts/author shapes and raise ValueError with
  Crossref context; missing date-parts no longer raise IndexError.
- **Regression verification:** included in the **6 passed** above.

## 032 — make_plan raised TypeError before its parameter validation

- **Reproduction:** `tests/test_bugfix_litskills_planning.py::test_make_plan_rejects_non_object_parameters`:
  `make_plan(table, parameters=[{...}])` raised
  `TypeError: unhashable type: 'dict'` from `set(supplied)`.
- **Root cause:** `set(supplied)` ran before the `isinstance(supplied, dict)` check.
- **Fix:** validate the object type first, then build the field set.
- **Regression verification:** pristine HEAD: **2 failed**; fixed tree:
  **2 passed**.

## 033 — Unit-conflict diagnostic named the wrong unit

- **Reproduction:** `tests/test_bugfix_litskills_planning.py::test_unparseable_upstream_unit_is_named_in_the_issue`:
  with a corrupt stored unit (`banana`) and a valid declared unit (`nm`), the plan
  issue said "无法识别单位：nm" and skipped the remaining unit checks.
- **Root cause:** one broad try/except wrapped declared-unit parsing, stored-unit
  parsing and compatibility checks, always reporting the declared unit.
- **Fix:** parse the declared unit separately, report "无法识别上游单位：<stored>"
  per stored unit, and guard non-dict `table.attrs["units"]`.
- **Regression verification:** included in the **2 passed** above.

## 034 — Demo launcher could not import its branding helper (20 failing tests)

- **Reproduction:** the 20 baseline failures in `tests/test_demo_launcher.py`
  raised `ModuleNotFoundError: No module named 'branding'` while loading
  `scripts/start_demo.py`; `tests/test_bugfix_launcher_imports.py::test_start_demo_loads_sibling_branding_helper`
  reproduces the same import failure directly.
- **Root cause:** `from scripts.branding import ...` resolves to
  `packages/materials-quality/scripts` (a regular package placed on `sys.path` by
  pytest's rootdir) which has no `branding.py`; the fallback `from branding import`
  fails because the repository root is not on `sys.path` in that environment.
- **Fix:** load the sibling `branding.py` by file path via
  `importlib.util.spec_from_file_location("studyui_branding", ...)`, which works
  for direct execution, `python -m scripts.start_demo` and importlib loaders.
- **Regression verification:** `tests/test_demo_launcher.py` **20 failed → 20
  passed**; new import tests pristine HEAD: **2 failed, 1 passed**; fixed tree:
  **3 passed**.

## 035 — The portable builder had the same fragile branding import

- **Reproduction:** `tests/test_bugfix_launcher_imports.py::test_portable_builder_loads_sibling_branding_helper`
  failed to load `scripts/build_portable.py` by file path with the same
  `ModuleNotFoundError`, and a foreign `scripts` package could be imported.
- **Root cause:** identical namespace shadowing in the builder.
- **Fix:** the same file-path loader; `scripts/branding.py` remains in
  `INCLUDE_FILES` for the portable archive.
- **Regression verification:** pristine HEAD: failed; fixed tree: passed;
  `--check` and `-m scripts.start_demo --check` entry points re-verified.

## 036 — Ctrl+C during startup orphaned the detached StudyUI server

- **Reproduction:** `tests/test_bugfix_launcher_lifecycle.py::test_keyboard_interrupt_during_startup_stops_spawned_server`
  showed that interrupting the launcher while it waited for `/api/health` left the
  detached server running and holding the loopback port.
- **Root cause:** the readiness loop only stopped the child on timeout;
  KeyboardInterrupt propagated without cleanup and `start_system` never received
  the process handle.
- **Fix:** wrap the readiness loop in `try/except BaseException`, stop the spawned
  service, then re-raise; timeout behavior unchanged.
- **Regression verification:** pristine HEAD: **3 failed**; fixed tree:
  **3 passed**.

## 037 — Startup-failure message pointed at a log that does not exist

- **Reproduction:** `tests/test_bugfix_launcher_lifecycle.py::test_startup_failure_reports_the_requested_runtime_log`:
  with a custom `--runtime`, the failure message named the default
  `.demo-runtime/logs/studyui-server.log` instead of the actual runtime.
- **Root cause:** a hard-coded default-runtime log path in the RuntimeError text.
- **Fix:** derive the log path from the runtime actually in use.
- **Regression verification:** included in the **3 passed** above.

## 038 — Locale-codec decoding of the theme probe broke non-ASCII paths

- **Reproduction:** `tests/test_bugfix_launcher_lifecycle.py::test_theme_probe_decodes_child_output_as_utf8`:
  the Langflow theme probe failed with UnicodeDecodeError under a non-UTF-8 locale
  (cp936 / LANG=C) when the install path contained non-ASCII characters.
- **Root cause:** `subprocess.run(..., text=True)` decoded the child's UTF-8 output
  with the ANSI code page and inherited locale environment.
- **Fix:** pass `encoding="utf-8"` and a child environment with `PYTHONUTF8=1` /
  `PYTHONIOENCODING=utf-8`.
- **Regression verification:** included in the **3 passed** above.

## 039 — /canvas/api/v2/workflows request data bypassed approval and sanitization

- **Reproduction:** `tests/test_bugfix_server_workflow_host.py::test_request_data_cannot_add_unapproved_ai_analysis_node`,
  `::test_request_data_cannot_inject_untrusted_component_code`, and
  `::test_request_data_must_only_contain_installed_components`: a POST with
  `{"flow_id": <saved safe flow>, "data": {"nodes": [...]}}` returned 200 and
  executed the injected graph, including an AI-analysis node and untrusted
  component code bytes.
- **Root cause:** authorization and sanitization were applied to the stored flow,
  but the request's `data` override (which LFX runs with priority) was merged
  afterwards — the checked target was not the executed target.
- **Fix:** merge caller data first, then sanitize the effective graph against the
  installed component catalog (unknown types → 422), and authorize the effective
  graph for AI nodes.
- **Regression verification:** pristine HEAD: **3 failed**; fixed tree:
  **3 passed**; injected AI node now returns 403 and untrusted code is rebound.

## 040 — A rejected workflow restore had already overwritten the current workflow

- **Reproduction:** `tests/test_bugfix_server_workflow_api.py::test_rejected_restore_keeps_the_current_workflow`:
  restoring a historical revision that no longer validates returned 422, but the
  store had already been replaced by the invalid revision.
- **Root cause:** the route saved first (`store.restore`) and validated afterwards.
- **Fix:** validate (and normalize) the loaded revision before saving; failures
  leave the current workflow untouched.
- **Regression verification:** pristine HEAD: **1 failed**; fixed tree:
  **1 passed**; `tests/test_workflow_files.py` **19 passed**.

## 041 — A stray or corrupt JSON file broke all workflow listing

- **Reproduction:** `tests/test_bugfix_server_workflow_store.py::test_list_ignores_files_that_are_not_workflows`:
  a `manifest.json` or truncated workflow file in the workflows directory made
  `store.list()` raise, so project listing/migration/deletion returned 500.
- **Root cause:** `list()` parsed every `*.json` as a canonical workflow.
- **Fix:** skip files that cannot be read as canonical workflows; readable
  workflows are still served.
- **Regression verification:** pristine HEAD: **1 failed, 1 passed**; fixed tree:
  **2 passed**.

## 042 — Workflow history was ordered by revision hash, not save time

- **Reproduction:** `tests/test_bugfix_server_workflow_store.py::test_history_lists_the_most_recent_saved_version_first`
  returned versions in hash order instead of newest-first.
- **Root cause:** history files were sorted by filename/revision instead of the
  `saved_at` suffix.
- **Fix:** sort history by `saved_at` descending.
- **Regression verification:** included in the **2 passed** above.

## 043 — Latest artifact could pick the older same-second write

- **Reproduction:** `tests/test_bugfix_server_artifacts.py::test_latest_artifact_uses_creation_order_within_one_second`:
  two artifacts with the same name written in the same second could resolve to the
  older one (tie broken by random UUID).
- **Root cause:** `latest_artifacts()` ordered by `(created_at, uuid)`.
- **Fix:** order by `(created_at, rowid)` so insertion order breaks ties.
- **Regression verification:** pristine HEAD: **1 failed**; fixed tree:
  **1 passed**; artifact/rebind subset **9 passed**.

## 044 — Canvas add_node accepted NaN coordinates

- **Reproduction:** `tests/test_bugfix_server_workflow_actions.py::test_add_node_rejects_nan_position`
  and `::test_add_node_rejects_infinite_position`: `{"op": "add_node", "x": NaN}`
  passed bounds validation and later failed at `json.dumps(allow_nan=False)`.
- **Root cause:** the bounds check used `abs(x) > 100000`, which is false for NaN.
- **Fix:** require `math.isfinite(x/y)` in addition to the canvas bounds.
- **Regression verification:** pristine HEAD: **1 failed, 1 passed**; fixed tree:
  **2 passed**.

## 045 — Non-object JSON body to the messages route returned 500

- **Reproduction:** `tests/test_bugfix_server_routes.py::test_message_route_rejects_non_object_json_body`
  (bodies `[]`, `"text"`, `7`) produced an AttributeError and a 500 response.
- **Root cause:** the route accessed fields before checking the decoded body type.
- **Fix:** reject non-object JSON bodies with 400
  `{"error": "Request body must be a JSON object"}`.
- **Regression verification:** pristine HEAD: **4 failed**; fixed tree:
  **4 passed**.

## 046 — A failed approved action left its durable task waiting forever

- **Reproduction:** `tests/test_bugfix_server_routes.py::test_failed_approved_action_resolves_waiting_task`:
  when an approved non-workflow tool failed at dispatch, the approval had already
  been consumed but the durable task stayed `waiting_approval` permanently.
- **Root cause:** the harness re-raises after consuming the approval; the route
  only called `TaskManager.resolve_approval` on normal returns.
- **Fix:** catch the approved-dispatch exception, record a failed result, still
  resolve the waiting task, then return the error.
- **Regression verification:** pristine HEAD: task stayed `waiting_approval`
  (test failed); fixed tree: **4 passed**; approval-flow regression tests
  `test_agent_task_legacy.py` + `test_advanced_features_phase4.py` pass.


## 047 — Truncated model replies aborted long agent tasks

- **Reproduction:** the user's portable session task (16:52) failed at round 13
  with `ValueError: Model stream returned an unsuccessful finish reason` after
  six minutes of work; `tests/test_bugfix_model_finish_reason.py` reproduces it
  with a fake SSE `finish_reason='length'`. `length`/`max_tokens` (the provider
  hit its output limit) was classified as a fatal error.
- **Root cause:** the stream client accepted only `stop`/`tool_calls` and raised
  for every other provider finish reason; a long answer cut by the output limit
  therefore killed the whole durable task.
- **Fix:** finish-reason policy sets; `length`/`max_tokens` now return the partial
  reply with `truncated=True` (complete tool calls preserved, cut tool-call JSON
  dropped and marked), and the harness continues the turn from the cut-off point
  at most twice (`MAX_TRUNCATED_CONTINUATIONS`) with an explicit partial-output
  note instead of presenting a fragment as final.
- **Regression verification:** pristine HEAD worktree: **13 failed, 2 passed**;
  fixed tree: **16 passed**; related stream/retry suites **41 passed**.

## 048 — Provider stop reasons were misclassified and oversized replies retried

- **Reproduction:** `tests/test_bugfix_model_finish_reason.py::test_insufficient_system_resource_is_retried_without_duplicate_output`
  and `::test_content_filter_is_permanent_and_not_retried`; the user DB showed 8
  tasks failed with the stale message "Model response exceeded 2 MB" although the
  real limit is 16 MB, and oversized replies were retried six times.
- **Root cause:** all non-standard finish reasons were treated alike, and the
  size-limit errors hard-coded "2 MB"/"256 KB" while using module constants.
- **Fix:** `insufficient_system_resource` is retried before any output (never
  duplicating emitted text), `content_filter`/safety are permanent and
  actionable, oversized responses are permanent (no pointless retries), and all
  byte-limit messages derive from the live limits ("16 MB (16,000,000 bytes)" /
  "256 KB (256,000 bytes)").
- **Regression verification:** included in the 16 tests above; reference suites
  `test_agent_stream_contract.py` + `test_agent_model_retry.py` **41 passed**.

## 049 — run_workflow exposed only sink nodes; agents were blind to intermediate metrics

- **Reproduction:** desktop session d432bbb9 messages 49-59: with
  `mech.report -> viz.reports` connected, the run result contained only the sink
  node's artifacts; the mechanics modulus/yield report was absent, so the agent
  spent five-plus rounds rewiring/guessing (it only appeared when `mech` had no
  outgoing edge).
- **Root cause:** `FileWorkflowExecutor` mapped LFX `output_type='debug'` to
  `'any'` and marked only export/leaf nodes as `is_output`, and LFX returns
  results only for output vertices unless debug mode is requested; the harness
  compaction therefore never saw intermediate results. Debug-wrapped reports
  also lost their `message.data` metrics during compaction.
- **Fix:** opt-in `include_all_nodes` for agent tool runs (canvas/UI defaults
  unchanged), harness compaction that keeps every executed node within the
  8,000-char contract, exposes per-node report metrics (e.g.
  `elastic_modulus_MPa`, `yield_stress_MPa`), `execution_status`, and
  `failed_nodes`.
- **Regression verification:** pristine HEAD worktree: **4 failed / 9 deselected**;
  fixed tree **14 passed**; `tests/test_bugfix_run_metrics_report.py` (Lead) plus
  existing `test_harness_controls.py` **105 passed**; a scripted-model end-to-end
  chat run sees `saw_metrics=True` with the real 200000 MPa / 202.01 MPa values.

## 050 — Misleading permission errors for old-session uploads and bare filenames

- **Reproduction:** desktop session d1c34dce: a path belonging to an older chat's
  upload directory (and a bare filename) returned "此本地路径未授权给当前项目。请先
  在项目菜单的…添加该目录"; the agent suggested adding the folder, the retry still
  failed and the user abandoned the session. A missing file also produced the
  "unsupported file format" message in `data_inspection.authorized_file`.
- **Root cause:** one generic message for every authorization failure, and one
  combined condition for "missing file" and "unsupported suffix".
- **Fix:** actionable messages that name the real repair (re-upload in the current
  chat, or copy to an authorized folder, or use the full path returned by the
  upload record); missing files are reported as missing instead of unsupported.
  Permission policy and roots are unchanged.
- **Regression verification:**
  `tests/test_bugfix_run_visibility_all_nodes.py` permission-message tests and
  `tests/test_bugfix_e2e_offline_use.py::test_missing_absolute_path_message_points_to_upload_or_project_dir`
  (pristine HEAD fails, fixed tree passes).

## 051 — Mechanics "no offset crossing" warning had no diagnostics or repair hint

- **Reproduction:** desktop run returned "No offset-line crossing was measured
  after the elastic fit range; yield stress is unavailable." for a fit window
  outside the elastic region, with no modulus, ranges, or guidance; the agent
  suspected a unit error and burned rounds adding diagnostics branches.
- **Root cause:** the missing-crossing branch emitted a fixed sentence only.
- **Fix:** the warning now reports the fitted modulus, R², the fit window used,
  the measured strain/stress ranges, an explicit "fit_range must lie inside the
  initial linear region" hint and a deterministic initial-slope candidate range
  (no automatic fit-window selection), plus machine-readable
  `offset_line_diagnostics`; missing x/y columns now list available columns.
- **Regression verification:**
  `tests/test_bugfix_actionable_errors_mechanics_viz.py` — 5 failed / 1 passed on
  current pre-fix behavior, **6 passed** after; related science suites
  **119 + 64 passed**.

## 052 — Mechanics plot column/unit errors were not actionable

- **Reproduction:** chaining the mechanics result table into the plot node failed
  with `unknown columns: ['strain','stress','specimen']` and
  `unit declarations must map existing columns to nonempty unit labels`, without
  the available columns or the `strain_fraction`/`stress_MPa` mapping the agent
  needed.
- **Root cause:** validation errors only stated the requirement that failed.
- **Fix:** unknown-column errors list available columns and suggest
  `cfg_x`/`cfg_y`/`cfg_sample` (including the derived-table mapping or connecting
  the raw import table); unit-declaration errors list columns and the expected
  `{"<column>": "<unit>"}` format with an example. Valid plotting behavior is
  unchanged.
- **Regression verification:** included in the **6 passed** above.

## Usability-blocker round — verification run

- Baseline before this round (same tree): **1493 passed, 5 skipped**.
- After the six fixes above: **1537 passed, 5 skipped, 0 failed**
  (`pytest tests -q`, 550.40 s on the final formatted tree; +44 new tests).
- `ruff check` + `ruff format --check` (0.17.3, CI configuration) clean for
  `src`, `components`, `tests`, `scripts`, `examples` and root `scripts`.
- Ported to the user's Windows portable demo and re-verified through its own
  runtime and HTTP server: all five home-page reference workflows complete and
  download their HTML report (source SHA-256 + embedded PNG) and source artifact
  (**5/5**), and a scripted-model chat run (upload Ti64 CSV -> build -> run ->
  report) completes with the agent seeing the real 200000 MPa modulus and
  202.01 MPa Rp0.2 values and chart artifacts.
- **Live end-to-end acceptance with the real configured model** (patched portable
  app on 127.0.0.1:7880, user's exact Ti64 request): the agent uploaded the CSV,
  inspected it (SHA-256, 401 rows), ran a window-sensitivity check driven by the
  new R² diagnostic (0.0005-0.002 rejected, 0.0002-0.001 accepted), computed
  **E = 200,000 MPa / 200 GPa and Rp0.2 = 202.01 MPa**, exported two PNG plots,
  the 401x7 results CSV and metadata JSON, and returned a structured report with
  source hash, unit reasoning, limitations and the saved workflow id. The task
  finished **completed, 0 approvals, 0 errors** - one complete normal use.

## Verification run — 2026-11-08

- Pristine HEAD (`0858caa`) baseline: **1381 passed, 21 failed, 5 skipped**.
- Fixed tree: **1493 passed, 5 skipped, 0 failed** (`pytest tests -q`,
  443.73 s); the 91 new regression tests are included.
- Every regression test above was independently re-run against a pristine HEAD
  worktree and failed there, then passed in the fixed tree.
- `ruff check` and `ruff format --check` (0.17.3, CI configuration) pass for
  `src`, `components`, `tests`, `scripts`, `examples` and the repository-root
  `scripts`.
- The 5 skips are the pre-existing browser/UI-extra tests.
- Repository-hygiene finding (not counted, not fixed): the checked-in generated
  artifacts (`science/catalog.json`, `examples/**`, `demos/flows/**`) predate the
  last feature commit, so `scripts/build_*.py` rewrites them on a fresh checkout.
  Their stale fields are unused at runtime, but tests that execute the embedded
  example flows exercise older copies of the component code. Regenerate with the
  documented build scripts and consider a CI freshness check.
- Documentation fix: `docs/demo-launcher.md` pointed users at a
  `.demo-runtime/logs/studyui-launcher.log` file the launcher never creates; it
  now references the real `studyui-server.log` and console output.
## Boundary-exhaustion campaign - 2026-11-08 (round 2)

Second pass: systematically probe every operation, numeric limit and boundary,
not only the reported failure paths.

Area coverage (recorded probe cases / confirmed defects fixed / new test files):
- Harness core (tool budgets, compaction, text limits, 4x19x8x2 permission matrix,
  task state machine, path authorization, data inspection, academic search, skill
  registry): ~400 classified cases + 1,248 authorize combinations / 8 fixed /
  6 tests/test_boundary_harness_*.py (35 nodes).
- Server, storage and workflow files (HTTP routes/methods/hosts/bodies, uploads,
  revisions/history, concurrency, injected disk failures): ~252 / 5 /
  3 tests/test_boundary_server_*.py (13 nodes).
- Science I/O and extractors (encodings, CSV/PDF/raster/HDF5/SQL/OCR grids):
  ~387 / 10 / 2 tests/test_boundary_io_*.py (13 nodes).
- Science numeric operations (statistics, plots, materials, batch packet/source):
  ~283 / 5 / tests/test_boundary_numeric_extremes.py (5 nodes).
- Literature, skills, evaluation and UI schema (every catalog field x 16 boundary
  values): ~10,200 / 10 / tests/test_boundary_litskills_validation.py (11 nodes).
- Model HTTP/SSE transport (fragmentation, grammar, byte limits, HTTP status and
  retry, tool calls, profiles): ~180 / 13 / 3 tests/test_boundary_model_*.py
  (38 nodes).
- Standalone science fuzzer (48 operations + 8 quality components): 16,703 cases,
  report-only; findings below.
- Lead cross-cutting launcher/builder boundaries (~150 cases) / 4 fixed
  (non-finite --ready-timeout accepted; blank --runtime silently resolved to cwd;
  dependency arrays containing extras such as uvicorn[standard] crashed with
  SyntaxError; case-variant and *.env forbidden portable files slipped through) /
  3 new test files (tests/test_boundary_launcher_*.py, test_boundary_portable_forbidden.py).

Total: about 30,600 recorded boundary cases, 55 additional confirmed fixes and
147 new regression tests. Final full suite: **1684 passed, 5 skipped, 0 failed**;
ruff check and format --check clean (0.17.3, CI configuration).

Browser UI evidence: the 5 browser suites that are always skipped locally were run
with Playwright + Chromium: 15 pass / 11 fail, and 10 of the 11 also fail on a
pristine HEAD checkout in this environment, so they are pre-existing
environment/expectation failures rather than regressions from this work; one is
order-dependent (passes on isolated re-run). Not counted as defects.

Residual findings handed to the next round (reproduced, not fixed here):
- science fuzzer: non-finite cells passed through a unit conversion raise a raw
  ArithmeticError rather than an actionable ValueError; stats.predict accepts an
  unbounded n_estimators=1e308 (configuration JSON only) and appears to hang;
  direct callable use with a non-dict config still raises raw AttributeError.


## CI repair round — 2026-11-09 (round 3)

Both GitHub Actions jobs had been failing since the UI port. Every failure was
reproduced locally, root-caused, fixed and re-verified; the CI steps that had
always been skipped behind the failing steps were also run locally for the
first time against the ported UI.

Fixture corrections (not counted as defects):
- test job: the corrupt-database fixture wrote a 28-byte text file. SQLite
  builds on Linux accept files shorter than the 100-byte header as empty
  databases, so no error was raised. The fixture now writes a valid 16-byte
  magic header with an invalid page size (528 bytes total), and the query
  reads `sqlite_master`: a bare "select 1" never touches the file on Linux
  SQLite builds, so no content-only fixture could raise there.
- ui job: the two rich-rendering chat fixtures did not mock `/api/workspaces`,
  so `allWorkspaces` became `{}` and the whole chat view crashed with
  `allWorkspaces.find is not a function`. After that, two assertions still
  described the pre-port DOM: the streaming partial is now a committed block
  plus a live tail (assert the `aria-busy` tail), and `watchTask` now streams
  through `fetch` before falling back to `api()` polling, so the late-response
  injection must release the poll after switching sessions.
- ui job: the task card cancel button is now labelled `取消`.
- `scripts/ui_demo_reference_acceptance.py` still asserted the pre-port demo
  cards carried the dataset row count; the simplified cards show the title and
  format badge by design, and `tests/test_demo_reference_ui.py` pins that
  contract.

Confirmed defects fixed in this round (each covered by a regression check):

1. **The demo run-guidance panel disappeared from the canvas view.** The
   `#demo-run-guidance` status element and the code that fills it in
   `openDemoReference` were lost in the port; opening a reference workflow no
   longer explained how to run it. Regression:
   `tests/test_demo_reference_ui.py::test_open_reference_navigates_canvas_with_run_guidance`
   (five cases) and
   `::test_fresh_start_reference_creates_project_and_preserves_ungrouped_chat`.
2. **The workflow sidebar action menu was clipped and unclickable for the top
   rows.** The flip-up rule `:nth-last-child(-n + 3)` opened the menu above the
   list's scroll origin, where `overflow: auto` clips it, so clicks landed on
   `.dsh-flow-browser-head` instead. The rule now excludes the first three
   rows. Regression: the rename half of
   `tests/test_demo_reference_ui.py::test_workflow_sidebar_menu_renames_and_deletes`.
3. **The canvas delete route rejected its only caller.**
   `DELETE /api/v1/flows/{id}` consulted the model-grade permission set, where
   `workflow.delete` is ALWAYS_APPROVE, so the human's confirmed sidebar delete
   always failed with 403. Model-initiated deletes never use this route (they
   go through the harness `delete_workflow` tool with the one-shot approval
   card); the route now gates the human action like other canvas writes.
   Regression: the delete half of
   `test_workflow_sidebar_menu_renames_and_deletes`.
4. **A view switch during boot was reverted by a stale snapshot.**
   `refresh()` computed the requested view before its `await`s and applied it
   afterwards, clobbering a view switch made while sessions were still loading
   (flaky: reproduced on roughly half of immediate clicks; the event log showed
   `showView('chat', false)` overriding the user's click). The view is now
   recomputed after the awaits. Regression: repeated runs of the demo
   reference UI suite (12/12 instrumented rounds stable, 3 x 11 passed).
5. **Reference workflow runs dropped their generated plots.**
   `run_reference_canvas` called `run_flow` without `include_all_nodes`, so
   only the terminal report node reached the artifact collector and the viz
   nodes' declared figure files never entered the session artifact store; the
   task completed with a report but without any downloadable plot. The call now
   mirrors the run_workflow tool (all executed nodes, with the same
   compatibility fallback). Regression:
   `scripts/ui_demo_reference_acceptance.py` — all five cases now store and
   download reports **and** plots.

Verification: full local suite **1710 passed, 0 failed** (includes the five
previously skipped browser suites, run with Playwright against system Chrome);
`ruff check` and `ruff format --check` clean (0.17.3, CI configuration);
`prettier@3.3.3 --check` clean for the touched UI assets; the complete test-job
build/evaluate/wheel/verify_install chain and the full demo-reference
acceptance script pass locally.

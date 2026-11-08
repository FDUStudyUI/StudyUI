# Verified bug-fix ledger

Only independently reproducible defects with a regression test and a passing
verification run are counted. Test-fixture corrections and feature work are not
counted. The requested 100-fix target is a goal, not a claim that has already
been met.

**Verified fixes: 12 / 100 target**

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

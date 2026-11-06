# Pure scientific analysis plans

`AnalysisPlanRunner(max_steps=64, max_executions=64).run(steps, inputs, previous=None)`
returns an `AnalysisRun`. `inputs` maps names to pandas DataFrames or artifact-free
`NodeResult` objects. Every run validates the complete graph before execution.

The visual step-editor schema can use these columns (ordinary presets should
populate config using the selected operation's existing visual fields):

| Field | Control | Meaning |
| --- | --- | --- |
| `id` | Unique text | Stable step name |
| `operation` | Dropdown | One of `PURE_OPERATIONS` only |
| `dependencies` | Ordered multi-select | Existing step IDs; first supplies the primary source |
| `input` | Optional dropdown | Named external source overriding the first dependency; roots default to `input` |
| `source_output` | `table` / `features` dropdown | Which primary source payload becomes the input table |
| `config` | Selected operation's visual form | Explicit scientific parameters |

Each dependency contributes to the fingerprint, even if an operation consumes
only its first table. Multi-table operations receive all dependency tables;
`preprocess.merge` with `method=specimen` receives the first as master and the
remainder as features. Source selection applies to the dependency tables too.

`AnalysisRun.records[id]` includes status, reason, elapsed seconds, input,
configuration, implementation and dependency fingerprints, result-integrity
fingerprint, scientific diagnostics, and the actual `NodeResult`. Successful
steps and their result contents are authenticated with a process-local key.
Reuse requires a valid previous record and equal fingerprints. Data, dtypes,
indices, units, metadata, helper implementation files and scientific library
versions participate in invalidation. Changed parameters invalidate descendants
even if the immediate numeric output happens to be identical.

Declared input contracts restore their units before execution. Each operation
updates or clears inherited contracts using the same preservation rules as the
native node adapter: normalization/unit conversion update unit declarations,
filtering updates surviving roles, and grouped statistics record aggregation.
Intermediate cached results therefore carry their current scientific schema.

Statuses are `success`, `reused`, `failed`, `blocked`, and `budget_exceeded`.
`success` means the operation completed; warnings/diagnostics still define the
scientific interpretation. Batch `failed` or `partial_failed` results remain
available for inspection but block descendants. Independent branches continue.
The runner never broadens a physical fitting window and never retries inside a
run. To repair, explicitly edit parameters and call `run` again with the earlier
in-memory `AnalysisRun`. No disk pickle, JSON cache import, or global run-ID
lookup is provided. The capability should stay within the owning node/session.

The budget limits operation-call count and graph size (hard maximum 256 each),
not wall-clock runtime or resident memory of an individual scientific call.
Source hashing reads installed implementation files only. Scientific operations
cannot import files, export artifacts, execute arbitrary code, request approval,
or call a network service. Registry membership alone never expands the explicit
allowlist.

`analysis_plan(table, config={"steps": [...]})` is a simple node adapter returning
a status table and JSON-compatible audit/results. A single successful terminal
node supplies its feature table (or its ordinary table when features are absent)
as `NodeResult.features`. Multiple terminals require explicit downstream selection;
the adapter does not arbitrarily choose one. This adapter does not persist cache
state; an owning UI node may retain an `AnalysisRun` for explicit local retries.

Run the offline repair example from repository root:

```powershell
.superpowers/run-tests.ps1 examples/analysis_plan_demo.py
```

It asserts three calls on the first failure, two calls after an explicit unit
repair with two unrelated results reused, and zero calls on the unchanged rerun.

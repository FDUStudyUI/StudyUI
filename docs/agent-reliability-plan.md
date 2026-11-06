# Agent reliability implementation

Scope: complete the 2026-11-06 review against PR #7, retaining native forms and teammate UI. Base 78971d1; deliver through a new branch/PR without merging main or rewriting teammate branches.

1. Evidence: replace unconditional standards approval with evidence-based checks and unknown states; strict file identity; exact port mapping. Tests include absent data, descending axes, duplicate identities and ambiguous ports.
2. Boundaries: validate uploads against existing sessions and project policy, unique storage; custom code becomes non-executable review draft; scoped approvals and same-origin endpoints.
3. Execution: persistent task IDs, cooperative cancellation, no repeated session runs, polling/recovery; model stream correctness and bounded errors; honest UI status. Cancellation during uninterruptible operations remains cancelling until operation returns.
4. Evidence UI and reports: render actual execution events; no guaranteed standards or literature claims; evidence-based repair guidance and reusable benchmark results.
5. Verification: repair static checks without weakening scientific gates, manifest-based node discovery, run full tests/examples/wheel and real browser acceptance. Add offline independent adversarial evaluation and document live-model evaluation limitations.

Constraints: preserve original measurements; no invented standards compliance, measurement units or literature intervals. No paid model calls using user credentials. Keep old environments and local main untouched. Tests run in this isolated worktree with existing interpreter and explicit source path. No arbitrary generated code execution in host.

Implementation choices: use existing FastAPI/SQLite/vanilla UI. Persist task state separately in the runtime directory. Resume means reconnect to recorded task/result, not silently replay side effects after process restart. Draft code can be reviewed/exported; executable extensions continue to use the audited Skill sandbox.

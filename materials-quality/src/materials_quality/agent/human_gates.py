"""Runtime HUMAN approval gates backed by SessionStore and WorkflowLedger.

Suspends a workflow at critical materials-science decision points (e.g.,
elastic fit-range confirmation, baseline model choice, outlier exclusion,
or overriding a GUARD warning) and resumes cleanly once the researcher
approves or rejects the one-shot approval card.
"""

from __future__ import annotations

from typing import Any

from .permissions import new_approval_id
from .store import SessionStore
from .workflow_ledger import WorkflowLedger

HUMAN_GATE_KINDS = frozenset(
    {
        "select_fit_range",
        "choose_baseline_model",
        "exclude_outlier_samples",
        "confirm_guard_override",
        "confirm_method_parameters",
    }
)


class HumanGateController:
    """Coordinates one-shot HUMAN checkpoints between SessionStore and WorkflowLedger."""

    def __init__(self, store: SessionStore, ledger: WorkflowLedger | None = None) -> None:
        self.store = store
        self.ledger = ledger

    def request_gate(
        self,
        *,
        session_id: str,
        run_id: str,
        node_id: str,
        gate_kind: str,
        prompt: str,
        proposed_parameters: dict[str, Any] | None = None,
        guard_report: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if gate_kind not in HUMAN_GATE_KINDS:
            raise ValueError(f"Unsupported HUMAN gate kind: {gate_kind!r}")
        if not self.store.has_session(session_id):
            raise ValueError(f"Unknown session_id for HUMAN gate: {session_id!r}")

        context = self.store.session_context(session_id) or {}
        approval_id = new_approval_id()
        request_payload = {
            "kind": "workflow.human_gate",
            "run_id": run_id,
            "node_id": node_id,
            "gate_kind": gate_kind,
            "proposed_parameters": dict(proposed_parameters or {}),
            "guard_report": guard_report,
            "summary": {
                "title": f"人工科研确认：{gate_kind} ({node_id})",
                "impact": str(prompt)[:500],
            },
        }
        self.store.create_approval(
            approval_id,
            session_id,
            context.get("project_id"),
            "workflow.human_gate",
            str(prompt)[:1000],
            request_payload,
        )
        if self.ledger is not None:
            self.ledger.append_event(
                run_id,
                "human_gate_requested",
                {
                    "approval_id": approval_id,
                    "session_id": session_id,
                    "node_id": node_id,
                    "gate_kind": gate_kind,
                    "prompt": str(prompt)[:500],
                    "proposed_parameters": dict(proposed_parameters or {}),
                },
            )
        return {
            "status": "waiting_human_gate",
            "approval_id": approval_id,
            "run_id": run_id,
            "node_id": node_id,
            "gate_kind": gate_kind,
        }

    def resolve_gate(
        self,
        approval_id: str,
        decision: str,
        *,
        reviewer_note: str = "",
        confirmed_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected", "cancelled"}:
            raise ValueError(f"Invalid HUMAN gate decision: {decision!r}")
        record = self.store.get_approval(approval_id)
        if record is None or record.get("status") != "pending":
            raise ValueError("HUMAN 门禁审批不存在或已处理。")
        req = record.get("request") or {}
        if req.get("kind") != "workflow.human_gate":
            raise ValueError("该审批记录不属于 workflow.human_gate。")

        if not self.store.decide_approval(approval_id, decision):
            raise ValueError("HUMAN 门禁审批已被其他操作处理。")

        run_id = str(req.get("run_id") or "")
        node_id = str(req.get("node_id") or "")
        effective_params = (
            dict(confirmed_parameters)
            if confirmed_parameters is not None
            else dict(req.get("proposed_parameters") or {})
        )
        if self.ledger is not None and run_id:
            self.ledger.append_event(
                run_id,
                "human_gate_resolved",
                {
                    "approval_id": approval_id,
                    "node_id": node_id,
                    "gate_kind": req.get("gate_kind"),
                    "decision": decision,
                    "reviewer_note": str(reviewer_note)[:500],
                    "confirmed_parameters": effective_params,
                },
            )
        return {
            "approval_id": approval_id,
            "run_id": run_id,
            "node_id": node_id,
            "decision": decision,
            "can_resume": decision == "approved",
            "confirmed_parameters": effective_params,
            "reviewer_note": str(reviewer_note)[:500],
        }

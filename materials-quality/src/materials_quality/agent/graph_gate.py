"""Checked Graph Updates: triple-gate validation before committing workflow edits.

Wraps ``agent.workflow.apply_actions`` with three explicit gates:
1. Structural Gate: DAG acyclicity (Kahn's topological sort), canonical port/type
   compatibility, and registered/installed component verification.
2. Policy Gate: PermissionStore authorization and detection of external-data
   AI subagent nodes (``StudyUIAIAnalysis``) requiring one-shot approval.
3. Compile Gate: Rebinds all nodes against installed catalog templates via
   ``sanitize_installed_components`` to ensure the graph compiles cleanly.

If any gate fails, the original workflow ``W^(k)`` is returned untouched and a
``graph_update_rejected`` event is recorded in ``WorkflowLedger`` when attached.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .permissions import PermissionStore
from .workflow import (
    apply_actions,
    flow_digest,
    sanitize_installed_components,
    validate_flow_connections,
)
from .workflow_ledger import WorkflowLedger


@dataclass(frozen=True)
class GraphUpdateResult:
    """Auditable outcome of a checked workflow graph update."""

    accepted: bool
    flow: dict[str, Any]
    digest: str
    descriptions: tuple[str, ...] = ()
    rejections: tuple[dict[str, str], ...] = ()
    gate_details: dict[str, Any] = field(default_factory=dict)
    graph_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "digest": self.digest,
            "descriptions": list(self.descriptions),
            "rejections": [dict(item) for item in self.rejections],
            "gate_details": dict(self.gate_details),
            "graph_version": self.graph_version,
        }


def check_dag_acyclic(flow: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return ``(is_acyclic, cycle_nodes)`` using Kahn's topological sort."""
    data = flow.get("data") if isinstance(flow, dict) else {}
    nodes = [
        str(node["id"])
        for node in (data.get("nodes") or [])
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    ]
    edges = data.get("edges") or []
    indegree = dict.fromkeys(nodes, 0)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        src = edge.get("source")
        dst = edge.get("target")
        if src in adjacency and dst in indegree:
            adjacency[src].append(dst)
            indegree[dst] += 1

    queue = deque(node_id for node_id, deg in indegree.items() if deg == 0)
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for nxt in adjacency[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited == len(nodes):
        return True, []
    cycle_nodes = sorted(node_id for node_id, deg in indegree.items() if deg > 0)
    return False, cycle_nodes


def apply_checked_graph_update(
    flow: dict[str, Any],
    actions: list[dict[str, Any]],
    catalog: dict[str, Any],
    *,
    permissions: PermissionStore | None = None,
    project_id: str | None = None,
    task_authorized: bool = True,
    allow_external_ai_without_approval: bool = False,
    compile_check: bool = True,
    ledger: WorkflowLedger | None = None,
    run_id: str | None = None,
    rationale: str = "",
) -> GraphUpdateResult:
    """Validate and apply a workflow patch under structural, policy, and compile gates."""
    original = deepcopy(flow)
    original_digest = flow_digest(original)
    rejections: list[dict[str, str]] = []
    gate_details: dict[str, Any] = {
        "structural": "pending",
        "policy": "pending",
        "compile": "pending",
    }

    # --- Gate 1: Structural (apply_actions + DAG acyclicity + canonical ports) ---
    try:
        candidate, descriptions = apply_actions(original, actions, catalog)
        validate_flow_connections(candidate)
        acyclic, cycle_nodes = check_dag_acyclic(candidate)
        if not acyclic:
            rejections.append(
                {
                    "gate": "structural",
                    "code": "DAG_CYCLE_DETECTED",
                    "message": f"工作流图存在有向环路，涉及节点：{', '.join(cycle_nodes)}。",
                }
            )
            gate_details["structural"] = "rejected"
        else:
            gate_details["structural"] = "passed"
    except Exception as exc:
        rejections.append(
            {
                "gate": "structural",
                "code": "STRUCTURAL_VALIDATION_FAILED",
                "message": str(exc),
            }
        )
        gate_details["structural"] = "rejected"
        candidate = original
        descriptions = []

    # --- Gate 2: Policy (PermissionStore + AI external-data check) ---
    if not rejections:
        if permissions is not None:
            decision = permissions.authorize(
                project_id=project_id,
                action="workflow.edit",
                task_authorized=task_authorized,
            )
            if not decision.get("allowed"):
                rejections.append(
                    {
                        "gate": "policy",
                        "code": "POLICY_DENIED",
                        "message": str(decision.get("reason", "权限策略拒绝该图更新。")),
                    }
                )
        orig_ai_nodes = {
            node.get("id"): node
            for node in original.get("data", {}).get("nodes", [])
            if isinstance(node, dict) and node.get("data", {}).get("type") == "StudyUIAIAnalysis"
        }
        cand_ai_nodes = [
            node
            for node in candidate.get("data", {}).get("nodes", [])
            if isinstance(node, dict) and node.get("data", {}).get("type") == "StudyUIAIAnalysis"
        ]
        has_new_ai = any(
            node.get("id") not in orig_ai_nodes or node != orig_ai_nodes[node.get("id")]
            for node in cand_ai_nodes
        )
        if has_new_ai and not allow_external_ai_without_approval:
            rejections.append(
                {
                    "gate": "policy",
                    "code": "EXTERNAL_AI_APPROVAL_REQUIRED",
                    "message": "新增 StudyUIAIAnalysis 节点会触发外部模型数据传输，须"
                    "经一次性人工审批后方可合入。",
                }
            )
        gate_details["policy"] = "rejected" if rejections else "passed"

    # --- Gate 3: Compile (sanitize against installed components) ---
    if not rejections:
        if not compile_check:
            gate_details["compile"] = "skipped"
        else:
            try:
                candidate = sanitize_installed_components(candidate, catalog)
                gate_details["compile"] = "passed"
            except Exception as exc:
                rejections.append(
                    {
                        "gate": "compile",
                        "code": "COMPILE_SANITY_FAILED",
                        "message": str(exc),
                    }
                )
                gate_details["compile"] = "rejected"

    if rejections:
        if ledger is not None and run_id:
            ledger.append_event(
                run_id,
                "graph_update_rejected",
                {
                    "base_digest": original_digest,
                    "rationale": str(rationale)[:500],
                    "rejections": rejections,
                    "gate_details": gate_details,
                },
            )
        return GraphUpdateResult(
            accepted=False,
            flow=original,
            digest=original_digest,
            descriptions=(),
            rejections=tuple(rejections),
            gate_details=gate_details,
            graph_version=ledger.latest_version(run_id) if (ledger is not None and run_id) else None,
        )

    new_digest = flow_digest(candidate)
    version = None
    if ledger is not None and run_id:
        version = ledger.record_graph_version(
            run_id,
            candidate,
            reason=rationale or "; ".join(descriptions),
            gate_report=gate_details,
        )

    return GraphUpdateResult(
        accepted=True,
        flow=candidate,
        digest=new_digest,
        descriptions=tuple(descriptions),
        rejections=(),
        gate_details=gate_details,
        graph_version=version,
    )

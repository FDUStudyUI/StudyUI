"""Acceptance gate, manual approval workflow, and rollback for knowledge evolution.

Enforces three non-negotiable governance guarantees:
1. Evaluation lock: ``mode="off"`` blocks all submissions and applications.
2. Zero-regression & boundary integrity: verifies ``B+ \\ B- == empty`` on the
   regression benchmark, zero ``AssetGraph.validate()`` errors, and monotonic
   preservation of physical applicability scopes and known limitations.
3. Manual one-shot approval & one-click rollback: defaults to ``mode="manual"``,
   persists pre-apply snapshots on disk as JSON, and invalidates each
   ``SessionStore`` approval after application so it cannot be replayed.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.permissions import new_approval_id
from ..agent.store import SessionStore
from ..assets.graph import AssetGraph
from ..assets.schema import AssetNode
from .editor import KnowledgePatch, apply_patch_to_node, validate_declarative_patch

EVOLUTION_MODES = ("off", "manual")
EVOLUTION_APPROVAL_ACTION = "knowledge.evolution.apply"

_WEAKENING_PATTERNS = (
    re.compile(r"\b(no limitation|no limitations|bypass guard|ignore guard)\b", re.IGNORECASE),
    re.compile(r"\b(replaces? rietveld|universally valid|valid for all materials)\b", re.IGNORECASE),
    re.compile(r"(无任何限制|无限制|跳过\s*guard|绕过\s*guard|替代\s*rietveld|适用一切材料)", re.IGNORECASE),
)

BenchmarkRunner = Callable[[AssetGraph], dict[str, bool]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    raw = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    try:
        tmp.write_text(raw, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _clone_graph(graph: AssetGraph) -> AssetGraph:
    cloned = AssetGraph()
    for node in graph.nodes():
        cloned.add_asset(node)
    for edge in graph.edges():
        cloned.add_edge(edge)
    return cloned


def _node_from_dict(data: dict[str, Any]) -> AssetNode:
    return AssetNode(
        id=str(data["id"]),
        type=str(data["type"]),
        title=str(data["title"]),
        version=str(data.get("version", "1.0.0")),
        scope=str(data.get("scope", "bundled")),
        domain=str(data.get("domain", "general")),
        entrypoint=str(data.get("entrypoint", "")),
        description=str(data.get("description", "")),
        applicability_scope=tuple(str(x) for x in data.get("applicability_scope", ())),
        out_of_scope_cases=tuple(str(x) for x in data.get("out_of_scope_cases", ())),
        standards_refs=tuple(dict(ref) for ref in data.get("standards_refs", ())),
        known_limitations=tuple(str(x) for x in data.get("known_limitations", ())),
        metadata=dict(data.get("metadata") or {}),
    )


@dataclass(frozen=True)
class AcceptanceReport:
    """Result of deterministic zero-regression and boundary-integrity checks."""

    patch_id: str
    passed: bool
    baseline_passed: tuple[str, ...]
    candidate_passed: tuple[str, ...]
    regressions: tuple[str, ...]
    graph_errors: tuple[str, ...]
    boundary_violations: tuple[str, ...]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "passed": self.passed,
            "baseline_passed": list(self.baseline_passed),
            "candidate_passed": list(self.candidate_passed),
            "regressions": list(self.regressions),
            "graph_errors": list(self.graph_errors),
            "boundary_violations": list(self.boundary_violations),
            "reasons": list(self.reasons),
        }


def check_boundary_integrity(
    before: AssetNode,
    after: AssetNode,
    added_values: tuple[str, ...] = (),
) -> list[str]:
    """Ensure physical applicability scopes and known limitations are never weakened."""
    violations: list[str] = []
    for field_name in ("applicability_scope", "out_of_scope_cases", "known_limitations"):
        before_set = set(getattr(before, field_name))
        after_set = set(getattr(after, field_name))
        removed = sorted(before_set - after_set)
        if removed:
            violations.append(
                f"Field '{field_name}' removed existing boundary statement(s): {removed}"
            )
    for text in added_values:
        for pattern in _WEAKENING_PATTERNS:
            if pattern.search(text):
                violations.append(
                    f"Proposed text '{text}' weakens physical applicability boundaries."
                )
                break
    return violations


def evaluate_patch(
    patch: KnowledgePatch,
    asset_graph: AssetGraph,
    *,
    benchmark_runner: BenchmarkRunner | None = None,
) -> AcceptanceReport:
    """Run declarative validation, graph integrity, boundary review, and B+\\B- gate."""
    reasons: list[str] = []
    declarative_errors = validate_declarative_patch(patch, asset_graph)
    if declarative_errors:
        return AcceptanceReport(
            patch_id=patch.patch_id,
            passed=False,
            baseline_passed=(),
            candidate_passed=(),
            regressions=(),
            graph_errors=tuple(declarative_errors),
            boundary_violations=(),
            reasons=tuple(declarative_errors),
        )

    before_node = asset_graph.get(patch.target_asset_id)
    assert before_node is not None
    after_node = apply_patch_to_node(before_node, patch)

    boundary_violations = check_boundary_integrity(before_node, after_node, patch.values)
    reasons.extend(boundary_violations)

    candidate_graph = _clone_graph(asset_graph)
    candidate_graph.add_asset(after_node, overwrite=True)
    graph_errors = [f"{issue.code}: {issue.message}" for issue in candidate_graph.errors()]
    reasons.extend(graph_errors)

    baseline_passed: list[str] = []
    candidate_passed: list[str] = []
    regressions: list[str] = []
    if benchmark_runner is not None:
        base_results = benchmark_runner(asset_graph)
        cand_results = benchmark_runner(candidate_graph)
        b_plus = {case_id for case_id, ok in base_results.items() if ok}
        b_minus = {case_id for case_id, ok in cand_results.items() if ok}
        baseline_passed = sorted(b_plus)
        candidate_passed = sorted(b_minus)
        regressions = sorted(b_plus - b_minus)
        if regressions:
            reasons.append(
                f"Zero-regression gate failed (B+ \\ B- non-empty): {regressions}"
            )

    passed = not reasons
    return AcceptanceReport(
        patch_id=patch.patch_id,
        passed=passed,
        baseline_passed=tuple(baseline_passed),
        candidate_passed=tuple(candidate_passed),
        regressions=tuple(regressions),
        graph_errors=tuple(graph_errors),
        boundary_violations=tuple(boundary_violations),
        reasons=tuple(reasons),
    )


class EvolutionController:
    """Manages gated submission, one-shot manual approval, application, and rollback."""

    def __init__(
        self,
        *,
        store: SessionStore,
        storage_dir: str | Path,
        mode: str = "manual",
    ) -> None:
        if mode not in EVOLUTION_MODES:
            raise ValueError(f"Unsupported evolution mode {mode!r}; expected one of {EVOLUTION_MODES}")
        self.store = store
        self.mode = mode
        self.storage_dir = Path(storage_dir).resolve()
        self.patches_dir = self.storage_dir / "patches"
        self.patches_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, patch_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", patch_id)
        return self.patches_dir / f"{safe}.json"

    def _save_record(self, patch_id: str, record: dict[str, Any]) -> None:
        _atomic_write_json(self._record_path(patch_id), record)

    def get_record(self, patch_id: str) -> dict[str, Any] | None:
        path = self._record_path(patch_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def submit_patch(
        self,
        patch: KnowledgePatch,
        asset_graph: AssetGraph,
        *,
        session_id: str,
        project_id: str | None = None,
        benchmark_runner: BenchmarkRunner | None = None,
    ) -> dict[str, Any]:
        """Evaluate a declarative patch and submit it for manual one-shot approval."""
        if self.mode == "off":
            return {
                "status": "disabled",
                "patch_id": patch.patch_id,
                "approval_id": None,
                "reason": "Knowledge evolution is locked off (mode='off').",
            }

        report = evaluate_patch(patch, asset_graph, benchmark_runner=benchmark_runner)
        if not report.passed:
            record = {
                "patch_id": patch.patch_id,
                "status": "rejected_by_gate",
                "patch": patch.to_dict(),
                "acceptance_report": report.to_dict(),
                "approval_id": None,
                "updated_at": _now(),
            }
            self._save_record(patch.patch_id, record)
            return {
                "status": "rejected_by_gate",
                "patch_id": patch.patch_id,
                "approval_id": None,
                "report": report.to_dict(),
            }

        approval_id = new_approval_id()
        self.store.create_approval(
            approval_id=approval_id,
            session_id=session_id,
            project_id=project_id,
            action=EVOLUTION_APPROVAL_ACTION,
            reason=f"Apply declarative knowledge patch {patch.patch_id} to {patch.target_asset_id}",
            request={
                "patch_id": patch.patch_id,
                "target_asset_id": patch.target_asset_id,
                "target_asset_type": patch.target_asset_type,
                "field": patch.field,
                "values": list(patch.values),
            },
        )
        record = {
            "patch_id": patch.patch_id,
            "status": "pending_approval",
            "patch": patch.to_dict(),
            "acceptance_report": report.to_dict(),
            "approval_id": approval_id,
            "before_snapshot": None,
            "updated_at": _now(),
        }
        self._save_record(patch.patch_id, record)
        return {
            "status": "pending_approval",
            "patch_id": patch.patch_id,
            "approval_id": approval_id,
            "report": report.to_dict(),
        }

    def apply_approved_patch(self, patch_id: str, asset_graph: AssetGraph) -> dict[str, Any]:
        """Apply an approved declarative patch and invalidate its one-shot approval."""
        if self.mode == "off":
            raise RuntimeError("Knowledge evolution is locked off (mode='off').")

        record = self.get_record(patch_id)
        if record is None:
            raise FileNotFoundError(f"Unknown patch_id: {patch_id}")
        if record.get("status") != "pending_approval":
            raise RuntimeError(f"Patch {patch_id} is not pending approval (status={record.get('status')}).")

        approval_id = str(record.get("approval_id") or "")
        approval = self.store.get_approval(approval_id)
        if approval is None or approval.get("status") != "approved":
            raise PermissionError(
                f"Patch {patch_id} requires an approved SessionStore decision before application."
            )

        patch = KnowledgePatch.from_dict(record["patch"])
        before_node = asset_graph.get(patch.target_asset_id)
        if before_node is None:
            raise KeyError(f"Target asset '{patch.target_asset_id}' not found in AssetGraph.")

        updated_node = apply_patch_to_node(before_node, patch)
        asset_graph.add_asset(updated_node, overwrite=True)
        self.store.invalidate_approval(approval_id)

        record["before_snapshot"] = before_node.to_dict()
        record["after_snapshot"] = updated_node.to_dict()
        record["status"] = "applied"
        record["applied_at"] = _now()
        record["updated_at"] = _now()
        self._save_record(patch_id, record)
        return {
            "status": "applied",
            "patch_id": patch_id,
            "target_asset_id": updated_node.id,
            "new_version": updated_node.version,
        }

    def rollback_patch(self, patch_id: str, asset_graph: AssetGraph) -> dict[str, Any]:
        """Restore the exact pre-patch AssetNode snapshot in one click."""
        record = self.get_record(patch_id)
        if record is None:
            raise FileNotFoundError(f"Unknown patch_id: {patch_id}")
        if record.get("status") != "applied" or not record.get("before_snapshot"):
            raise RuntimeError(f"Patch {patch_id} cannot be rolled back (status={record.get('status')}).")

        restored_node = _node_from_dict(record["before_snapshot"])
        asset_graph.add_asset(restored_node, overwrite=True)
        record["status"] = "rolled_back"
        record["rolled_back_at"] = _now()
        record["updated_at"] = _now()
        self._save_record(patch_id, record)
        return {
            "status": "rolled_back",
            "patch_id": patch_id,
            "target_asset_id": restored_node.id,
            "restored_version": restored_node.version,
        }

    def apply_persisted_patches(self, asset_graph: AssetGraph) -> list[str]:
        """Replay all previously applied declarative patches onto ``asset_graph``."""
        applied_ids: list[str] = []
        records: list[dict[str, Any]] = []
        for path in sorted(self.patches_dir.glob("*.json")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(rec, dict) and rec.get("status") == "applied":
                records.append(rec)
        records.sort(key=lambda r: (str(r.get("applied_at") or ""), str(r.get("patch_id") or "")))
        for rec in records:
            patch = KnowledgePatch.from_dict(rec["patch"])
            node = asset_graph.get(patch.target_asset_id)
            if node is None:
                continue
            updated = apply_patch_to_node(node, patch)
            asset_graph.add_asset(updated, overwrite=True)
            applied_ids.append(patch.patch_id)
        return applied_ids

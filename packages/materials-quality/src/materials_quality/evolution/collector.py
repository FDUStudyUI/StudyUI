"""Evidence collector for declarative knowledge evolution.

Extracts structured evidence items ``e = (Z, f, omega)`` from:
- ``WorkflowLedger`` (``events.jsonl``): runtime GUARD blocks, node failures,
  rejected graph updates, and rejected human-gate decisions
- ``SessionStore`` (``agent.sqlite3``): session events and tool errors
- Explicit user or materials-expert corrections
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..agent.store import SessionStore
from ..agent.workflow_ledger import WorkflowLedger

_TRANSIENT_PATTERNS = (
    re.compile(r"\b(timeout|timed out|readtimeout|connecttimeout)\b", re.IGNORECASE),
    re.compile(r"\b(502|503|504|429|rate[ _-]?limit)\b", re.IGNORECASE),
    re.compile(r"\b(connection reset|econnrefused|econnreset|network is unreachable)\b", re.IGNORECASE),
    re.compile(r"\b(temporary failure|temporarily unavailable|resource temporarily unavailable)\b", re.IGNORECASE),
    re.compile(r"operation not permitted.*socket|socketserver", re.IGNORECASE),
)

_DOMAIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("xrd", ("xrd", "diffraction", "bragg", "scherrer", "rietveld", "cif", "2theta", "two_theta", "cuka")),
    ("mechanics", ("tensile", "stress", "strain", "modulus", "young", "yield", "astm e8", "iso 6892", "mechanics")),
    ("spectra", ("raman", "ftir", "xps", "spectrum", "spectra", "baseline", "wavenumber", "binding energy")),
    ("battery", ("battery", "cycle", "coulombic", "voltage", "capacity", "pybamm", "c-rate", "discharge", "cell")),
    ("thermal", ("dsc", "tga", "thermal", "glass transition", "tg", "melting", "heat flow", "decomposition")),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def is_transient_failure(text: str) -> bool:
    """Return True when an error looks like transient infrastructure/network noise."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _TRANSIENT_PATTERNS)


def infer_domain(text: str, payload: dict[str, Any] | None = None) -> str:
    """Infer materials domain from structured payload fields or free text."""
    data = payload or {}
    for key in ("domain", "task_family", "family", "materials_domain"):
        raw = str(data.get(key) or "").strip().lower()
        if raw in {"xrd", "mechanics", "spectra", "battery", "thermal"}:
            return raw
    haystack = f"{text} {data}".lower()
    for domain, keywords in _DOMAIN_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return domain
    return "general"


@dataclass(frozen=True)
class EvidenceItem:
    """Single structured evidence record ``e = (Z, f, omega)``."""

    id: str
    source: str
    kind: str
    domain: str
    summary: str
    failure_signal: str
    trajectory_ref: dict[str, Any] = field(default_factory=dict)
    correction: str = ""
    asset_hint: str = ""
    transient: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "kind": self.kind,
            "domain": self.domain,
            "summary": self.summary,
            "failure_signal": self.failure_signal,
            "trajectory_ref": dict(self.trajectory_ref),
            "correction": self.correction,
            "asset_hint": self.asset_hint,
            "transient": self.transient,
        }


@dataclass(frozen=True)
class EvidenceBundle:
    """Collection of extracted evidence items across runtime logs and corrections."""

    items: tuple[EvidenceItem, ...]
    collected_at: str
    sources: tuple[str, ...]

    def non_transient_items(self) -> list[EvidenceItem]:
        return [item for item in self.items if not item.transient]

    def to_dict(self) -> dict[str, Any]:
        return {
            "collected_at": self.collected_at,
            "sources": list(self.sources),
            "total_items": len(self.items),
            "non_transient_count": len(self.non_transient_items()),
            "items": [item.to_dict() for item in self.items],
        }


def _collect_from_ledger(ledger: WorkflowLedger, run_ids: Iterable[str] | None) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if run_ids is None:
        target_runs = sorted(
            path.name
            for path in ledger.root.iterdir()
            if path.is_dir() and (path / "events.jsonl").is_file()
        )
    else:
        target_runs = list(run_ids)

    for run_id in target_runs:
        for idx, event in enumerate(ledger.read_events(run_id)):
            kind = str(event.get("kind") or "")
            payload = event.get("payload") or {}
            if kind == "guard_blocked":
                code = str(payload.get("code") or payload.get("guard_id") or "GUARD_BLOCKED")
                msg = str(payload.get("message") or payload.get("reason") or code)
                domain = infer_domain(f"{code} {msg}", payload)
                items.append(
                    EvidenceItem(
                        id=_stable_id("ev_ledger", run_id, str(idx), code, msg),
                        source="ledger",
                        kind="guard_blocked",
                        domain=domain,
                        summary=f"Runtime guard blocked execution: {msg}",
                        failure_signal=f"{code}: {msg}",
                        trajectory_ref={"run_id": run_id, "event_index": idx, "ts": event.get("ts")},
                        correction=str(
                            payload.get("recommendation")
                            or payload.get("recommended_action")
                            or payload.get("limitation")
                            or ""
                        ),
                        asset_hint=str(payload.get("asset_id") or ""),
                        transient=is_transient_failure(msg),
                    )
                )
            elif kind == "node_failed":
                node_id = str(payload.get("node_id") or "")
                err = str(payload.get("error") or "node_failed")
                domain = infer_domain(f"{node_id} {err}", payload)
                items.append(
                    EvidenceItem(
                        id=_stable_id("ev_ledger", run_id, str(idx), node_id, err),
                        source="ledger",
                        kind="node_failed",
                        domain=domain,
                        summary=f"Workflow node '{node_id}' failed: {err}",
                        failure_signal=err,
                        trajectory_ref={
                            "run_id": run_id,
                            "node_id": node_id,
                            "event_index": idx,
                            "ts": event.get("ts"),
                        },
                        asset_hint=str(payload.get("asset_id") or ""),
                        transient=is_transient_failure(err),
                    )
                )
            elif kind == "graph_update_rejected":
                rejections = payload.get("rejections") or []
                rejection_text = "; ".join(
                    f"{r.get('code', '')}: {r.get('message', '')}"
                    for r in rejections
                    if isinstance(r, dict)
                )
                reason = str(
                    rejection_text
                    or payload.get("reason")
                    or payload.get("rationale")
                    or payload.get("errors")
                    or "graph_update_rejected"
                )
                domain = infer_domain(reason, payload)
                items.append(
                    EvidenceItem(
                        id=_stable_id("ev_ledger", run_id, str(idx), reason),
                        source="ledger",
                        kind="graph_update_rejected",
                        domain=domain,
                        summary=f"Graph update rejected by gate: {reason}",
                        failure_signal=reason,
                        trajectory_ref={"run_id": run_id, "event_index": idx, "ts": event.get("ts")},
                        asset_hint=str(payload.get("asset_id") or ""),
                        transient=is_transient_failure(reason),
                    )
                )
            elif kind == "human_gate_resolved" and str(payload.get("decision") or "") == "rejected":
                reason = str(
                    payload.get("reason")
                    or payload.get("gate_kind")
                    or payload.get("action")
                    or "human_gate_rejected"
                )
                domain = infer_domain(f"{reason} {payload.get('reviewer_note') or ''}", payload)
                items.append(
                    EvidenceItem(
                        id=_stable_id("ev_ledger", run_id, str(idx), reason),
                        source="ledger",
                        kind="human_gate_rejected",
                        domain=domain,
                        summary=f"Human gate rejected action: {reason}",
                        failure_signal=reason,
                        trajectory_ref={"run_id": run_id, "event_index": idx, "ts": event.get("ts")},
                        correction=str(payload.get("reviewer_note") or payload.get("comment") or ""),
                        asset_hint=str(payload.get("asset_id") or ""),
                        transient=False,
                    )
                )
    return items


def _collect_from_store(store: SessionStore, session_ids: Iterable[str] | None) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if session_ids is None:
        return items
    interesting_kinds = {"guard_blocked", "tool_error", "workflow_failed", "user_correction"}
    for session_id in session_ids:
        for idx, event in enumerate(store.events(session_id, limit=500)):
            kind = str(event.get("kind") or "")
            if kind not in interesting_kinds:
                continue
            detail = event.get("detail") or {}
            msg = str(detail.get("message") or detail.get("error") or detail.get("summary") or kind)
            domain = infer_domain(msg, detail)
            event_ref = str(event.get("id") or f"{idx}:{event.get('created_at') or ''}")
            items.append(
                EvidenceItem(
                    id=_stable_id("ev_store", session_id, event_ref, kind, msg),
                    source="session_store",
                    kind=kind,
                    domain=domain,
                    summary=msg,
                    failure_signal=str(detail.get("code") or detail.get("error") or msg),
                    trajectory_ref={
                        "session_id": session_id,
                        "event_id": event.get("id"),
                        "created_at": event.get("created_at"),
                    },
                    correction=str(detail.get("correction") or ""),
                    asset_hint=str(detail.get("asset_id") or ""),
                    transient=is_transient_failure(msg) and kind != "user_correction",
                )
            )
    return items


def _collect_user_corrections(corrections: Iterable[dict[str, Any]] | None) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if corrections is None:
        return items
    for idx, entry in enumerate(corrections):
        summary = str(entry.get("summary") or entry.get("correction") or "").strip()
        correction = str(entry.get("correction") or summary).strip()
        if not correction:
            continue
        failure_signal = str(entry.get("failure_signal") or summary)
        domain = infer_domain(f"{summary} {correction}", entry)
        items.append(
            EvidenceItem(
                id=_stable_id("ev_user", str(idx), domain, correction),
                source="user_correction",
                kind="user_correction",
                domain=domain,
                summary=summary or correction,
                failure_signal=failure_signal,
                trajectory_ref=dict(entry.get("trajectory_ref") or {}),
                correction=correction,
                asset_hint=str(entry.get("asset_id") or ""),
                transient=False,
            )
        )
    return items


def collect_evidence(
    *,
    store: SessionStore | None = None,
    ledger: WorkflowLedger | None = None,
    session_ids: Iterable[str] | None = None,
    run_ids: Iterable[str] | None = None,
    user_corrections: Iterable[dict[str, Any]] | None = None,
) -> EvidenceBundle:
    """Collect structured evidence bundles across ledger, session store, and corrections."""
    items: list[EvidenceItem] = []
    sources: list[str] = []

    if ledger is not None:
        sources.append("ledger")
        items.extend(_collect_from_ledger(ledger, run_ids))
    if store is not None:
        sources.append("session_store")
        items.extend(_collect_from_store(store, session_ids))
    if user_corrections is not None:
        sources.append("user_correction")
        items.extend(_collect_user_corrections(user_corrections))

    return EvidenceBundle(
        items=tuple(items),
        collected_at=_now(),
        sources=tuple(sources),
    )

"""Append-only workflow event ledger and versioned graph snapshots for resumable runs.

Stores each workflow run under ``<root>/<run_id>/`` with:
- ``graph_v{k}.json``: immutable versioned workflow snapshots
- ``events.jsonl``: append-only JSONL ledger of lifecycle, node, guard, human-gate,
  and graph-update events

Integrates with ``materials_quality.science.checkpoints`` so interrupted runs
can be identified as ``interrupted_resumable`` across server restarts and
resumed without re-executing pure scientific steps whose verified checkpoints
remain valid on disk.
"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .workflow import flow_digest

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


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


class WorkflowLedger:
    """Durable append-only event ledger and versioned graph store."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _run_dir(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"Invalid workflow run_id: {run_id!r}")
        return self.root / run_id

    def exists(self, run_id: str) -> bool:
        try:
            run_dir = self._run_dir(run_id)
        except ValueError:
            return False
        return (run_dir / "events.jsonl").is_file()

    def start_run(
        self,
        run_id: str,
        flow: dict[str, Any],
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        version = self.record_graph_version(run_id, flow, reason="initial_snapshot")
        event = self.append_event(
            run_id,
            "run_started",
            {
                "flow_id": flow.get("id"),
                "flow_name": flow.get("name", ""),
                "flow_digest": flow_digest(flow),
                "graph_version": version,
                "session_id": session_id,
                "metadata": dict(metadata or {}),
            },
        )
        return {"run_id": run_id, "graph_version": version, "event": event}

    def record_graph_version(
        self,
        run_id: str,
        flow: dict[str, Any],
        *,
        reason: str = "",
        gate_report: dict[str, Any] | None = None,
    ) -> int:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        version = self.latest_version(run_id) + 1
        snapshot_path = run_dir / f"graph_v{version}.json"
        _atomic_write_json(snapshot_path, deepcopy(flow))
        self.append_event(
            run_id,
            "graph_version_committed",
            {
                "graph_version": version,
                "flow_id": flow.get("id"),
                "flow_digest": flow_digest(flow),
                "reason": str(reason)[:500],
                "gate_report": gate_report,
            },
        )
        return version

    def append_event(self, run_id: str, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "events.jsonl"
        record = {
            "ts": _now(),
            "run_id": run_id,
            "kind": str(kind),
            "payload": dict(payload or {}),
        }
        line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
        return record

    def read_events(self, run_id: str) -> list[dict[str, Any]]:
        events_path = self._run_dir(run_id) / "events.jsonl"
        if not events_path.is_file():
            return []
        events: list[dict[str, Any]] = []
        for raw_line in events_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            events.append(json.loads(line))
        return events

    def latest_version(self, run_id: str) -> int:
        run_dir = self._run_dir(run_id)
        if not run_dir.is_dir():
            return 0
        versions = []
        for path in run_dir.glob("graph_v*.json"):
            match = re.fullmatch(r"graph_v(\d+)\.json", path.name)
            if match:
                versions.append(int(match.group(1)))
        return max(versions, default=0)

    def load_graph(self, run_id: str, version: int | None = None) -> dict[str, Any]:
        target_version = self.latest_version(run_id) if version is None else int(version)
        if target_version <= 0:
            raise FileNotFoundError(f"No graph snapshot recorded for run {run_id}")
        path = self._run_dir(run_id) / f"graph_v{target_version}.json"
        if not path.is_file():
            raise FileNotFoundError(f"Missing graph snapshot: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def summarize_run(self, run_id: str) -> dict[str, Any]:
        events = self.read_events(run_id)
        if not events:
            raise FileNotFoundError(f"No ledger events found for run {run_id}")

        status = "running"
        completed_nodes: dict[str, dict[str, Any]] = {}
        failed_nodes: dict[str, str] = {}
        pending_human_gates: dict[str, dict[str, Any]] = {}
        guard_violations: list[dict[str, Any]] = []
        rejected_updates: list[dict[str, Any]] = []
        checkpoint_keys: dict[str, str] = {}

        for event in events:
            kind = event.get("kind")
            payload = event.get("payload") or {}
            if kind == "node_completed":
                node_id = str(payload.get("node_id") or "")
                if node_id:
                    completed_nodes[node_id] = dict(payload)
                    failed_nodes.pop(node_id, None)
                    if payload.get("checkpoint_key"):
                        checkpoint_keys[node_id] = str(payload["checkpoint_key"])
            elif kind == "node_failed":
                node_id = str(payload.get("node_id") or "")
                if node_id:
                    failed_nodes[node_id] = str(payload.get("error", ""))
            elif kind == "guard_blocked":
                guard_violations.append(dict(payload))
            elif kind == "human_gate_requested":
                approval_id = str(payload.get("approval_id") or "")
                if approval_id:
                    pending_human_gates[approval_id] = dict(payload)
            elif kind == "human_gate_resolved":
                approval_id = str(payload.get("approval_id") or "")
                pending_human_gates.pop(approval_id, None)
            elif kind == "graph_update_rejected":
                rejected_updates.append(dict(payload))
            elif kind == "run_completed":
                status = "completed"
            elif kind == "run_failed":
                status = "failed"
            elif kind == "run_cancelled":
                status = "cancelled"
            elif kind == "run_interrupted":
                status = "interrupted_resumable"

        if pending_human_gates and status == "running":
            status = "waiting_human_gate"

        latest_version = self.latest_version(run_id)
        resumable = latest_version > 0 and status in {
            "running",
            "interrupted_resumable",
            "waiting_human_gate",
        }
        return {
            "run_id": run_id,
            "status": status,
            "resumable": resumable,
            "latest_version": latest_version,
            "event_count": len(events),
            "completed_nodes": sorted(completed_nodes),
            "failed_nodes": failed_nodes,
            "checkpoint_keys": checkpoint_keys,
            "pending_human_gates": list(pending_human_gates.values()),
            "guard_violations": guard_violations,
            "rejected_updates": rejected_updates,
        }

    def resume_plan(self, run_id: str, checkpoint_root: str | Path | None = None) -> dict[str, Any]:
        """Compute which nodes can be reused from disk checkpoints vs. need execution."""
        summary = self.summarize_run(run_id)
        flow = self.load_graph(run_id)
        all_nodes = [
            str(node.get("id"))
            for node in flow.get("data", {}).get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        ]
        cp_root = Path(checkpoint_root).resolve() if checkpoint_root is not None else None

        reusable_nodes: list[str] = []
        pending_nodes: list[str] = []
        completed_set = set(summary["completed_nodes"])

        for node_id in all_nodes:
            key = summary["checkpoint_keys"].get(node_id)
            has_disk_cp = bool(key and cp_root is not None and (cp_root / key / "result.json").is_file())
            if node_id in completed_set and (cp_root is None or has_disk_cp):
                reusable_nodes.append(node_id)
            else:
                pending_nodes.append(node_id)

        return {
            "run_id": run_id,
            "graph_version": summary["latest_version"],
            "flow_digest": flow_digest(flow),
            "resumable": summary["resumable"] and not summary["pending_human_gates"],
            "blocked_by_human_gates": summary["pending_human_gates"],
            "reusable_nodes": reusable_nodes,
            "pending_nodes": pending_nodes,
        }

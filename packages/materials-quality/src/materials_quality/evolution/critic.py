"""Evidence critic that filters transient noise and localizes K/S asset gaps."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

from ..assets.graph import AssetGraph
from ..assets.schema import AssetNode
from .collector import EvidenceBundle, EvidenceItem

EVOLVABLE_ASSET_TYPES = frozenset({"K", "S"})


@dataclass(frozen=True)
class CritiqueFinding:
    """Localized knowledge or skill gap backed by non-transient evidence."""

    finding_id: str
    target_asset_id: str
    target_asset_type: str
    domain: str
    issue_category: str
    rationale: str
    proposed_addition: str
    evidence_ids: tuple[str, ...]
    occurrences: int

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "target_asset_id": self.target_asset_id,
            "target_asset_type": self.target_asset_type,
            "domain": self.domain,
            "issue_category": self.issue_category,
            "rationale": self.rationale,
            "proposed_addition": self.proposed_addition,
            "evidence_ids": list(self.evidence_ids),
            "occurrences": self.occurrences,
        }


def _resolve_target_asset(item: EvidenceItem, asset_graph: AssetGraph) -> AssetNode | None:
    """Locate the most relevant K or S asset in ``asset_graph`` for ``item``."""
    if item.asset_hint:
        hinted = asset_graph.get(item.asset_hint)
        if hinted is not None and hinted.type in EVOLVABLE_ASSET_TYPES:
            return hinted

    candidates = [
        node
        for node in asset_graph.by_domain(item.domain)
        if node.type in EVOLVABLE_ASSET_TYPES
    ]
    if not candidates:
        candidates = [
            node
            for node in asset_graph.nodes()
            if node.type in EVOLVABLE_ASSET_TYPES
        ]
    if not candidates:
        return None

    haystack = f"{item.summary} {item.failure_signal} {item.correction}".lower()
    tokens = {tok for tok in haystack.replace(":", " ").replace("/", " ").split() if len(tok) >= 3}

    def _score(node: AssetNode) -> tuple[int, int, str]:
        node_text = f"{node.id} {node.title} {node.description}".lower()
        overlap = sum(1 for tok in tokens if tok in node_text)
        type_priority = 1 if node.type == "K" else 0
        return (overlap, type_priority, node.id)

    return max(candidates, key=_score)


def _classify_category(item: EvidenceItem) -> str:
    text = f"{item.kind} {item.summary} {item.failure_signal} {item.correction}".lower()
    if any(kw in text for kw in ("out of scope", "out_of_scope", "不适用", "超出适用范围", "禁止用于")):
        return "out_of_scope_case"
    if item.kind == "guard_blocked" or any(kw in text for kw in ("limitation", "限制", "前提", "boundary", "guard")):
        return "known_limitation"
    return "method_pitfall"


def _build_proposed_addition(items: list[EvidenceItem]) -> str:
    for item in items:
        if item.correction.strip():
            return item.correction.strip()
    primary = items[0]
    return f"注意检查并披露：{primary.failure_signal.strip()}"


def critique_evidence(
    bundle: EvidenceBundle,
    asset_graph: AssetGraph,
    *,
    min_occurrences: int = 1,
) -> list[CritiqueFinding]:
    """Filter transient noise and localize recurring gaps to K/S assets."""
    if min_occurrences < 1:
        raise ValueError("min_occurrences must be >= 1")

    grouped: dict[tuple[str, str, str], list[EvidenceItem]] = defaultdict(list)
    resolved_nodes: dict[str, AssetNode] = {}

    for item in bundle.non_transient_items():
        target = _resolve_target_asset(item, asset_graph)
        if target is None:
            continue
        resolved_nodes[target.id] = target
        category = _classify_category(item)
        key_text = (item.correction or item.failure_signal).strip().lower()[:160]
        grouped[(target.id, category, key_text)].append(item)

    findings: list[CritiqueFinding] = []
    for (target_id, category, key_text), items in sorted(grouped.items()):
        if len(items) < min_occurrences:
            continue
        node = resolved_nodes[target_id]
        proposed = _build_proposed_addition(items)
        digest = hashlib.sha256(f"{target_id}|{category}|{key_text}".encode("utf-8")).hexdigest()[:12]
        findings.append(
            CritiqueFinding(
                finding_id=f"finding_{digest}",
                target_asset_id=node.id,
                target_asset_type=node.type,
                domain=node.domain,
                issue_category=category,
                rationale=(
                    f"Localized {len(items)} non-transient evidence item(s) "
                    f"to {node.type} asset '{node.id}' ({category})."
                ),
                proposed_addition=proposed,
                evidence_ids=tuple(item.id for item in items),
                occurrences=len(items),
            )
        )
    return findings

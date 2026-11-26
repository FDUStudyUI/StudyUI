"""In-memory scientific asset graph with validation and role subgraph routing."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any

from .schema import (
    ASSET_SCOPES,
    ASSET_TYPES,
    BOUNDARY_REQUIRED_TYPES,
    EDGE_TYPES,
    AssetEdge,
    AssetNode,
    ValidationIssue,
)

TRAVERSAL_EDGE_KINDS = frozenset({"MOUNT", "DEP", "CALL", "PART", "VERIFY", "EVIDENCE"})


class AssetGraph:
    """Directed graph of versioned StudyUI scientific assets."""

    def __init__(self) -> None:
        self._nodes: dict[str, AssetNode] = {}
        self._edges: list[AssetEdge] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        self._outgoing: dict[str, list[AssetEdge]] = {}
        self._incoming: dict[str, list[AssetEdge]] = {}

    def add_asset(self, node: AssetNode, *, overwrite: bool = False) -> None:
        if not node.id or not isinstance(node.id, str):
            raise ValueError("AssetNode.id must be a non-empty string")
        if node.id in self._nodes and not overwrite:
            raise ValueError(f"Duplicate asset id: {node.id}")
        self._nodes[node.id] = node
        self._outgoing.setdefault(node.id, [])
        self._incoming.setdefault(node.id, [])

    def add_edge(self, edge: AssetEdge) -> None:
        key = (edge.source, edge.target, edge.kind)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._edges.append(edge)
        self._outgoing.setdefault(edge.source, []).append(edge)
        self._incoming.setdefault(edge.target, []).append(edge)

    def get(self, asset_id: str) -> AssetNode | None:
        return self._nodes.get(asset_id)

    def __contains__(self, asset_id: str) -> bool:
        return asset_id in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def nodes(self) -> list[AssetNode]:
        return list(self._nodes.values())

    def edges(self) -> list[AssetEdge]:
        return list(self._edges)

    def by_type(self, asset_type: str) -> list[AssetNode]:
        return [node for node in self._nodes.values() if node.type == asset_type]

    def by_scope(self, scope: str) -> list[AssetNode]:
        return [node for node in self._nodes.values() if node.scope == scope]

    def by_domain(self, domain: str) -> list[AssetNode]:
        return [node for node in self._nodes.values() if node.domain == domain]

    def edges_from(self, asset_id: str, *, kinds: Iterable[str] | None = None) -> list[AssetEdge]:
        allowed = set(kinds) if kinds is not None else None
        return [edge for edge in self._outgoing.get(asset_id, []) if allowed is None or edge.kind in allowed]

    def edges_to(self, asset_id: str, *, kinds: Iterable[str] | None = None) -> list[AssetEdge]:
        allowed = set(kinds) if kinds is not None else None
        return [edge for edge in self._incoming.get(asset_id, []) if allowed is None or edge.kind in allowed]

    def validate(self) -> list[ValidationIssue]:
        """Run deterministic integrity, schema, and applicability-boundary checks."""
        issues: list[ValidationIssue] = []

        for node in self._nodes.values():
            if node.type not in ASSET_TYPES:
                issues.append(
                    ValidationIssue(
                        code="INVALID_ASSET_TYPE",
                        severity="error",
                        asset_id=node.id,
                        message=f"Unknown asset type {node.type!r}; expected one of {ASSET_TYPES}.",
                    )
                )
            if node.scope not in ASSET_SCOPES:
                issues.append(
                    ValidationIssue(
                        code="INVALID_ASSET_SCOPE",
                        severity="error",
                        asset_id=node.id,
                        message=f"Unknown asset scope {node.scope!r}; expected one of {ASSET_SCOPES}.",
                    )
                )
            if not node.title.strip():
                issues.append(
                    ValidationIssue(
                        code="EMPTY_TITLE",
                        severity="error",
                        asset_id=node.id,
                        message="Asset title must not be empty.",
                    )
                )
            if node.type in BOUNDARY_REQUIRED_TYPES:
                if not node.applicability_scope:
                    issues.append(
                        ValidationIssue(
                            code="MISSING_APPLICABILITY_SCOPE",
                            severity="error",
                            asset_id=node.id,
                            message=f"Asset {node.id} ({node.type}) must declare applicability_scope.",
                        )
                    )
                if not node.known_limitations:
                    issues.append(
                        ValidationIssue(
                            code="MISSING_KNOWN_LIMITATIONS",
                            severity="error",
                            asset_id=node.id,
                            message=f"Asset {node.id} ({node.type}) must declare known_limitations.",
                        )
                    )
            if node.type == "R":
                mounted = self.edges_from(node.id, kinds=("MOUNT",))
                if not mounted:
                    issues.append(
                        ValidationIssue(
                            code="ROLE_WITHOUT_MOUNTS",
                            severity="warning",
                            asset_id=node.id,
                            message=f"Role {node.id} has no MOUNT edges to downstream assets.",
                        )
                    )

        for edge in self._edges:
            if edge.kind not in EDGE_TYPES:
                issues.append(
                    ValidationIssue(
                        code="INVALID_EDGE_TYPE",
                        severity="error",
                        asset_id=edge.source,
                        message=f"Unknown edge kind {edge.kind!r}; expected one of {EDGE_TYPES}.",
                    )
                )
            if edge.source not in self._nodes:
                issues.append(
                    ValidationIssue(
                        code="DANGLING_EDGE_SOURCE",
                        severity="error",
                        asset_id=edge.source,
                        message=f"Edge ({edge.source} -[{edge.kind}]-> {edge.target}) has unknown source.",
                    )
                )
            if edge.target not in self._nodes:
                issues.append(
                    ValidationIssue(
                        code="DANGLING_EDGE_TARGET",
                        severity="error",
                        asset_id=edge.source,
                        message=f"Edge ({edge.source} -[{edge.kind}]-> {edge.target}) has unknown target.",
                    )
                )
            if edge.source == edge.target and edge.kind in {"DEP", "PART"}:
                issues.append(
                    ValidationIssue(
                        code="SELF_LOOP_EDGE",
                        severity="error",
                        asset_id=edge.source,
                        message=f"Self-loop is forbidden for {edge.kind} edge on {edge.source}.",
                    )
                )

        return issues

    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.validate() if issue.severity == "error"]

    def subgraph_for_role(
        self,
        role_id: str,
        *,
        scopes: Iterable[str] | None = None,
        max_depth: int = 3,
    ) -> AssetGraph:
        """Return the reachable asset subgraph mounted by ``role_id``."""
        role = self._nodes.get(role_id)
        if role is None or role.type != "R":
            raise ValueError(f"Unknown role asset: {role_id}")
        allowed_scopes = set(scopes) if scopes is not None else set(ASSET_SCOPES)
        sub = AssetGraph()
        if role.scope not in allowed_scopes:
            return sub

        visited: set[str] = {role_id}
        queue: deque[tuple[str, int]] = deque([(role_id, 0)])
        sub.add_asset(role)

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self._outgoing.get(current_id, []):
                if edge.kind not in TRAVERSAL_EDGE_KINDS:
                    continue
                target = self._nodes.get(edge.target)
                if target is None or target.scope not in allowed_scopes:
                    continue
                if target.id not in visited:
                    visited.add(target.id)
                    sub.add_asset(target)
                    queue.append((target.id, depth + 1))

        # Include all edges whose endpoints are both inside the subgraph.
        for edge in self._edges:
            if edge.source in visited and edge.target in visited:
                sub.add_edge(edge)

        return sub

    def summary(self) -> dict[str, Any]:
        counts_by_type = dict.fromkeys(ASSET_TYPES, 0)
        counts_by_scope = dict.fromkeys(ASSET_SCOPES, 0)
        for node in self._nodes.values():
            counts_by_type[node.type] = counts_by_type.get(node.type, 0) + 1
            counts_by_scope[node.scope] = counts_by_scope.get(node.scope, 0) + 1
        issues = self.validate()
        return {
            "total_assets": len(self._nodes),
            "total_edges": len(self._edges),
            "by_type": counts_by_type,
            "by_scope": counts_by_scope,
            "error_count": sum(1 for item in issues if item.severity == "error"),
            "warning_count": sum(1 for item in issues if item.severity == "warning"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "assets": [node.to_dict() for node in sorted(self._nodes.values(), key=lambda item: item.id)],
            "edges": [
                edge.to_dict()
                for edge in sorted(self._edges, key=lambda item: (item.source, item.kind, item.target))
            ],
        }

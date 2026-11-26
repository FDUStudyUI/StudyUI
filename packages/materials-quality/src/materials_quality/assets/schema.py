"""Schema definitions for the StudyUI layered scientific asset graph.

Six versioned asset types mirror the MatOS scientific asset taxonomy while
embedding explicit applicability scopes and known technical limitations for
materials-science governance:

- D: Dataset / real-instrument example assets
- K: Domain knowledge / method card assets
- T: Registered computational tool / Langflow component assets
- S: Research skill assets
- R: Declarative research role assets
- W: Workflow / protocol compiler assets
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ASSET_TYPES = ("D", "K", "T", "S", "R", "W")
ASSET_SCOPES = ("bundled", "user", "project")
EDGE_TYPES = ("DEP", "MOUNT", "CALL", "PART", "EVIDENCE", "VERIFY")

BOUNDARY_REQUIRED_TYPES = frozenset({"K", "S", "W"})


@dataclass(frozen=True)
class AssetNode:
    """Single versioned node in the scientific asset graph."""

    id: str
    type: str
    title: str
    version: str = "1.0.0"
    scope: str = "bundled"
    domain: str = "general"
    entrypoint: str = ""
    description: str = ""
    applicability_scope: tuple[str, ...] = ()
    out_of_scope_cases: tuple[str, ...] = ()
    standards_refs: tuple[dict[str, str], ...] = ()
    known_limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "version": self.version,
            "scope": self.scope,
            "domain": self.domain,
            "entrypoint": self.entrypoint,
            "description": self.description,
            "applicability_scope": list(self.applicability_scope),
            "out_of_scope_cases": list(self.out_of_scope_cases),
            "standards_refs": [dict(ref) for ref in self.standards_refs],
            "known_limitations": list(self.known_limitations),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AssetEdge:
    """Typed directed relationship between two assets."""

    source: str
    target: str
    kind: str
    rationale: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ValidationIssue:
    """Structured diagnostic produced by ``AssetGraph.validate()``."""

    code: str
    severity: str
    asset_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "asset_id": self.asset_id,
            "message": self.message,
        }

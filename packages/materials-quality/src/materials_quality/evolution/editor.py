"""Declarative patch generator for K/S assets (strictly never modifies Python code)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from ..assets.graph import AssetGraph
from ..assets.schema import AssetNode
from .critic import EVOLVABLE_ASSET_TYPES, CritiqueFinding

ALLOWED_PATCH_FIELDS = frozenset(
    {
        "applicability_scope",
        "out_of_scope_cases",
        "known_limitations",
        "metadata.pitfalls",
        "metadata.checklist",
    }
)
ALLOWED_OPERATIONS = frozenset({"append_unique"})
FORBIDDEN_CODE_EXTENSIONS = (".py", ".pyi", ".pyx", ".sh", ".js", ".ts", ".tsx", ".c", ".cpp")

_CATEGORY_TO_FIELD = {
    "out_of_scope_case": "out_of_scope_cases",
    "known_limitation": "known_limitations",
    "boundary_gap": "known_limitations",
    "method_pitfall": "metadata.pitfalls",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bump_patch_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
    return f"{version}.1"


@dataclass(frozen=True)
class KnowledgePatch:
    """Strictly declarative append-only patch targeting a K or S asset."""

    patch_id: str
    target_asset_id: str
    target_asset_type: str
    field: str
    operation: str
    values: tuple[str, ...]
    rationale: str
    evidence_ids: tuple[str, ...]
    source_finding_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "target_asset_id": self.target_asset_id,
            "target_asset_type": self.target_asset_type,
            "field": self.field,
            "operation": self.operation,
            "values": list(self.values),
            "rationale": self.rationale,
            "evidence_ids": list(self.evidence_ids),
            "source_finding_id": self.source_finding_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgePatch:
        return cls(
            patch_id=str(data["patch_id"]),
            target_asset_id=str(data["target_asset_id"]),
            target_asset_type=str(data["target_asset_type"]),
            field=str(data["field"]),
            operation=str(data["operation"]),
            values=tuple(str(v) for v in data.get("values", ())),
            rationale=str(data.get("rationale", "")),
            evidence_ids=tuple(str(e) for e in data.get("evidence_ids", ())),
            source_finding_id=str(data.get("source_finding_id", "")),
            created_at=str(data.get("created_at", "")),
        )


def validate_declarative_patch(patch: KnowledgePatch, asset_graph: AssetGraph) -> list[str]:
    """Verify a patch is strictly declarative and targets a valid K/S asset."""
    errors: list[str] = []
    target_lower = patch.target_asset_id.lower()
    if any(target_lower.endswith(ext) for ext in FORBIDDEN_CODE_EXTENSIONS) or "/" in patch.target_asset_id:
        errors.append(
            f"Patch target '{patch.target_asset_id}' looks like a file/code path; "
            "evolution patches may only modify declarative K/S assets."
        )
    if patch.target_asset_type not in EVOLVABLE_ASSET_TYPES:
        errors.append(
            f"Asset type '{patch.target_asset_type}' is not evolvable; "
            f"allowed types: {sorted(EVOLVABLE_ASSET_TYPES)}."
        )
    node = asset_graph.get(patch.target_asset_id)
    if node is None:
        errors.append(f"Target asset '{patch.target_asset_id}' does not exist in AssetGraph.")
    elif node.type not in EVOLVABLE_ASSET_TYPES:
        errors.append(
            f"Target asset '{node.id}' has type '{node.type}'; only K/S declarative assets may evolve."
        )
    if patch.field not in ALLOWED_PATCH_FIELDS:
        errors.append(
            f"Field '{patch.field}' is not allowed; allowed fields: {sorted(ALLOWED_PATCH_FIELDS)}."
        )
    if patch.operation not in ALLOWED_OPERATIONS:
        errors.append(
            f"Operation '{patch.operation}' is not allowed; allowed operations: {sorted(ALLOWED_OPERATIONS)}."
        )
    if not patch.values or not any(val.strip() for val in patch.values):
        errors.append("Patch values must contain at least one non-empty declarative entry.")
    return errors


def _existing_field_values(node: AssetNode, field_name: str) -> tuple[str, ...]:
    if field_name in {"applicability_scope", "out_of_scope_cases", "known_limitations"}:
        return tuple(getattr(node, field_name))
    if field_name.startswith("metadata."):
        key = field_name.split(".", 1)[1]
        raw = node.metadata.get(key, ())
        if isinstance(raw, (list, tuple)):
            return tuple(str(x) for x in raw)
    return ()


def propose_declarative_patches(
    findings: list[CritiqueFinding],
    asset_graph: AssetGraph,
) -> list[KnowledgePatch]:
    """Convert localized findings into validated declarative K/S patches."""
    patches: list[KnowledgePatch] = []
    for finding in findings:
        node = asset_graph.get(finding.target_asset_id)
        if node is None or node.type not in EVOLVABLE_ASSET_TYPES:
            continue
        field_name = _CATEGORY_TO_FIELD.get(finding.issue_category, "known_limitations")
        existing = {entry.strip().lower() for entry in _existing_field_values(node, field_name)}
        addition = finding.proposed_addition.strip()
        if not addition or addition.lower() in existing:
            continue
        digest = hashlib.sha256(
            f"{node.id}|{field_name}|{addition}".encode("utf-8")
        ).hexdigest()[:12]
        patch = KnowledgePatch(
            patch_id=f"patch_{digest}",
            target_asset_id=node.id,
            target_asset_type=node.type,
            field=field_name,
            operation="append_unique",
            values=(addition,),
            rationale=finding.rationale,
            evidence_ids=finding.evidence_ids,
            source_finding_id=finding.finding_id,
            created_at=_now(),
        )
        if not validate_declarative_patch(patch, asset_graph):
            patches.append(patch)
    return patches


def apply_patch_to_node(node: AssetNode, patch: KnowledgePatch) -> AssetNode:
    """Return a new AssetNode with the declarative patch applied (pure, monotonic)."""
    if patch.target_asset_id != node.id:
        raise ValueError(f"Patch target {patch.target_asset_id} does not match node {node.id}")
    if patch.field not in ALLOWED_PATCH_FIELDS or patch.operation != "append_unique":
        raise ValueError(f"Unsupported declarative patch: {patch.field} / {patch.operation}")

    new_version = _bump_patch_version(node.version)

    if patch.field in {"applicability_scope", "out_of_scope_cases", "known_limitations"}:
        current = list(getattr(node, patch.field))
        existing_lower = {item.strip().lower() for item in current}
        for val in patch.values:
            cleaned = val.strip()
            if cleaned and cleaned.lower() not in existing_lower:
                current.append(cleaned)
                existing_lower.add(cleaned.lower())
        return replace(node, version=new_version, **{patch.field: tuple(current)})

    key = patch.field.split(".", 1)[1]
    metadata = dict(node.metadata)
    current_meta = list(metadata.get(key, []))
    existing_lower = {str(item).strip().lower() for item in current_meta}
    for val in patch.values:
        cleaned = val.strip()
        if cleaned and cleaned.lower() not in existing_lower:
            current_meta.append(cleaned)
            existing_lower.add(cleaned.lower())
    metadata[key] = current_meta
    return replace(node, version=new_version, metadata=metadata)

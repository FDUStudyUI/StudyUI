"""Evidence-driven declarative knowledge evolution for StudyUI."""

from .acceptance import (
    EVOLUTION_APPROVAL_ACTION,
    EVOLUTION_MODES,
    AcceptanceReport,
    EvolutionController,
    check_boundary_integrity,
    evaluate_patch,
)
from .collector import EvidenceBundle, EvidenceItem, collect_evidence, infer_domain, is_transient_failure
from .critic import EVOLVABLE_ASSET_TYPES, CritiqueFinding, critique_evidence
from .editor import (
    ALLOWED_PATCH_FIELDS,
    KnowledgePatch,
    apply_patch_to_node,
    propose_declarative_patches,
    validate_declarative_patch,
)

__all__ = [
    "ALLOWED_PATCH_FIELDS",
    "AcceptanceReport",
    "CritiqueFinding",
    "EVOLUTION_APPROVAL_ACTION",
    "EVOLUTION_MODES",
    "EVOLVABLE_ASSET_TYPES",
    "EvidenceBundle",
    "EvidenceItem",
    "EvolutionController",
    "KnowledgePatch",
    "apply_patch_to_node",
    "check_boundary_integrity",
    "collect_evidence",
    "critique_evidence",
    "evaluate_patch",
    "infer_domain",
    "is_transient_failure",
    "propose_declarative_patches",
    "validate_declarative_patch",
]

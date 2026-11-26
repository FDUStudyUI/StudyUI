"""Layered scientific asset graph for StudyUI."""

from .catalog_bridge import build_default_asset_graph, cached_default_asset_graph
from .domain_knowledge import TASK_BOUNDARIES, extended_task_catalog, search_domain_method_cards
from .graph import AssetGraph
from .roles import ROLE_SPECS, ROLES_BY_KEY, RoleSpec
from .schema import ASSET_SCOPES, ASSET_TYPES, EDGE_TYPES, AssetEdge, AssetNode, ValidationIssue
from .scope_doc import render_scope_and_limitations_markdown

__all__ = [
    "ASSET_SCOPES",
    "ASSET_TYPES",
    "EDGE_TYPES",
    "ROLES_BY_KEY",
    "ROLE_SPECS",
    "TASK_BOUNDARIES",
    "AssetEdge",
    "AssetGraph",
    "AssetNode",
    "RoleSpec",
    "ValidationIssue",
    "build_default_asset_graph",
    "cached_default_asset_graph",
    "extended_task_catalog",
    "render_scope_and_limitations_markdown",
    "search_domain_method_cards",
]

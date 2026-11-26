"""MatOS integration layer: tool catalog, availability and CLI execution."""

from __future__ import annotations

from .catalog import (
    MatOSInputError,
    MatOSToolNotFound,
    all_tools,
    catalog_source,
    catalog_summary,
    describe_tool,
    list_tools,
    load_catalog,
    resolve_tool,
    validate_tool_input,
)
from .runner import (
    describe_matos_tool,
    find_matos_cli,
    install_hint,
    list_matos_tools,
    run_matos_tool,
    runtime_status,
    tool_availability,
)

__all__ = [
    "MatOSInputError",
    "MatOSToolNotFound",
    "all_tools",
    "catalog_source",
    "catalog_summary",
    "describe_matos_tool",
    "describe_tool",
    "find_matos_cli",
    "install_hint",
    "list_matos_tools",
    "list_tools",
    "load_catalog",
    "resolve_tool",
    "run_matos_tool",
    "runtime_status",
    "tool_availability",
    "validate_tool_input",
]

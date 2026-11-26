"""Static catalog of MatOS tool assets for StudyUI.

The catalog is generated from the MatOS benchmark-minimal distribution by
``scripts/build_matos_catalog.py``. It carries tool metadata and JSON input
schemas only; StudyUI never bundles or executes MatOS Python source. Runtime
availability and execution live in :mod:`materials_quality.matos.runner`.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalog_data.json")
EXPECTED_TOOL_COUNT = 18
EXPECTED_EXTERNAL_COUNT = 14
EXPECTED_BUILTIN_COUNT = 4


class MatOSToolNotFound(LookupError):
    """Raised when a MatOS tool identifier cannot be resolved."""


class MatOSInputError(ValueError):
    """Raised when a MatOS tool input does not match its JSON schema."""


def _normalize_key(value: str) -> str:
    text = value.strip().lower()
    for prefix in ("mcp__matos_asset__", "matos_tool__", "tool:", "matos:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    text = text.split("@", 1)[0]
    return text.replace("_", "-")


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Load and validate the generated catalog document (cached)."""
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    tools = payload.get("tools")
    if not isinstance(tools, list) or not tools:
        raise ValueError(f"MatOS catalog at {CATALOG_PATH} contains no tools")
    seen: set[str] = set()
    for tool in tools:
        tool_id = str(tool.get("id") or "")
        if not tool_id or tool_id in seen:
            raise ValueError(f"MatOS catalog contains a missing or duplicate tool id: {tool_id!r}")
        seen.add(tool_id)
        if tool.get("kind") not in {"external-tool", "builtin-pack"}:
            raise ValueError(f"MatOS tool {tool_id} has an unknown kind: {tool.get('kind')!r}")
    external_count = sum(1 for tool in tools if tool.get("kind") == "external-tool")
    builtin_count = sum(1 for tool in tools if tool.get("kind") == "builtin-pack")
    if len(tools) != EXPECTED_TOOL_COUNT:
        raise ValueError(f"MatOS catalog expected {EXPECTED_TOOL_COUNT} tools, found {len(tools)}")
    if external_count != EXPECTED_EXTERNAL_COUNT or builtin_count != EXPECTED_BUILTIN_COUNT:
        raise ValueError(
            "MatOS catalog expected "
            f"{EXPECTED_EXTERNAL_COUNT} external + {EXPECTED_BUILTIN_COUNT} builtin tools, "
            f"found {external_count} + {builtin_count}"
        )
    payload["tools"].sort(key=lambda item: str(item["id"]))
    return payload


@lru_cache(maxsize=1)
def _tool_index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for tool in load_catalog()["tools"]:
        for key in {
            str(tool["id"]).lower(),
            _normalize_key(str(tool["id"])),
            _normalize_key(str(tool.get("mcp_name") or "")),
            _normalize_key(str((tool.get("provenance") or {}).get("binding") or "")),
        }:
            if key and key not in index:
                index[key] = tool
    return index


def catalog_source() -> dict[str, Any]:
    return copy.deepcopy(load_catalog()["source"])


def catalog_summary() -> dict[str, Any]:
    return copy.deepcopy(load_catalog()["summary"])


def all_tools() -> list[dict[str, Any]]:
    return copy.deepcopy(load_catalog()["tools"])


def resolve_tool(tool: str) -> dict[str, Any]:
    """Resolve a tool id, ``tool:<id>`` ref, MCP binding, or underscore alias."""
    raw = str(tool or "").strip()
    if not raw:
        raise MatOSToolNotFound("MatOS tool id is required")
    record = _tool_index().get(raw.lower()) or _tool_index().get(_normalize_key(raw))
    if record is None:
        known = ", ".join(item["id"] for item in load_catalog()["tools"])
        raise MatOSToolNotFound(f"Unknown MatOS tool {raw!r}. Known tools: {known}")
    return copy.deepcopy(record)


def list_tools(
    *,
    family: str | None = None,
    kind: str | None = None,
    tool_id: str | None = None,
) -> list[dict[str, Any]]:
    """List catalog records, optionally filtered by family, kind or id/prefix."""
    wanted_family = str(family or "").strip().lower()
    wanted_kind = str(kind or "").strip().lower()
    wanted_id = str(tool_id or "").strip().lower()
    items: list[dict[str, Any]] = []
    for tool in load_catalog()["tools"]:
        if wanted_family and str(tool.get("family") or "").lower() != wanted_family:
            continue
        if wanted_kind and str(tool.get("kind") or "").lower() != wanted_kind:
            continue
        if wanted_id and wanted_id not in str(tool["id"]).lower():
            continue
        items.append(copy.deepcopy(tool))
    return items


def describe_tool(tool: str) -> dict[str, Any]:
    return resolve_tool(tool)


def validate_tool_input(tool: dict[str, Any], value: Any) -> dict[str, Any]:
    """Validate ``value`` against the MatOS tool's JSON input schema."""
    if not isinstance(value, dict):
        raise MatOSInputError("MatOS tool input must be a JSON object")
    schema = tool.get("input_schema") or {"type": "object"}
    if tool.get("kind") == "builtin-pack":
        # Builtin packs are documented as generic objects; there is no
        # external-input schema in MatOS for them.
        return value
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        details = []
        for error in errors[:10]:
            path = "/".join(str(part) for part in error.absolute_path) or "<root>"
            details.append(f"{path}: {error.message}")
        raise MatOSInputError("MatOS tool input does not match schema: " + "; ".join(details))
    return value

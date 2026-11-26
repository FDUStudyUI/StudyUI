"""Deterministic role subgraph router extracted from ``agent/harness.py``.

Keeps ``harness.py`` lean and preserves 100% backward compatibility when role
tool pruning is disabled (the default). When enabled, each turn is deterministically
mapped to one of the four declared StudyUI research roles, trimming the tool
surface and injecting the active role's applicability scope and limitations.
"""

from __future__ import annotations

import re
from typing import Any

from materials_quality.assets.catalog_bridge import cached_default_asset_graph
from materials_quality.assets.graph import AssetGraph
from materials_quality.assets.roles import ROLES_BY_KEY, SAFETY_ALWAYS_TOOLS

DEFAULT_ROLE = "workflow_planner"

_LITERATURE_RE = re.compile(
    r"(?:文献|论文|引用|doi|crossref|openalex|semantic\s*scholar|pubmed|综述|参考文献|查一下相关研究|literature|citation|paper)",
    re.IGNORECASE,
)
_QUALITY_RE = re.compile(
    r"(?:质控|质量检查|数据质量|缺失值|重复行|异常值|表头|分隔符|结构检查|单位核对|data\s*quality|audit|integrity|schema)",
    re.IGNORECASE,
)
_CHAR_RE = re.compile(
    r"(?:拉伸|应力|应变|模量|屈服|光谱|拉曼|\braman\b|\bftir\b|红外|\bxrd\b|衍射|晶面|电池|循环|库仑效率|容量保持|热分析|\btga\b|\bdsc\b|\btg\b|失重|玻璃化|tensile|spectra|battery|thermal)",
    re.IGNORECASE,
)
_WORKFLOW_ADMIN_RE = re.compile(
    r"(?:删除工作流|移除工作流|多分支|自定义工作流|运行\s*skill|执行技能脚本|delete\s+workflow|run\s+skill)",
    re.IGNORECASE,
)


def select_role(
    user_text: str,
    *,
    explicit_role: str | None = None,
    canvas_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministically select one of the four StudyUI research roles."""
    if explicit_role is not None:
        key = explicit_role.removeprefix("R:")
        if key not in ROLES_BY_KEY:
            raise ValueError(f"Unknown research role: {explicit_role}")
        spec = ROLES_BY_KEY[key]
        return {
            "role_key": spec.key,
            "role_id": spec.asset_id,
            "title": spec.title,
            "reason": "explicit_role_override",
            "allowed_tools": list(spec.allowed_tools),
        }

    if canvas_run:
        spec = ROLES_BY_KEY["workflow_planner"]
        return {
            "role_key": spec.key,
            "role_id": spec.asset_id,
            "title": spec.title,
            "reason": "canvas_run_requires_full_workflow_governance",
            "allowed_tools": list(spec.allowed_tools),
        }

    text = str(user_text or "").strip()
    if not text or _WORKFLOW_ADMIN_RE.search(text):
        spec = ROLES_BY_KEY[DEFAULT_ROLE]
        return {
            "role_key": spec.key,
            "role_id": spec.asset_id,
            "title": spec.title,
            "reason": "workflow_governance_or_default",
            "allowed_tools": list(spec.allowed_tools),
        }

    has_lit = bool(_LITERATURE_RE.search(text))
    has_quality = bool(_QUALITY_RE.search(text))
    has_char = bool(_CHAR_RE.search(text))

    # Multi-domain requests fall back to workflow_planner so no required tool is dropped.
    if has_lit and (has_char or has_quality):
        chosen, reason = DEFAULT_ROLE, "multi_domain_request"
    elif has_lit:
        chosen, reason = "literature_reviewer", "literature_intent_matched"
    elif has_char:
        chosen, reason = "characterization_analyst", "characterization_domain_matched"
    elif has_quality:
        chosen, reason = "data_quality_auditor", "data_quality_intent_matched"
    else:
        chosen, reason = DEFAULT_ROLE, "default_general_planning"

    spec = ROLES_BY_KEY[chosen]
    return {
        "role_key": spec.key,
        "role_id": spec.asset_id,
        "title": spec.title,
        "reason": reason,
        "allowed_tools": list(spec.allowed_tools),
    }


def route_tools(
    all_tools: list[dict[str, Any]],
    role_selection: dict[str, Any],
    *,
    enabled: bool = False,
) -> list[dict[str, Any]]:
    """Filter ``harness.TOOLS`` to the active role's allowlist when enabled."""
    if not enabled:
        return list(all_tools)
    allowed = set(role_selection.get("allowed_tools") or ()) | set(SAFETY_ALWAYS_TOOLS)
    return [
        tool
        for tool in all_tools
        if isinstance(tool, dict)
        and isinstance(tool.get("function"), dict)
        and tool["function"].get("name") in allowed
    ]


def build_role_context_note(
    role_selection: dict[str, Any],
    graph: AssetGraph | None = None,
) -> str:
    """Build a compact system prompt note describing the active role subgraph."""
    asset_graph = graph if graph is not None else cached_default_asset_graph()
    role_id = str(role_selection["role_id"])
    subgraph = asset_graph.subgraph_for_role(role_id)
    role_node = subgraph.get(role_id)
    if role_node is None:
        return ""
    summary = subgraph.summary()
    limitations = "；".join(role_node.known_limitations)
    out_of_scope = "；".join(role_node.out_of_scope_cases)
    return (
        f"【当前科研角色子图：{role_node.title} ({role_node.id})】\n"
        f"路由依据：{role_selection.get('reason', 'default')}；"
        f"已挂载组件 {summary['by_type']['T']} 个、方法卡 {summary['by_type']['K']} 张、"
        f"典型任务规范 {summary['by_type']['W']} 类、Skills {summary['by_type']['S']} 个。\n"
        f"角色边界限制：{limitations}" + (f"\n明确不支持：{out_of_scope}" if out_of_scope else "")
    )

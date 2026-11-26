"""Bridge existing StudyUI registries into a unified ``AssetGraph``."""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

from materials_quality.material_examples import examples as load_instrument_examples
from materials_quality.science.catalog import entries as load_catalog_entries
from materials_quality.science.method_cards import load_cards as load_literature_cards
from materials_quality.skills.registry import SKILL_CATALOG, load_skill

from .domain_knowledge import extended_task_catalog
from .graph import AssetGraph
from .roles import ROLE_SPECS
from .schema import AssetEdge, AssetNode

_SKILL_DOMAINS: dict[str, str] = {
    "workflow": "workflow",
    "harness": "general",
    "literature": "literature",
    "data_quality": "quality",
    "spectra": "spectra",
    "mechanics": "mechanics",
    "contrast": "general",
    "xrd": "xrd",
    "battery": "battery",
    "thermal": "thermal",
    "compression": "mechanics",
    "plasmonic": "spectra",
    "experimental_design": "quality",
    "uncertainty": "quality",
}

_OPERATION_DOMAIN_HINTS: dict[str, str] = {
    "materials.mechanics": "mechanics",
    "materials.spectra": "spectra",
    "materials.xrd": "xrd",
    "materials.xrd_cif_screening": "xrd",
    "materials.battery_cycles": "battery",
    "materials.pybamm_battery_sim": "battery",
    "materials.thermal": "thermal",
    "materials.batch_spectra": "spectra",
    "materials.chemometrics": "spectra",
}


_CATEGORY_ALIASES: dict[str, str] = {
    "数据接入": "io",
    "io": "io",
    "内容提取": "extraction",
    "extraction": "extraction",
    "preprocessing": "preprocessing",
    "材料专业分析": "materials",
    "materials": "materials",
    "统计与建模": "statistics",
    "statistics": "statistics",
    "可视化与报告": "visualization",
    "visualization": "visualization",
    "literature": "literature",
    "文献与证据": "literature",
    "quality": "quality",
    "agent": "agent",
    "export": "export",
}

_NATIVE_DIR_CATEGORIES: dict[str, str] = {
    "materials_quality": "quality",
    "materials_batch": "materials",
    "materials_skills": "agent",
    "materials_sources": "io",
    "materials_extraction": "extraction",
    "materials_preprocessing": "preprocessing",
    "materials_analysis": "materials",
    "materials_statistics": "statistics",
    "materials_visualization": "visualization",
    "materials_literature": "literature",
}

_NATIVE_OVERRIDES: dict[str, dict[str, str]] = {
    "BatteryCycles": {
        "asset_id": "T:materials.battery_cycles",
        "category": "materials",
        "domain": "battery",
        "entrypoint": "materials_quality.science.battery:analyze_battery_cycles",
    },
    "PymatgenXrdScreening": {
        "asset_id": "T:materials.xrd_cif_screening",
        "category": "materials",
        "domain": "xrd",
        "entrypoint": "materials_quality.science.plugins.pymatgen_xrd:compute_theoretical_xrd_from_cif",
    },
    "PybammBatterySim": {
        "asset_id": "T:materials.pybamm_battery_sim",
        "category": "materials",
        "domain": "battery",
        "entrypoint": "materials_quality.science.plugins.pybamm_battery:simulate_single_cell_discharge",
    },
    "BatchSpectrumAnalyzer": {
        "category": "materials",
        "domain": "spectra",
    },
    "MaterialBatchQuality": {
        "category": "quality",
        "domain": "quality",
    },
    "ContrastStudy": {
        "category": "statistics",
        "domain": "general",
        "entrypoint": "materials_quality.science.contrast_study",
    },
    "MaterialModelComparison": {
        "category": "statistics",
        "domain": "general",
    },
}


def _canonical_category(raw_category: str, key: str = "") -> str:
    if key.startswith("export."):
        return "export"
    normalized = _CATEGORY_ALIASES.get(str(raw_category or "").strip())
    if normalized:
        return normalized
    prefix = key.split(".", 1)[0] if "." in key else ""
    return {
        "io": "io",
        "extract": "extraction",
        "preprocess": "preprocessing",
        "materials": "materials",
        "stats": "statistics",
        "viz": "visualization",
        "lit": "literature",
    }.get(prefix, str(raw_category or "general"))


def _components_root() -> Path | None:
    here = Path(__file__).resolve()
    for candidate in (here.parents[3] / "components", here.parents[1] / "component_sources"):
        if candidate.is_dir():
            return candidate
    return None


def _iter_native_component_specs() -> list[dict[str, str]]:
    root = _components_root()
    if root is None:
        return []
    specs: list[dict[str, str]] = []
    for path in sorted(root.glob("*/*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for stmt in tree.body:
            if not isinstance(stmt, ast.ClassDef):
                continue
            attrs: dict[str, str] = {}
            for item in stmt.body:
                if (
                    isinstance(item, ast.Assign)
                    and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                    and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)
                ):
                    attrs[item.targets[0].id] = item.value.value
            class_name = attrs.get("name") or stmt.name
            specs.append(
                {
                    "class_name": class_name,
                    "title": attrs.get("display_name") or class_name,
                    "description": attrs.get("description") or "",
                    "directory": path.parent.name,
                    "filename": path.name,
                }
            )
    return specs


def _tool_domain(entry: dict) -> str:
    key = str(entry.get("key", ""))
    if key in _OPERATION_DOMAIN_HINTS:
        return _OPERATION_DOMAIN_HINTS[key]
    category = _canonical_category(str(entry.get("category", "general")), key)
    if category in {"quality", "literature"}:
        return category
    return "general"


def build_default_asset_graph() -> AssetGraph:
    """Assemble the bundled StudyUI scientific asset graph from live registries."""
    graph = AssetGraph()

    # 1. Tool assets (T): all registered science catalog components + native Langflow components.
    tool_by_class: dict[str, str] = {}
    for entry in load_catalog_entries():
        key = str(entry["key"])
        asset_id = f"T:{key}"
        class_name = str(entry.get("class_name", ""))
        raw_category = str(entry.get("category", "general"))
        canonical_category = _canonical_category(raw_category, key)
        if class_name:
            tool_by_class[class_name] = asset_id
        graph.add_asset(
            AssetNode(
                id=asset_id,
                type="T",
                title=str(entry.get("title") or key),
                version="1.0.0",
                scope="bundled",
                domain=_tool_domain(entry),
                entrypoint=str(entry.get("function", "")),
                description=str(entry.get("requirement", "")),
                metadata={
                    "category": canonical_category,
                    "raw_category": raw_category,
                    "class_name": class_name,
                    "directory": str(entry.get("directory", "")),
                },
            )
        )

    for comp in _iter_native_component_specs():
        class_name = comp["class_name"]
        if class_name in tool_by_class:
            continue
        override = _NATIVE_OVERRIDES.get(class_name, {})
        asset_id = override.get("asset_id", f"T:{class_name}")
        directory = comp["directory"]
        category = override.get("category") or _NATIVE_DIR_CATEGORIES.get(directory, "general")
        domain = override.get("domain") or ("quality" if category == "quality" else "general")
        entrypoint = override.get("entrypoint") or f"components/{directory}/{comp['filename']}:{class_name}"
        tool_by_class[class_name] = asset_id
        graph.add_asset(
            AssetNode(
                id=asset_id,
                type="T",
                title=comp["title"],
                version="1.0.0",
                scope="bundled",
                domain=domain,
                entrypoint=entrypoint,
                description=comp["description"],
                metadata={
                    "category": category,
                    "raw_category": directory,
                    "class_name": class_name,
                    "directory": directory,
                    "native_component": True,
                },
            )
        )

    # 2. Literature method cards (K:card.*) + VERIFY edges to tools.
    for card in load_literature_cards():
        card_id = f"K:card.{card['id']}"
        source_title = str(card.get("source_title") or card.get("source_kind") or "Literature method card")
        source_url = str(card.get("source_url") or "")
        refs = ({"title": source_title, "url": source_url},) if source_url else ({"title": source_title},)
        scope_items = tuple(
            f"{k}={v}" for k, v in (card.get("requires") or {}).items()
        ) or ("需满足方法卡声明的信号与数据前提。",)
        limitations = tuple(card.get("warnings") or ()) or (
            "eligible 仅表示声明条件匹配，不代表实验或材料物理机制已验证。",
        )
        graph.add_asset(
            AssetNode(
                id=card_id,
                type="K",
                title=str(card.get("name") or card["id"]),
                version="1.0.0",
                scope="bundled",
                domain="literature",
                entrypoint="materials_quality.science.method_cards:recommend_methods",
                description=str(card.get("summary") or card.get("goal") or ""),
                applicability_scope=scope_items,
                out_of_scope_cases=("未声明或与方法卡前提冲突的信号类型不可直接应用。",),
                standards_refs=refs,
                known_limitations=limitations,
                metadata={"operation": str(card.get("operation", "")), "goal": str(card.get("goal", ""))},
            )
        )
        op = str(card.get("operation") or "")
        if op and f"T:{op}" in graph:
            graph.add_edge(
                AssetEdge(
                    source=card_id,
                    target=f"T:{op}",
                    kind="VERIFY",
                    rationale="Method card defines applicability preconditions for this operation.",
                )
            )

    # 3. 5 typical materials tasks (W:protocol.*) and 30 task method cards (K:task.*).
    for task in extended_task_catalog():
        task_id = str(task["id"])
        wf_id = f"W:protocol.{task_id}"
        refs = tuple(
            {
                "title": str(card["source"]["title"]),
                "url": str(card["source"].get("url", "")),
            }
            for card in task["cards"]
            if isinstance(card.get("source"), dict) and card["source"].get("title")
        )
        # Deduplicate standards refs while preserving order.
        unique_refs: list[dict[str, str]] = []
        seen_titles: set[str] = set()
        for ref in refs:
            if ref["title"] not in seen_titles:
                seen_titles.add(ref["title"])
                unique_refs.append(ref)

        graph.add_asset(
            AssetNode(
                id=wf_id,
                type="W",
                title=str(task["title"]),
                version=str(task["version"]),
                scope="bundled",
                domain=task_id,
                entrypoint=(
                    "materials_quality.agent.material_protocols:compile_material_protocol"
                    if task.get("protocol_compiler_ready")
                    else f"materials_quality.science:{task['operation']}"
                ),
                description=f"{task['title']}典型材料科研工作流与方法检查规范。",
                applicability_scope=tuple(task["applicability_scope"]),
                out_of_scope_cases=tuple(task["out_of_scope_cases"]),
                standards_refs=tuple(unique_refs),
                known_limitations=tuple(task["known_limitations"]),
                metadata={
                    "operation": str(task["operation"]),
                    "protocol_compiler_ready": bool(task.get("protocol_compiler_ready")),
                    "card_count": len(task["cards"]),
                },
            )
        )
        primary_op_id = f"T:{task['operation']}"
        if primary_op_id in graph:
            graph.add_edge(
                AssetEdge(
                    source=wf_id,
                    target=primary_op_id,
                    kind="CALL",
                    rationale="Primary deterministic calculation node for this typical task.",
                )
            )

        for card in task["cards"]:
            card_id = f"K:task.{card['id']}"
            source = card.get("source") or {}
            graph.add_asset(
                AssetNode(
                    id=card_id,
                    type="K",
                    title=str(card["title"]),
                    version=str(card.get("version", task["version"])),
                    scope="bundled",
                    domain=task_id,
                    entrypoint="materials_quality.assets.domain_knowledge:extended_task_catalog",
                    description=str(card["objective"]),
                    applicability_scope=(str(card["objective"]),),
                    out_of_scope_cases=(str(card["conditions"]),),
                    standards_refs=(
                        ({"title": str(source["title"]), "url": str(source.get("url", ""))}),
                    )
                    if source.get("title")
                    else (),
                    known_limitations=(str(card["conditions"]),),
                    metadata={"task": task_id, "operation": str(card["operation"])},
                )
            )
            graph.add_edge(
                AssetEdge(
                    source=wf_id,
                    target=card_id,
                    kind="PART",
                    rationale="Task knowledge card belongs to this typical materials workflow.",
                )
            )
            op_name = str(card["operation"])
            target_tool = f"T:{op_name}" if f"T:{op_name}" in graph else tool_by_class.get(op_name)
            if target_tool and target_tool in graph:
                graph.add_edge(
                    AssetEdge(
                        source=card_id,
                        target=target_tool,
                        kind="VERIFY",
                        rationale="Knowledge card encodes physical/method checks for this tool.",
                    )
                )

    # 4. Built-in research skills (S:*).
    for skill_key, (skill_name, title) in SKILL_CATALOG.items():
        skill_data = load_skill(skill_key)
        skill_id = f"S:{skill_name}"
        domain = _SKILL_DOMAINS.get(skill_key, "general")
        graph.add_asset(
            AssetNode(
                id=skill_id,
                type="S",
                title=title,
                version=str(skill_data.get("version", "1.0.0")),
                scope="bundled",
                domain=domain,
                entrypoint=f"materials_quality/skills/resources/{skill_name}/SKILL.md",
                description=str(skill_data.get("description", title)),
                applicability_scope=(f"适用于 {title} 相关的材料科研流程与规则指导。",),
                out_of_scope_cases=("Skill 文本属于只读指导材料，不可覆盖系统权限策略或直接执行未审核代码。",),
                known_limitations=("Skill 指令不替代确定性节点计算或人工实验验证。",),
                metadata={
                    "task_key": skill_key,
                    "sha256": str(skill_data.get("sha256", "")),
                    "always": bool(skill_data.get("always", False)),
                    "triggers": list(skill_data.get("triggers", [])),
                },
            )
        )

    # 4b. Link optional compute solver tools to their domain skills, workflows, and knowledge cards.
    plugin_graph_links = (
        (
            "T:materials.xrd_cif_screening",
            "S:studyui-powder-xrd",
            "W:protocol.xrd",
            ("K:task.xrd.scan", "K:task.xrd.references"),
            "Optional pymatgen CIF theoretical XRD candidate-screening tool.",
        ),
        (
            "T:materials.pybamm_battery_sim",
            "S:studyui-battery-cycling",
            "W:protocol.battery",
            ("K:task.battery.units", "K:task.battery.conditions"),
            "Optional PyBaMM single-cell electrochemical discharge simulation tool.",
        ),
    )
    for tool_id, skill_id, wf_id, card_ids, rationale in plugin_graph_links:
        if tool_id not in graph:
            continue
        if skill_id in graph:
            graph.add_edge(AssetEdge(source=skill_id, target=tool_id, kind="MOUNT", rationale=rationale))
        if wf_id in graph:
            graph.add_edge(AssetEdge(source=wf_id, target=tool_id, kind="CALL", rationale=rationale))
        for card_id in card_ids:
            if card_id in graph:
                graph.add_edge(AssetEdge(source=card_id, target=tool_id, kind="VERIFY", rationale=rationale))

    # 5. Real instrument example datasets (D:example.*) + EVIDENCE edges to workflows.
    for item in load_instrument_examples():
        example_id = f"D:example.{item['id']}"
        task_name = str(item.get("task", "general"))
        source = item.get("source") or {}
        refs = (
            ({"title": str(source.get("title") or source.get("doi") or item["id"]), "url": str(source.get("url", ""))},)
            if source
            else ()
        )
        graph.add_asset(
            AssetNode(
                id=example_id,
                type="D",
                title=str(item.get("title") or item["id"]),
                version="1.0.0",
                scope="bundled",
                domain=task_name,
                entrypoint=f"materials_quality/material_examples/data/{item['filename']}",
                description=str(item.get("scope") or ""),
                applicability_scope=(str(item.get("scope") or "公开真实仪器验证数据。"),),
                standards_refs=refs,
                known_limitations=("单份公开仪器样例仅用于对应表征协议的复现与验证，不代表任意仪器型号全覆盖。",),
                metadata={
                    "task": task_name,
                    "filename": str(item.get("filename", "")),
                    "sha256": str(item.get("sha256", "")),
                    "doi": str(source.get("doi", "")),
                },
            )
        )
        wf_target = f"W:protocol.{task_name}"
        if wf_target in graph:
            graph.add_edge(
                AssetEdge(
                    source=example_id,
                    target=wf_target,
                    kind="EVIDENCE",
                    rationale="Attributed real-instrument dataset validating this protocol.",
                )
            )

    # 6. Declarative research roles (R:*) + MOUNT edges.
    for role in ROLE_SPECS:
        graph.add_asset(
            AssetNode(
                id=role.asset_id,
                type="R",
                title=role.title,
                version="1.0.0",
                scope="bundled",
                domain="general",
                entrypoint="materials_quality.agent.role_router:select_role",
                description=role.description,
                applicability_scope=role.applicability_scope,
                out_of_scope_cases=role.out_of_scope_cases,
                known_limitations=role.known_limitations,
                metadata={
                    "role_key": role.key,
                    "allowed_tools": list(role.allowed_tools),
                    "mounted_categories": list(role.mounted_categories),
                    "mounted_domains": list(role.mounted_domains),
                },
            )
        )
        for skill_name in role.mounted_skills:
            target = f"S:{skill_name}"
            if target in graph:
                graph.add_edge(AssetEdge(source=role.asset_id, target=target, kind="MOUNT"))
        for wf_id in role.mounted_workflows:
            if wf_id in graph:
                graph.add_edge(AssetEdge(source=role.asset_id, target=wf_id, kind="MOUNT"))
        for node in graph.nodes():
            if node.type == "T" and node.metadata.get("category") in role.mounted_categories:
                graph.add_edge(AssetEdge(source=role.asset_id, target=node.id, kind="MOUNT"))
            elif node.type == "K" and node.domain in role.mounted_domains:
                graph.add_edge(AssetEdge(source=role.asset_id, target=node.id, kind="MOUNT"))

    return graph


@lru_cache(maxsize=1)
def cached_default_asset_graph() -> AssetGraph:
    """Return a cached read-only-intended instance of the bundled asset graph."""
    return build_default_asset_graph()

"""Generate ``docs/scope-and-limitations.md`` directly from the AssetGraph."""

from __future__ import annotations

from .catalog_bridge import build_default_asset_graph
from .graph import AssetGraph


def render_scope_and_limitations_markdown(graph: AssetGraph | None = None) -> str:
    """Render a deterministic Markdown specification of StudyUI scope and limitations."""
    asset_graph = graph if graph is not None else build_default_asset_graph()
    summary = asset_graph.summary()
    workflows = sorted(asset_graph.by_type("W"), key=lambda item: item.id)
    roles = sorted(asset_graph.by_type("R"), key=lambda item: item.id)
    examples = sorted(asset_graph.by_type("D"), key=lambda item: item.id)

    lines: list[str] = [
        "# StudyUI 适用范围、材料典型任务与技术限制说明",
        "",
        "> 本文档由 `materials_quality.assets.scope_doc.render_scope_and_limitations_markdown()` "
        "直接从科学资产图谱生成，确保文档边界与代码登记资产保持一致。",
        "",
        "## 一、当前纳管资产概览",
        "",
        f"- **已登记科学计算组件（T）**：{summary['by_type']['T']} 个",
        f"- **材料方法与文献知识卡（K）**：{summary['by_type']['K']} 张",
        f"- **典型材料任务工作流规范（W）**：{summary['by_type']['W']} 类",
        f"- **内置科研技能包（S）**：{summary['by_type']['S']} 个",
        f"- **带来源与哈希的真实仪器案例（D）**：{summary['by_type']['D']} 份",
        f"- **声明式研究角色（R）**：{summary['by_type']['R']} 个",
        f"- **资产图谱关系边**：{summary['total_edges']} 条（校验错误数：{summary['error_count']}）",
        "",
        "## 二、五大典型材料任务的适用范围与明确不支持场景",
        "",
    ]

    for wf in workflows:
        compiler_state = (
            "已支持一键协议编译（表单/对话直出原生节点）"
            if wf.metadata.get("protocol_compiler_ready")
            else "已纳入资产图谱与方法卡规范（使用原生节点组合或自定义建流）"
        )
        lines.append(f"### {wf.title}（`{wf.id}`）")
        lines.append("")
        lines.append(f"- **状态**：{compiler_state}；主算子：`{wf.metadata.get('operation', '')}`")
        lines.append("- **适用范围**：")
        for item in wf.applicability_scope:
            lines.append(f"  - {item}")
        lines.append("- **明确不支持 / 需换方法场景**：")
        for item in wf.out_of_scope_cases:
            lines.append(f"  - {item}")
        lines.append("- **已知技术限制**：")
        for item in wf.known_limitations:
            lines.append(f"  - {item}")
        if wf.standards_refs:
            refs_text = "；".join(
                f"[{ref['title']}]({ref['url']})" if ref.get("url") else ref["title"]
                for ref in wf.standards_refs
            )
            lines.append(f"- **标准与方法依据**：{refs_text}")
        lines.append("")

    lines.extend(
        [
            "## 三、研究角色能力边界（Role Subgraphs）",
            "",
            "| 角色 ID | 角色名称 | 可挂载工具数 | 适用范围 | 核心限制 |",
            "|---|---|---:|---|---|",
        ]
    )
    for role in roles:
        tool_count = len(role.metadata.get("allowed_tools", []))
        scope_text = " ".join(role.applicability_scope)
        limit_text = " ".join(role.known_limitations)
        lines.append(f"| `{role.id}` | {role.title} | {tool_count} | {scope_text} | {limit_text} |")

    lines.extend(
        [
            "",
            "## 四、系统级技术限制与评测边界声明",
            "",
            "1. **确定性计算与模型推理分离**：数值计算由本地已登记科学节点执行"
            "；大语言模型仅负责任务理解、参数澄清、建流编排与报告综合，不替代精确数值"
            "求解。",
            (
                "2. **当前不覆盖的领域计算**：系统目前聚焦材料实验表征数据质控与定量分析，不包含第一"
                "性原理计算（DFT/VASP/QE）、分子动力学集群调度（LAMMPS）或全谱 Rietv"
                "eld 结构精修。"
            ),
            "3. **评测三维度解耦原则**：",
            "   - **工作流构建成功率**：衡量智能体在真实仪器数据上构建合法可执行流程的比例。",
            "   - **计算结果可重复性（独立维度）**：衡量固定工作流在冷启动多"
            "进程与复现包重跑下结果表哈希与数值的一致性。",
            "   - **所选方法正确性（独立维度）**：衡量方法选型、物理前提契约"
            "、越界拦截以及材料专家评审质量；运行成功或结果可重复**不等于**方法选"
            "择正确。",
            f"4. **当前已内置真实仪器验证数据**：共 {len(examples)}"
            f" 份公开仪器文件（带 DOI 与 SHA-256 校验），覆盖金属拉伸、"
            f"矿物 XRD 与聚合物 Raman，后续按计划扩充锂电池循环与热分析真实"
            f"数据集及越界反例集。",
            "",
        ]
    )
    return "\n".join(lines)

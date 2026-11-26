"""Declarative research role definitions mounted on the scientific asset graph."""

from __future__ import annotations

from dataclasses import dataclass

SAFETY_ALWAYS_TOOLS = (
    "list_pending_approvals",
    "cancel_approval",
)


@dataclass(frozen=True)
class RoleSpec:
    """Declarative specification for a StudyUI research role asset."""

    key: str
    title: str
    description: str
    allowed_tools: tuple[str, ...]
    mounted_categories: tuple[str, ...]
    mounted_domains: tuple[str, ...]
    mounted_skills: tuple[str, ...]
    mounted_workflows: tuple[str, ...]
    applicability_scope: tuple[str, ...]
    out_of_scope_cases: tuple[str, ...]
    known_limitations: tuple[str, ...]

    @property
    def asset_id(self) -> str:
        return f"R:{self.key}"


ROLE_SPECS: tuple[RoleSpec, ...] = (
    RoleSpec(
        key="characterization_analyst",
        title="材料表征分析角色",
        description="负责力学、光谱、XRD、电池循环与热分析等典型材料表征任务的协议建流、确定性计算、图表与报告交付。",
        allowed_tools=(
            "inspect_research_file",
            "list_project_files",
            "recommend_analysis_methods",
            "list_research_skills",
            "use_research_skill",
            "list_workflows",
            "inspect_workflow",
            "list_components",
            "build_material_workflow",
            "build_workflow",
            "propose_workflow_changes",
            "run_workflow",
            "run_materials_solver",
            "write_research_report",
            *SAFETY_ALWAYS_TOOLS,
        ),
        mounted_categories=("io", "preprocessing", "materials", "statistics", "visualization", "export"),
        mounted_domains=("mechanics", "spectra", "xrd", "battery", "thermal"),
        mounted_skills=(
            "studyui-harness-operations",
            "studyui-raw-data-integrity",
            "studyui-mechanics-analysis",
            "studyui-spectrum-analysis",
            "studyui-powder-xrd",
            "studyui-battery-cycling",
            "studyui-thermal-analysis",
            "studyui-statistics-and-figures",
            "studyui-units-and-uncertainty",
        ),
        mounted_workflows=(
            "W:protocol.mechanics",
            "W:protocol.spectra",
            "W:protocol.xrd",
            "W:protocol.battery",
            "W:protocol.thermal",
        ),
        applicability_scope=(
            "力学拉伸、拉曼/红外/荧光光谱、粉末 XRD、锂电池循环与 TG/DSC 热分析等单曲线或分组表征任务。",
        ),
        out_of_scope_cases=(
            "不执行任意非登记 Shell/Python 脚本，不替代第一性原理计算（DFT）或全谱 Rietveld 结构精修。",
        ),
        known_limitations=(
            "默认不包含工作流删除工具与外部学术检索工具；需要文献核验时应切换至文献证据角色或规划角色。",
        ),
    ),
    RoleSpec(
        key="data_quality_auditor",
        title="原始数据与质控审计角色",
        description="负责原始仪器文件结构探查、缺失/重复/单位/异常值质控审计与非破坏性数据清洗验证。",
        allowed_tools=(
            "list_project_files",
            "inspect_research_file",
            "list_research_skills",
            "use_research_skill",
            "list_workflows",
            "inspect_workflow",
            "list_components",
            "build_workflow",
            "propose_workflow_changes",
            "run_workflow",
            "run_materials_solver",
            "write_research_report",
            *SAFETY_ALWAYS_TOOLS,
        ),
        mounted_categories=("io", "quality", "preprocessing", "statistics", "export"),
        mounted_domains=("quality", "general"),
        mounted_skills=(
            "studyui-harness-operations",
            "studyui-raw-data-integrity",
            "studyui-units-and-uncertainty",
            "studyui-experimental-design",
        ),
        mounted_workflows=(),
        applicability_scope=(
            "原始表格、Excel 多工作表、数值 XY 与 HDF5/NetCDF/Zarr 仪器数据的结构审查、单位契约与异常检测。",
        ),
        out_of_scope_cases=("不负责材料物相鉴定、力学本构建模或学术文献综述；不得修改原始测量源文件。",),
        known_limitations=(
            "仅对已授权项目目录或当前会话上传文件执行只读检查，无法访问未授权路径或外部网络数据。",
        ),
    ),
    RoleSpec(
        key="literature_reviewer",
        title="学术文献与方法证据角色",
        description="负责白名单学术数据库检索、DOI/元数据核验、文献方法卡适用条件比对与证据化综述。",
        allowed_tools=(
            "search_literature",
            "recommend_analysis_methods",
            "list_research_skills",
            "use_research_skill",
            "list_workflows",
            "inspect_workflow",
            "write_research_report",
            *SAFETY_ALWAYS_TOOLS,
        ),
        mounted_categories=("literature",),
        mounted_domains=("literature",),
        mounted_skills=(
            "studyui-harness-operations",
            "studyui-raw-data-integrity",
            "studyui-literature-evidence",
            "studyui-experimental-design",
        ),
        mounted_workflows=(),
        applicability_scope=(
            "CrossRef、OpenAlex、Semantic Scholar、E"
            "urope PMC、DataCite 白名单学术元数据检索与方法卡前提核"
            "对。",
        ),
        out_of_scope_cases=(
            "不执行通用网页爬取，不可在仅获得元数据摘要时宣称已阅读论文全文或编造公认物理区间。",
        ),
        known_limitations=("该角色为只读证据角色，不具备创建、修改、运行或删除工作流的权限。",),
    ),
    RoleSpec(
        key="workflow_planner",
        title="科研工作流编排与治理角色",
        description="负责跨领域复杂多分支工作流搭建、参数修复、权限审批协同、沙箱 Skill 调用与全流程治理。",
        allowed_tools=(
            "recommend_analysis_methods",
            "write_research_report",
            "inspect_research_file",
            "list_project_files",
            "search_literature",
            "list_research_skills",
            "use_research_skill",
            "run_skill_script",
            "list_workflows",
            "inspect_workflow",
            "list_components",
            "propose_workflow_changes",
            "build_workflow",
            "build_material_workflow",
            "run_workflow",
            "run_materials_solver",
            "delete_workflow",
            *SAFETY_ALWAYS_TOOLS,
        ),
        mounted_categories=(
            "io",
            "extraction",
            "quality",
            "preprocessing",
            "materials",
            "statistics",
            "chemometrics",
            "visualization",
            "literature",
            "export",
            "agent",
        ),
        mounted_domains=(
            "mechanics",
            "spectra",
            "xrd",
            "battery",
            "thermal",
            "quality",
            "literature",
            "general",
        ),
        mounted_skills=(
            "studyui-research-workflow",
            "studyui-harness-operations",
            "studyui-raw-data-integrity",
            "studyui-literature-evidence",
            "studyui-mechanics-analysis",
            "studyui-spectrum-analysis",
            "studyui-powder-xrd",
            "studyui-battery-cycling",
            "studyui-thermal-analysis",
            "studyui-statistics-and-figures",
            "studyui-units-and-uncertainty",
            "studyui-experimental-design",
            "studyui-compressive-strength",
            "studyui-dna-origami-plasmonics",
        ),
        mounted_workflows=(
            "W:protocol.mechanics",
            "W:protocol.spectra",
            "W:protocol.xrd",
            "W:protocol.battery",
            "W:protocol.thermal",
        ),
        applicability_scope=(
            "跨表征方法、多分支工作流编排、工作流修复与删除管理，以及需要同时调用文献与计算的复合科研任务。",
        ),
        out_of_scope_cases=(
            "高风险动作（删除工作流、跨项目访问、AI 节点数据外传、沙箱脚本执行）仍受一次性审批严格约束。",
        ),
        known_limitations=(
            "工具集最全，适合复杂或跨领域任务；单一领域常规分析优先交由专职角色以降低工具误选率。",
        ),
    ),
)

ROLES_BY_KEY: dict[str, RoleSpec] = {spec.key: spec for spec in ROLE_SPECS}

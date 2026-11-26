"""Canvas presentation policy: keep node forms compact.

The canvas node renderer shows every non-advanced input. Several StudyUI
components (the research planner, visualization/statistics operations and the
batch analyzer) expose 20-50 optional parameters, which makes a single node
several screens tall. This policy keeps the data/table inputs, output paths,
mode selectors and column selectors visible, and folds every other optional
input into the node's Advanced section. It is presentation-only: the installed
component code, the saved flow values and execution are unchanged.
"""

from __future__ import annotations

BASE_VISIBLE = frozenset(
    {
        "input_table",
        "input_data",
        "input_tables",
        "reports",
        "source_file",
        "plan",
        "bundle_base64",
        "ui_mode",
        "config_json",
        "task",
        "request",
        "output_directory",
        "cfg_output_dir",
        "cfg_filename",
        "cfg_path",
    }
)

# Fields that select data semantics stay visible; styling, thresholds and
# export tuning move under Advanced.
COLUMN_TOKENS = (
    "column",
    "columns",
    "group",
    "curve",
    "value_vars",
    "id_vars",
    "cfg_on",
    "cfg_by",
    "index",
)

PLANNER_TYPE = "ResearchSkillPlanner"
PLANNER_CORES = {
    "spectra": {"curve_column", "x_column", "y_column", "group_column"},
    "mechanics": {"x_column", "y_column", "group_column", "sample_column"},
    "contrast": {"group_column", "sample_column", "variable_column", "value_column"},
}
PLANNER_FIXED = {"input_table", "task", "request"}


def keep_visible(name: str) -> bool:
    if name in BASE_VISIBLE:
        return True
    lowered = name.lower()
    return any(token in lowered for token in COLUMN_TOKENS)


def compact_template(template, type_name: str | None = None) -> dict:
    """Mark optional inputs advanced; never hide the code editor or inputs."""
    if not isinstance(template, dict):
        return template
    if type_name == PLANNER_TYPE:
        task = str((template.get("task") or {}).get("value") or "")
        core = PLANNER_FIXED | PLANNER_CORES.get(task, set())
        for name, field in template.items():
            if name == "code" or not isinstance(field, dict):
                continue
            field["advanced"] = name not in core
        return template
    for name, field in template.items():
        if name == "code" or not isinstance(field, dict):
            continue
        if keep_visible(name):
            # Preserve a task-specific advanced decision made by the component.
            field.setdefault("advanced", False)
        else:
            field["advanced"] = True
    return template


def compact_flow_templates(flow) -> dict:
    """Apply compact_template to every canvas node in a flow."""
    if not isinstance(flow, dict):
        return flow
    data = flow.get("data")
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        return flow
    for node in nodes:
        if not isinstance(node, dict):
            continue
        outer = node.get("data") if isinstance(node.get("data"), dict) else {}
        inner = outer.get("node") if isinstance(outer, dict) else None
        if isinstance(inner, dict) and isinstance(inner.get("template"), dict):
            compact_template(inner["template"], type_name=outer.get("type") or inner.get("type"))
    return flow


def compact_component_catalog(catalog) -> dict:
    """Apply compact_template to every component template in the canvas catalog."""
    if not isinstance(catalog, dict):
        return catalog
    for group in catalog.values():
        if not isinstance(group, dict):
            continue
        for component_name, component in group.items():
            if isinstance(component, dict) and isinstance(component.get("template"), dict):
                compact_template(component["template"], type_name=str(component_name))
    return catalog

"""Plan preview and scientific metadata confirmation through native forms."""

from lfx.custom import Component
from lfx.io import Output
from lfx.schema import Data, Message

from materials_quality.batch.native import prepare_form
from materials_quality.skills.native import (
    COLUMNS,
    THRESHOLD_MODES,
    UNIT_MODES,
    VISIBLE,
    parameters_from,
    planner_inputs,
)
from materials_quality.skills.planning import _route, input_identity, make_plan
from materials_quality.skills.registry import digest, list_skills, load_skill


class ResearchSkillPlanner(Component):
    display_name = "科研技能·任务规划"
    description = "选择光谱、力学或组间研究；原生表单确认参数，先预览步骤与待补事项，再连接执行。"
    name = "ResearchSkillPlanner"
    icon = "ClipboardList"
    inputs = planner_inputs()
    outputs = [
        Output(
            name="plan", display_name="经校验的分析计划", method="build_plan", group_outputs=True, cache=False
        ),
        Output(
            name="preview",
            display_name="步骤与待补事项",
            method="build_preview",
            group_outputs=True,
            cache=False,
        ),
    ]

    def _plan(self):
        task = _route(self.request) if self.task == "auto" else self.task
        p = parameters_from(self, task)
        signature = digest(
            [input_identity(self.input_table), self.task, self.request, p, self.use_model, list_skills()]
        )
        cached = self._ctx.get("research_plan")
        if cached is None or cached[0] != signature:
            if self.use_model:
                from materials_quality.skills.model import suggest_plan

                plan = suggest_plan(self.input_table, self.request, task=self.task, parameters=p)
            else:
                plan = make_plan(self.input_table, task=self.task, request=self.request, parameters=p)
            self._ctx["research_plan"] = (signature, plan)
        return self._ctx["research_plan"][1]

    def build_plan(self) -> Data:
        from copy import deepcopy

        return Data(data=deepcopy(self._plan()))

    def build_preview(self) -> Message:
        p = self._plan()
        lines = [
            "计划可执行。" if p["ready"] else "需要补充信息，尚未执行计算。",
            f"输入 {p['input']['rows']} 行、{len(p['input']['columns'])} 列；"
            f"任务：{load_skill(p['task'])['title'] if p['task'] else '待选择'}。",
        ]
        lines.extend(f"{i + 1}. {step}" for i, step in enumerate(p["steps"]))
        lines.extend(f"待补：{item['message']}" for item in p["issues"])
        labels = {
            "curve_id": "曲线编号",
            "x": "波长列",
            "y": "强度列",
            "group": "组别",
            "sample_id": "样品编号",
            "strain": "应变列",
            "stress": "应力列",
            "experimental_unit": "独立试验单位",
            "peak_window": "候选窗口（nm）",
            "fit_range": "弹性拟合区间",
            "x_unit": "波长单位",
            "y_unit": "强度单位",
            "strain_unit": "应变单位",
            "stress_unit": "应力单位",
            "value_unit": "测量值单位",
            "selection_rule": "候选选择规则",
            "prominence_mode": "阈值来源",
            "unit_mode": "统计单位方式",
            "small_sample_policy": "小样本政策",
        }
        lines.extend(f"{labels[k]}：{v}" for k, v in p["parameters"].items() if k in labels and v is not None)
        lines.extend("提示：" + w for w in p["warnings"])
        return Message(text="\n".join(lines))

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name in build_config:
            build_config[field_name]["value"] = field_value
        task = build_config["task"].get("value", self.task)
        request = build_config["request"].get("value", self.request)
        task = _route(request) if task == "auto" else task
        # No inferred task: display task selector and request, rather than all task fields.
        allowed = VISIBLE.get(task, set())
        for name in set().union(*VISIBLE.values()):
            build_config[name]["show"] = name in allowed
        if task == "mechanics":
            build_config["x_column"]["display_name"] = "应变列"
            build_config["y_column"]["display_name"] = "应力列"
        else:
            build_config["x_column"]["display_name"] = "波长列"
            build_config["y_column"]["display_name"] = "强度列"
        if task == "spectra":
            for name in ("smooth_window", "smooth_order"):
                build_config[name]["show"] = bool(build_config["smooth"].get("value", self.smooth))
            build_config["baseline_value"]["show"] = build_config["baseline"].get("value") == "constant"
            threshold = THRESHOLD_MODES.get(
                build_config["prominence_mode"].get("value"), build_config["prominence_mode"].get("value")
            )
            build_config["prominence"]["show"] = threshold == "absolute"
            for name in ("noise_confirmed", "noise_low", "noise_high", "noise_multiplier"):
                build_config[name]["show"] = threshold == "noise_reference"
            build_config["peak_distance_x"]["show"] = bool(build_config["distance_enabled"].get("value"))
            unit = UNIT_MODES.get(
                build_config["unit_mode"].get("value"), build_config["unit_mode"].get("value")
            )
            build_config["unit_column"]["show"] = unit == "sample"
            build_config["unit_confirmed"]["show"] = unit != "descriptive"
        if field_name == "input_table" and hasattr(field_value, "columns"):
            for name in COLUMNS:
                build_config[name]["options"] = ["", *field_value.columns.tolist()]
        return build_config

    def to_frontend_node(self, *args, **kwargs):
        result = super().to_frontend_node(*args, **kwargs)
        result["data"]["node"]["field_order"] = [field.name for field in self.inputs]
        self.update_build_config(result["data"]["node"]["template"], None)
        return prepare_form(result)

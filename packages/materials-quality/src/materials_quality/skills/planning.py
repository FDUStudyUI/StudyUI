"""One validation contract for forms, CLI and untrusted model proposals."""

from copy import deepcopy
from math import isfinite

from materials_quality.context import table_fingerprint
from materials_quality.science.contracts import require_table
from materials_quality.science.table_contract import contract_identity, read_contract
from materials_quality.units import _unit

from .registry import SKILLS, digest, load_skill
from .semantics import analysis_contract

ALIASES = {
    "curve_id": ["curve_id", "particle_id", "颗粒编号", "曲线编号"],
    "x": ["x", "wavelength_nm", "wavelength", "波长", "波长_nm"],
    "y": ["y", "intensity", "intensity_counts", "强度"],
    "group": ["group", "condition", "组别", "条件"],
    "sample_id": ["sample_id", "specimen_id", "sample", "样品编号"],
    "strain": ["strain", "strain_fraction", "应变"],
    "stress": ["stress", "stress_MPa", "应力"],
    "variable": ["variable", "变量"],
    "value": ["value", "测量值"],
    "experimental_unit": ["experimental_unit", "unit_id", "独立试验单位"],
}
COMMON = {"data_kind", "band"}
CONFIRMATIONS = {
    "spectra": {
        "x_unit",
        "y_unit",
        "peak_window",
        "unit_mode",
        "unit_confirmed",
        "experimental_unit",
        "noise_window",
        "small_sample_policy",
    },
    "mechanics": {"strain_unit", "stress_unit", "fit_range", "single_sample"},
    "contrast": {"experimental_unit", "design", "value_unit", "small_sample_policy"},
}
FIELDS = {
    "spectra": {
        "curve_id",
        "x",
        "y",
        "group",
        "x_unit",
        "y_unit",
        "peak_window",
        "baseline",
        "baseline_value",
        "smooth",
        "smooth_window",
        "smooth_order",
        "prominence",
        "selection_rule",
        "prominence_mode",
        "noise_window",
        "noise_multiplier",
        "peak_distance_x",
        "unit_mode",
        "unit_confirmed",
        "experimental_unit",
        "small_sample_policy",
    }
    | COMMON,
    "mechanics": {
        "sample_id",
        "strain",
        "stress",
        "group",
        "single_sample",
        "strain_unit",
        "stress_unit",
        "fit_range",
        "yield_offset",
    }
    | COMMON,
    "contrast": {
        "group",
        "variable",
        "value",
        "sample_id",
        "experimental_unit",
        "design",
        "strategy",
        "correction",
        "value_unit",
        "alpha",
        "small_sample_policy",
    }
    | COMMON,
}
STEPS = {
    "spectra": [
        "核对曲线与单位",
        "逐曲线基线和平滑",
        "窗口候选峰与完整特征",
        "分组描述与均值带",
        "导出与追溯",
    ],
    "mechanics": [
        "核对样品与单位",
        "逐样品弹性区间拟合",
        "偏移法规定塑性延伸强度",
        "曲线与指标汇总",
        "导出与追溯",
    ],
    "contrast": [
        "确认试验设计",
        "按独立试验单位聚合技术重复",
        "组间检验和效应量",
        "Holm/FDR 校正",
        "绘图与追溯",
    ],
}


def input_identity(table):
    require_table(table)
    return {
        "sha256": digest([table_fingerprint(table), table.attrs.get("units", {})]),
        "rows": len(table),
        "columns": list(table.columns),
        "contract_sha256": contract_identity(table),
    }


def _route(request):
    words = str(request).lower()
    cues = {
        "spectra": ("光谱", "spectr", "raman", "拉曼", "暗场", "候选峰"),
        "mechanics": ("力学", "拉伸", "模量", "应力", "mechanic", "tensile"),
        "contrast": ("组间", "显著性", "效应量", "对照研究", "contrast", "anova"),
    }
    matched = [task for task, keys in cues.items() if any(k in words for k in keys)]
    domains = [t for t in matched if t != "contrast"]
    if len(domains) == 1:
        return domains[0]
    return matched[0] if len(matched) == 1 else None


def make_plan(table, task="auto", request="", parameters=None, proposal=None):
    """Return a preview, with blocking issues instead of silently inventing metadata."""
    identity = input_identity(table)
    if not isinstance(request, str) or len(request) > 8000:
        raise ValueError("request must be text up to 8000 characters")
    supplied = deepcopy(parameters or {})
    if not isinstance(supplied, dict):
        raise ValueError("parameters must be an object")
    explicit_fields = set(supplied)
    if proposal is not None:
        if (
            not isinstance(proposal, dict)
            or set(proposal) != {"task", "parameters"}
            or proposal["task"] not in SKILLS
            or not isinstance(proposal["parameters"], dict)
        ):
            raise ValueError("model proposal must contain only registered task and parameters")
        if task not in {"auto", proposal["task"]}:
            raise ValueError("proposal conflicts with the explicitly selected task")
        task = proposal["task"]
        supplied = {**proposal["parameters"], **supplied}
    task = _route(request) if task == "auto" else task
    issues, warnings = [], []

    def issue(field, message):
        issues.append({"field": field, "message": message})

    if proposal is not None and task in CONFIRMATIONS:
        for field in sorted(CONFIRMATIONS[task] & proposal["parameters"].keys() - explicit_fields):
            issue(field, f"请通过表单或显式参数确认模型建议的 {field}。")

    if task is None:
        issue("task", "请选择光谱、力学或组间研究，或具体描述分析目标。")
        skill, p = None, supplied
    else:
        if task not in SKILLS:
            raise ValueError("unknown registered research task")
        if set(supplied) - FIELDS[task]:
            raise ValueError(f"未知参数 / unknown parameter: {sorted(set(supplied) - FIELDS[task])}")
        skill, p = load_skill(task), supplied
        p.setdefault("data_kind", "unspecified")
        p.setdefault("band", "iqr")
        if not isinstance(p["data_kind"], str) or p["data_kind"] not in {
            "unspecified",
            "synthetic",
            "measured",
            "simulated",
            "derived",
        }:
            issue("data_kind", "数据性质必须为已支持的选项。")
        if not isinstance(p["band"], str) or p["band"] not in {"iqr", "sd", "ci95"}:
            issue("band", "误差带必须选择 iqr、sd 或 ci95。")

        def column(key, required=True):
            if key not in p or p[key] in (None, ""):
                candidates = [c for c in table.columns if c in ALIASES[key]]
                p[key] = candidates[0] if len(candidates) == 1 else None
                if len(candidates) > 1:
                    issue(key, f"候选列不唯一，请选择：{candidates}")
            if p[key] is None:
                if required:
                    issue(key, f"请选择 {key} 对应的数据列。")
            elif not isinstance(p[key], str) or p[key] not in table.columns:
                issue(key, f"输入中不存在列：{p[key]}")

        def choice(key, values):
            if not isinstance(p.get(key), str) or p.get(key) not in values:
                issue(key, f"请明确 {key}：{', '.join(sorted(values))}。")

        def number(key, default=None, positive=False, integer=False):
            p.setdefault(key, default)
            v = p[key]
            if (
                type(v) not in (int, float)
                or not isfinite(v)
                or (positive and v <= 0)
                or (integer and type(v) is not int)
            ):
                issue(key, f"{key} 必须为{'正' if positive else '有限'}数值。")
                p[key] = None

        def interval(key):
            v = p.get(key)
            if (
                not isinstance(v, (list, tuple))
                or len(v) != 2
                or any(type(n) not in (int, float) or not isfinite(n) for n in v)
                or v[0] >= v[1]
            ):
                issue(key, f"请明确 {key} 的下限和上限，下限必须小于上限。")
                p[key] = None
            else:
                p[key] = list(v)

        if task == "spectra":
            for key in ("curve_id", "x", "y"):
                column(key)
            column("group", False)
            for key in ("x_unit", "y_unit"):
                if not isinstance(p.get(key), str) or not p[key].strip():
                    issue(key, "请明确单位，列名仅用于字段建议。")
            interval("peak_window")
            p.setdefault("baseline", "none")
            choice("baseline", {"none", "constant", "linear"})
            number("baseline_value", 0)
            p.setdefault("smooth", False)
            if type(p["smooth"]) is not bool:
                issue("smooth", "平滑开关必须为布尔值。")
            number("smooth_window", 7, positive=True, integer=True)
            number("smooth_order", 2, integer=True)
            if p["smooth_window"] is not None and p["smooth_order"] is not None:
                if p["smooth_window"] % 2 != 1 or not 0 <= p["smooth_order"] < p["smooth_window"]:
                    issue("smooth_window", "平滑窗口必须为奇数，且大于多项式阶数。")
            if "prominence" in p:
                number("prominence", positive=True)
            p.setdefault("selection_rule", "highest_prominence")
            choice("selection_rule", {"highest_prominence", "redmost"})
            p.setdefault("prominence_mode", "absolute" if "prominence" in p else "legacy_relative")
            choice("prominence_mode", {"legacy_relative", "absolute", "noise_reference"})
            if p["prominence_mode"] == "absolute" and "prominence" not in p:
                issue("prominence", "请输入正的突出度阈值，单位与处理后的信号相同。")
            if p["prominence_mode"] != "absolute" and "prominence" in p:
                issue("prominence_mode", "指定阈值与阈值模式冲突，请选择一种来源。")
            if p["prominence_mode"] == "noise_reference":
                interval("noise_window")
                number("noise_multiplier", 5, positive=True)
            if "peak_distance_x" in p:
                number("peak_distance_x", positive=True)
            p.setdefault("unit_mode", "descriptive")
            choice("unit_mode", {"descriptive", "curve", "sample"})
            p.setdefault("unit_confirmed", False)
            if type(p["unit_confirmed"]) is not bool:
                issue("unit_confirmed", "独立单位确认必须为勾选项。")
            if p["unit_mode"] != "descriptive" and p["unit_confirmed"] is not True:
                issue("unit_confirmed", "请确认独立试验单位及处理条件的施加层级；未确认时仅做描述。")
            if p["band"] == "ci95" and (p["unit_mode"] == "descriptive" or p["unit_confirmed"] is not True):
                issue("band", "均值置信带需确认独立单位；未确认时请选择四分位或标准差描述带。")
            if p["unit_mode"] == "sample":
                column("experimental_unit")
            warnings.append("窗口候选峰不等同于确认的物理模式；组内光谱带是描述统计。")
        elif task == "mechanics":
            for key in ("strain", "stress"):
                column(key)
            p.setdefault("single_sample", False)
            if type(p["single_sample"]) is not bool:
                issue("single_sample", "单样品声明必须为布尔值。")
            column("sample_id", not p["single_sample"])
            column("group", False)
            choice("strain_unit", {"fraction", "%"})
            choice("stress_unit", {"Pa", "kPa", "MPa", "GPa"})
            interval("fit_range")
            number("yield_offset", 0.002, positive=True)
            warnings.append("偏移量按应变分数输入；弹性区间须由试验依据确定。")
        else:
            for key in ("group", "variable", "value", "sample_id", "experimental_unit"):
                column(key)
            choice("design", {"independent", "paired"})
            p.setdefault("strategy", "parametric")
            p.setdefault("correction", "holm")
            choice("strategy", {"parametric", "nonparametric"})
            choice("correction", {"holm", "fdr_bh"})
            if not isinstance(p.get("value_unit"), str) or not p["value_unit"].strip():
                issue("value_unit", "请明确测量值单位，可使用 dimensionless。")
            number("alpha", 0.05, positive=True)
            if p["alpha"] is not None and p["alpha"] >= 1:
                issue("alpha", "显著性水平必须介于 0 和 1。")
            warnings.append("先按独立试验单位平均技术重复，再进行预先指定的组间检验。")
        if task in {"spectra", "contrast"}:
            p.setdefault("small_sample_policy", "descriptive")
            choice("small_sample_policy", {"descriptive", "model_based"})
        _units(table, task, p, issue)
        selected = {k: p[k] for k in ALIASES if k in p and isinstance(p[k], str) and p[k] in table}
        for name in set(selected.values()):
            sharing = {k for k, v in selected.items() if v == name}
            if len(sharing) > 1 and not sharing <= {"sample_id", "experimental_unit", "curve_id"}:
                issue("columns", "不同测量含义的字段必须选择不同的数据列。")
    semantic = None
    if task is not None and not issues:
        semantic, semantic_issues = analysis_contract(table, task, p)
        issues.extend(semantic_issues)
    plan = {
        "schema_version": "research-plan/2",
        "task": task,
        "request": request,
        "parameters": p,
        "input": identity,
        "skill": {k: skill[k] for k in ("name", "version", "sha256")} if skill else None,
        "steps": STEPS.get(task, []),
        "issues": issues,
        "warnings": warnings,
        "ready": not issues,
        "analysis_contract": semantic,
    }
    plan["plan_sha256"] = digest(plan)
    return plan


def _units(table, task, p, issue):
    contract = read_contract(table)
    semantic_units = contract["units_state"].get("units", {}) if contract else {}
    if not isinstance(semantic_units, dict):
        issue("contract", "数据契约的单位声明必须为列名到单位的映射。")
        return
    pairs = {
        "spectra": [("x", "x_unit"), ("y", "y_unit")],
        "mechanics": [("strain", "strain_unit"), ("stress", "stress_unit")],
        "contrast": [("value", "value_unit")],
    }[task]
    stored_units = table.attrs.get("units", {})
    if not isinstance(stored_units, dict):
        issue("contract", "数据表的单位声明必须为列名到单位的映射。")
        stored_units = {}
    for column, key in pairs:
        unit = p.get(key)
        if not unit:
            continue
        try:
            actual = _unit("dimensionless" if unit == "fraction" else unit)
        except Exception:
            issue(key, f"无法识别单位：{unit}。")
            continue
        for stored in (stored_units.get(p.get(column)), semantic_units.get(p.get(column))):
            if stored is None:
                continue
            try:
                parsed = _unit(stored)
            except Exception:
                # Name the unparseable upstream value, not the declared unit.
                issue(key, f"无法识别上游单位：{stored}。")
                continue
            if parsed != actual:
                issue(key, f"声明单位与上游单位冲突：{stored} / {unit}。")
        if task == "spectra" and key == "x_unit" and not actual.is_compatible_with(_unit("nm")):
            issue(key, "候选波长窗口要求长度单位。")


def validate_plan(table, plan):
    if not isinstance(plan, dict) or plan.get("schema_version") != "research-plan/2":
        raise ValueError("unsupported research plan / 计划版本已更新，请重新运行规划节点。")
    content = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if digest(content) != plan.get("plan_sha256"):
        raise ValueError("计划内容已修改 / plan fingerprint mismatch，请重新生成。")
    if input_identity(table) != plan.get("input"):
        raise ValueError("输入数据或单位已改变 / stale input，请重新规划。")
    if not plan.get("ready"):
        raise ValueError("计划需要补充信息：" + "; ".join(i["message"] for i in plan.get("issues", [])))
    fresh = make_plan(
        table, task=plan.get("task"), request=plan.get("request", ""), parameters=plan.get("parameters")
    )
    if "model_assistance" in plan:
        assistance = plan["model_assistance"]
        if (
            not isinstance(assistance, dict)
            or set(assistance) != {"provider", "model", "raw_rows_sent"}
            or assistance["provider"] != "chat-completions"
            or assistance["raw_rows_sent"] is not False
            or not isinstance(assistance["model"], str)
        ):
            raise ValueError("invalid model provenance")
        fresh["model_assistance"] = deepcopy(assistance)
        fresh["plan_sha256"] = digest({k: v for k, v in fresh.items() if k != "plan_sha256"})
    if fresh != plan:
        raise ValueError("计划与当前技能或校验规则不一致，请重新规划。")
    if not fresh["ready"]:
        raise ValueError("计划需要补充信息：" + "; ".join(i["message"] for i in fresh["issues"]))
    return deepcopy(fresh)

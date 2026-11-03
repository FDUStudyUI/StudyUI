"""Native form definitions; task-specific parameters remain ordinary controls."""

from lfx.io import BoolInput, DataFrameInput, DropdownInput, FloatInput, IntInput, MultilineInput, StrInput

COLUMNS = {
    "curve_column": "曲线/颗粒编号列",
    "x_column": "波长列",
    "y_column": "强度列",
    "group_column": "组别列（可选）",
    "sample_column": "样品/技术样本编号列",
    "variable_column": "变量标识列",
    "value_column": "测量值列",
    "unit_column": "独立试验单位/配对编号列",
}
VISIBLE = {
    "spectra": {
        "curve_column",
        "x_column",
        "y_column",
        "group_column",
        "x_unit",
        "y_unit",
        "window_confirmed",
        "window_low",
        "window_high",
        "baseline",
        "baseline_value",
        "smooth",
        "smooth_window",
        "smooth_order",
        "band",
    },
    "mechanics": {
        "x_column",
        "y_column",
        "group_column",
        "sample_column",
        "single_sample",
        "strain_unit",
        "stress_unit",
        "fit_confirmed",
        "fit_low",
        "fit_high",
        "yield_offset",
    },
    "contrast": {
        "group_column",
        "sample_column",
        "variable_column",
        "value_column",
        "unit_column",
        "design",
        "strategy",
        "correction",
        "alpha",
        "value_unit",
    },
}


def planner_inputs():
    return [
        DataFrameInput(name="input_table", display_name="输入数据表", required=True),
        DropdownInput(
            name="task",
            display_name="分析任务",
            options=["auto", "spectra", "mechanics", "contrast"],
            value="auto",
            real_time_refresh=True,
            info="auto=按描述识别；spectra=批量光谱；mechanics=材料力学；contrast=组间研究。",
        ),
        MultilineInput(
            name="request",
            display_name="描述分析目标",
            value="",
            real_time_refresh=True,
            info="例如：比较不同条件的光谱候选峰。可直接选任务、填下面的表单，无需模型。",
        ),
        BoolInput(
            name="use_model",
            display_name="使用模型辅助建议",
            value=False,
            advanced=True,
            info="需配置 STUDYUI_MODEL_BASE_URL / STUDYUI_MODEL；只发送列结构和缺失计数，不发送原始行。",
        ),
        DropdownInput(
            name="data_kind",
            display_name="数据性质",
            value="unspecified",
            options=["unspecified", "synthetic", "measured", "simulated", "derived"],
        ),
        *[
            DropdownInput(name=n, display_name=d, options=[""], value="", combobox=True)
            for n, d in COLUMNS.items()
        ],
        DropdownInput(
            name="x_unit",
            display_name="波长单位（请确认）",
            value="",
            options=["", "nm", "um", "m"],
            combobox=True,
        ),
        StrInput(name="y_unit", display_name="强度单位（如 counts）", value=""),
        BoolInput(name="window_confirmed", display_name="确认采用下方候选窗口", value=False),
        FloatInput(name="window_low", display_name="候选窗口下限（nm）", value=650),
        FloatInput(name="window_high", display_name="候选窗口上限（nm）", value=850),
        DropdownInput(
            name="baseline",
            display_name="基线方法",
            options=["none", "constant", "linear"],
            value="none",
            real_time_refresh=True,
        ),
        FloatInput(name="baseline_value", display_name="常数基线", value=0),
        BoolInput(
            name="smooth", display_name="启用 Savitzky–Golay 平滑", value=False, real_time_refresh=True
        ),
        IntInput(name="smooth_window", display_name="平滑窗口点数（奇数）", value=7),
        IntInput(name="smooth_order", display_name="平滑多项式阶数", value=2),
        DropdownInput(
            name="band",
            display_name="光谱带",
            options=["iqr", "sd", "ci95"],
            value="iqr",
            info="iqr=逐波长四分位范围；sd=标准差；ci95=均值逐点 t 置信区间。",
        ),
        BoolInput(name="single_sample", display_name="明确输入仅有一个力学样品", value=False),
        DropdownInput(
            name="strain_unit", display_name="应变单位（请确认）", options=["", "fraction", "%"], value=""
        ),
        DropdownInput(
            name="stress_unit",
            display_name="应力单位（请确认）",
            options=["", "Pa", "kPa", "MPa", "GPa"],
            value="",
        ),
        BoolInput(name="fit_confirmed", display_name="确认采用下方弹性拟合区间", value=False),
        FloatInput(name="fit_low", display_name="弹性区间下限（输入应变单位）", value=0),
        FloatInput(name="fit_high", display_name="弹性区间上限（输入应变单位）", value=0.0008),
        FloatInput(name="yield_offset", display_name="偏移量（应变分数，0.002=0.2%）", value=0.002),
        DropdownInput(
            name="design", display_name="试验设计（请确认）", options=["", "independent", "paired"], value=""
        ),
        DropdownInput(
            name="strategy",
            display_name="统计策略",
            options=["parametric", "nonparametric"],
            value="parametric",
        ),
        DropdownInput(
            name="correction", display_name="多重比较校正", options=["holm", "fdr_bh"], value="holm"
        ),
        FloatInput(name="alpha", display_name="显著性水平", value=0.05),
        StrInput(name="value_unit", display_name="测量值单位（如 MPa 或 dimensionless）", value=""),
    ]


def parameters_from(node, task):
    p = {"data_kind": node.data_kind}
    names = {
        "spectra": {
            "curve_id": "curve_column",
            "x": "x_column",
            "y": "y_column",
            "group": "group_column",
            "x_unit": "x_unit",
            "y_unit": "y_unit",
            "baseline": "baseline",
            "baseline_value": "baseline_value",
            "smooth": "smooth",
            "smooth_window": "smooth_window",
            "smooth_order": "smooth_order",
            "band": "band",
        },
        "mechanics": {
            "strain": "x_column",
            "stress": "y_column",
            "sample_id": "sample_column",
            "group": "group_column",
            "single_sample": "single_sample",
            "strain_unit": "strain_unit",
            "stress_unit": "stress_unit",
            "yield_offset": "yield_offset",
        },
        "contrast": {
            "group": "group_column",
            "sample_id": "sample_column",
            "experimental_unit": "unit_column",
            "variable": "variable_column",
            "value": "value_column",
            "design": "design",
            "strategy": "strategy",
            "correction": "correction",
            "alpha": "alpha",
            "value_unit": "value_unit",
        },
    }
    for key, field in names.get(task, {}).items():
        value = getattr(node, field)
        if value is not None and value != "":
            p[key] = value
    if task == "spectra" and node.window_confirmed:
        p["peak_window"] = [node.window_low, node.window_high]
    if task == "mechanics" and node.fit_confirmed:
        p["fit_range"] = [node.fit_low, node.fit_high]
    return p

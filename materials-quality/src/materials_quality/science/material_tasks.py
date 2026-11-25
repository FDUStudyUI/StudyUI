"""Versioned materials task knowledge and observable method prerequisites.

The task layer joins domain notes, native operations and executable checks.
It returns specific next actions so missing information can be completed in a form.
"""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from .units import normalize_unit_label

VERSION = "1.0.0"
SOURCES = {
    "tensile": {
        "title": "ASTM E8/E8M: Tension Testing of Metallic Materials",
        "url": "https://www.astm.org/e0008_e0008m.html",
    },
    "modulus": {
        "title": "ASTM E111: Young's Modulus, Tangent Modulus, and Chord Modulus",
        "url": "https://www.astm.org/e0111.html",
    },
    "peaks": {
        "title": "SciPy find_peaks: prominence, width and sampling conditions",
        "url": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html",
    },
    "smooth": {
        "title": "SciPy Savitzky-Golay filter: window and polynomial conditions",
        "url": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html",
    },
    "xrd": {
        "title": "IUCr Online Dictionary: Bragg's law",
        "url": "https://dictionary.iucr.org/Bragg%27s_law",
    },
    "width": {
        "title": "IUCr Online Dictionary: Scherrer equation",
        "url": "https://dictionary.iucr.org/Scherrer_equation",
    },
    "units": {"title": "BIPM SI Brochure", "url": "https://www.bipm.org/en/publications/si-brochure"},
}

# Authored task notes bind existing operations; no upstream executable assets are loaded.
_NOTES = {
    "mechanics": [
        (
            "measurement",
            "测量链与几何换算",
            "区分载荷、横梁位移、引伸计和工程应变。",
            "载荷换算应力需原截面积；位移换算应变需标距和测量来源。",
            "preprocess.filter",
            "units",
        ),
        (
            "loading",
            "零点与有效加载段",
            "保留原始曲线，显式选择同一试样的加载段。",
            "卸载和循环曲线应先分段；重复坐标需确认采集含义。",
            "preprocess.filter",
            "tensile",
        ),
        (
            "elastic",
            "弹性区选择",
            "以确认的应变区间拟合斜率，并检查残差与区间敏感性。",
            "至少三个有效点；较高 R² 本身不能证明测量链或区间正确。",
            "materials.mechanics",
            "modulus",
        ),
        (
            "yield",
            "偏移屈服指标",
            "使用显式偏移应变寻找拟合线与实测曲线的交点。",
            "交点必须在拟合区间之后且被实测覆盖；无交点时保留未测得状态。",
            "materials.mechanics",
            "tensile",
        ),
        (
            "strength",
            "强度与延伸指标",
            "报告实测最大应力及其位置；确认断裂后才报告断裂应变。",
            "工程应力与真实应力不可混用，末点不能自动视为断裂点。",
            "materials.mechanics",
            "tensile",
        ),
        (
            "groups",
            "批次与独立试样统计",
            "先生成试样级特征，再按工艺条件比较。",
            "同一试样的采样点或技术重复不增加独立试样数。",
            "ContrastStudy",
            "tensile",
        ),
    ],
    "spectra": [
        (
            "coordinates",
            "坐标与信号语义",
            "明确波长、波数、拉曼位移及纵轴含义。",
            "波长转拉曼位移需要激发波长；透射率不能直接当吸光度。",
            "preprocess.units",
            "units",
        ),
        (
            "background",
            "背景与参考校正",
            "保留原始信号，记录所选背景策略及参考来源。",
            "端点线性背景可能改变宽峰；绝对强度比较需匹配曝光和参考条件。",
            "materials.spectra",
            "peaks",
        ),
        (
            "smoothing",
            "平滑与采样条件",
            "按采样间隔和峰宽选择平滑窗口，并比较处理前后曲线。",
            "SG 窗口与阶数需匹配；不等距采样需先选择适合的方法。",
            "materials.spectra",
            "smooth",
        ),
        (
            "selection",
            "候选峰与选择规则",
            "记录突出度、窗口、峰宽、候选数及未检出状态。",
            "窗口选择的峰不是已确认的物理模式；重叠峰应单独复核。",
            "BatchSpectrumAnalyzer",
            "peaks",
        ),
        (
            "normalization",
            "归一化与研究目标",
            "形状比较可归一化，绝对强度比较保留物理强度分支。",
            "SNV、最大值和面积归一化会改变幅度的含义。",
            "preprocess.normalize",
            "units",
        ),
        (
            "groups",
            "曲线与独立样品统计",
            "按曲线提取特征，按真实实验单位聚合并报告检出率。",
            "同一颗粒的多次采集不是独立样品；组间检验需明确实验单位。",
            "ContrastStudy",
            "peaks",
        ),
    ],
    "xrd": [
        (
            "scan",
            "扫描与辐射信息",
            "记录 2θ、步长、辐射源和强度单位。",
            "计算晶面间距需要已知波长，角度定义必须为 2θ。",
            "materials.xrd",
            "xrd",
        ),
        (
            "background",
            "衍射背景处理",
            "保留原始谱并比较背景与扣除后的信号。",
            "非晶宽峰和荧光背景应结合实验条件选择基线模型。",
            "materials.xrd",
            "peaks",
        ),
        (
            "peaks",
            "候选衍射峰",
            "提取峰位、突出度、表观峰宽及测量范围。",
            "检出峰属于描述性证据，不能直接给出材料物相身份。",
            "materials.xrd",
            "peaks",
        ),
        (
            "profiles",
            "峰形与重叠峰",
            "对局部峰形拟合并查看残差和重叠情况。",
            "经验峰形拟合不等于结构 Rietveld 精修。",
            "materials.xrd",
            "width",
        ),
        (
            "references",
            "参考谱比较",
            "用提供的参考峰表匹配，保留参考版本和容差。",
            "匹配得分用于候选排序，需结合缺失峰和实验条件判读。",
            "materials.xrd",
            "xrd",
        ),
        (
            "widths",
            "峰宽模型与仪器条件",
            "区分表观峰宽、仪器展宽和模型解释。",
            "晶粒尺寸估计需要波长、形状因子和仪器展宽依据。",
            "materials.xrd",
            "width",
        ),
    ],
}


def task_catalog():
    titles = {"mechanics": "力学性能", "spectra": "光谱特征", "xrd": "XRD 表征"}
    return [
        {
            "id": task,
            "title": titles[task],
            "version": VERSION,
            "operation": "materials." + task,
            "cards": [
                {
                    "id": f"{task}.{key}",
                    "title": title,
                    "objective": objective,
                    "conditions": conditions,
                    "operation": operation,
                    "version": VERSION,
                    "source": deepcopy(SOURCES[source]),
                }
                for key, title, objective, conditions, operation, source in notes
            ],
        }
        for task, notes in _NOTES.items()
    ]


def assess_protocol(table, spec):
    """Twelve task-specific checks with evidence and a next action; no input mutation."""
    task = spec["task"]
    checks = []

    def check(key, ok, observed, expected, action, outcome="need_info"):
        checks.append(
            {
                "check_id": task + "." + key,
                "protocol_version": VERSION,
                "outcome": "pass" if bool(ok) else outcome,
                "observed": observed,
                "expected": expected,
                "suggested_action": "" if ok else action,
                "affected_steps": ["analysis"],
            }
        )

    x, y = spec.get("x"), spec.get("y")
    x_ok, y_ok = x in table, y in table and y != x
    check("coordinate_column", x_ok, x, "实际横坐标列", "从列选择器选择横坐标。")
    check("signal_column", y_ok, y, "不同于横坐标的信号列", "从列选择器选择信号。")
    values = (
        table[[x, y]].apply(pd.to_numeric, errors="coerce").to_numpy(float)
        if x_ok and y_ok
        else np.empty((0, 2))
    )
    finite = bool(len(values) and np.isfinite(values).all())
    check(
        "finite_values",
        finite,
        int(np.count_nonzero(~np.isfinite(values))),
        "有限数值",
        "查看缺失值或非数值行。",
    )
    check("point_count", len(values) >= 3, len(values), "至少三个测量点", "选择包含完整曲线的数据区域。")
    coordinate = np.sort(values[:, 0]) if spec.get("sort", False) else values[:, 0]
    increasing = finite and len(values) >= 3 and bool((np.diff(coordinate) > 0).all())
    check(
        "coordinate_order",
        increasing,
        {"increasing": increasing, "explicit_sort": bool(spec.get("sort", False))},
        "单条严格递增曲线，或明确按坐标排序的唯一采样点",
        "分开不同曲线或选择有效加载段。",
        "change_method" if finite and len(values) >= 3 else "need_info",
    )
    units = [spec.get("x_unit", ""), spec.get("y_unit", "")]
    check("declared_units", all(str(u).strip() for u in units), units, "横纵轴单位明确", "填写实测单位。")
    if task == "mechanics":
        strain_unit = normalize_unit_label(units[0], "strain")
        stress_unit = normalize_unit_label(units[1], "stress")
        check(
            "strain_unit", strain_unit in {"fraction", "%"}, units[0], "fraction 或 %", "确认工程应变单位。"
        )
        check(
            "stress_unit",
            stress_unit in {"Pa", "kPa", "MPa", "GPa"},
            units[1],
            "Pa、kPa、MPa 或 GPa",
            "确认工程应力单位。",
        )
        bounds = spec.get("fit_range", [])
        valid_bounds = len(bounds) == 2 and all(np.isfinite(v) for v in bounds) and bounds[0] < bounds[1]
        within = finite and valid_bounds and values[:, 0].min() <= bounds[0] < bounds[1] <= values[:, 0].max()
        check("fit_range", within, bounds, "实测范围内的递增区间", "填写初始弹性区间。")
        selected = (
            values[(values[:, 0] >= bounds[0]) & (values[:, 0] <= bounds[1])] if within else np.empty((0, 2))
        )
        check(
            "fit_points", len(selected) >= 3, len(selected), "拟合区间至少三个点", "扩大拟合区间或增加采样。"
        )
        offset = spec.get("yield_offset")
        positive_offset = isinstance(offset, (int, float)) and np.isfinite(offset) and offset > 0
        check(
            "offset_definition", positive_offset, offset, "明确的正偏移应变（fraction）", "填写屈服偏移定义。"
        )
        rising = len(selected) >= 3 and np.ptp(selected[:, 0]) > 0 and np.cov(selected.T)[0, 1] > 0
        check(
            "positive_elastic_trend",
            rising,
            bool(rising),
            "拟合区间呈正应力趋势",
            "重新选择弹性段并检查符号。",
            "change_method" if len(selected) >= 3 else "need_info",
        )
    else:
        baseline, prominence = spec.get("baseline"), spec.get("prominence")
        check(
            "baseline_choice",
            baseline in {"none", "linear"},
            baseline,
            "明确的基线策略",
            "选择不扣基线或端点线性基线。",
        )
        valid_prominence = isinstance(prominence, (int, float)) and np.isfinite(prominence) and prominence > 0
        check(
            "peak_threshold",
            valid_prominence,
            prominence,
            "信号单位下的正突出度",
            "结合噪声和目标峰设置突出度。",
        )
        varied = finite and np.ptp(values[:, 1]) > 0
        check(
            "signal_variation", varied, bool(varied), "信号有可分辨变化", "检查平直曲线或饱和信号。", "review"
        )
        if task == "spectra":
            check(
                "coordinate_semantics",
                units[0] in {"nm", "cm^-1", "cm-1", "eV", "Hz"},
                units[0],
                "明确的光谱坐标",
                "核对波长、波数或能量定义。",
                "review",
            )
            kind = spec.get("signal_kind", "intensity")
            check(
                "peak_sign",
                kind != "transmittance",
                kind,
                "强度或吸光度的正峰",
                "透射率请先转换或选用谷检测。",
                "change_method" if finite else "need_info",
            )
            check(
                "threshold_vs_signal",
                valid_prominence and varied and prominence <= np.ptp(values[:, 1]),
                prominence,
                "突出度不超过实测信号变化范围",
                "当前阈值可能不检出峰；核对目标与噪声。",
                "review",
            )
        else:
            check("angle_unit", units[0] == "deg", units[0], "2θ，单位 deg", "确认角度定义并转换为度。")
            angle_range = finite and values[:, 0].min() >= 0 and values[:, 0].max() <= 180
            check(
                "angle_range",
                angle_range,
                [float(values[:, 0].min()), float(values[:, 0].max())] if finite else None,
                "0–180° 的 2θ",
                "检查坐标列或角度定义。",
                "change_method" if finite else "need_info",
            )
            check(
                "threshold_vs_signal",
                valid_prominence and varied and prominence <= np.ptp(values[:, 1]),
                prominence,
                "突出度不超过实测信号变化范围",
                "当前阈值可能不检出峰；核对目标与背景。",
                "review",
            )
    blocking = [c for c in checks if c["outcome"] in {"need_info", "change_method", "fail"}]
    status = (
        "change_method"
        if any(c["outcome"] == "change_method" for c in blocking)
        else "need_info"
        if blocking
        else "ready"
    )
    return {
        "task": task,
        "version": VERSION,
        "status": status,
        "checks": checks,
        "next_actions": list(dict.fromkeys(c["suggested_action"] for c in checks if c["outcome"] != "pass")),
        "cards": next(t["cards"] for t in task_catalog() if t["id"] == task),
    }

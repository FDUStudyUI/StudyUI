"""Structured materials-domain knowledge, applicability scopes, and limitations.

Extends the three single-curve protocols in ``science.material_tasks``
(mechanics, spectra, XRD) with two additional typical materials-science task
domains (battery cycling and TG/DSC thermal analysis), totaling 5 typical
tasks and 30 method cards, without mutating ``material_tasks.task_catalog()``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from materials_quality.science.material_tasks import SOURCES as BASE_SOURCES
from materials_quality.science.material_tasks import VERSION, task_catalog

EXTENDED_SOURCES: dict[str, dict[str, str]] = {
    **BASE_SOURCES,
    "battery_iec": {
        "title": "IEC 62660-1: Secondary lithium-ion cells — Performance testing",
        "url": "https://www.iec.ch/",
    },
    "battery_ce": {
        "title": "BIPM SI Brochure — Electric charge and derived units (Ah / C)",
        "url": "https://www.bipm.org/en/publications/si-brochure",
    },
    "tga_astm": {
        "title": "ASTM E1131: Standard Test Method for Compositional Analysis by Thermogravimetry",
        "url": "https://www.astm.org/e1131-20.html",
    },
    "dsc_astm": {
        "title": "ASTM E1356: Standard Test Method for Assignment of the Glass Transition Temperatures by DSC",
        "url": "https://www.astm.org/e1356-23.html",
    },
}

TASK_BOUNDARIES: dict[str, dict[str, Any]] = {
    "mechanics": {
        "applicability_scope": (
            "单试样单调拉伸工程应力—应变曲线（已明确应变单位 fraction/% 与应力单位 Pa/kPa/MPa/GPa）。",
            "具备明确弹性拟合区间（至少 3 个有效测量点）与正偏移应变定义（如 0.2% 屈服偏移）。",
        ),
        "out_of_scope_cases": (
            "循环加载/卸载滞回曲线未先分段时不可直接按单调拉伸协议拟合模量。",
            "未提供原截面积或标距的原始载荷—位移数据不可直接冒充工程应力—应变。",
            "未确认试样断裂依据时不可将曲线末点自动报告为断裂延伸率。",
        ),
        "known_limitations": (
            "不同弹性选段可能产生显著模量差异，较高 R² 本身不证明测量链或引伸计校准正确。",
            "协议默认计算工程应力/应变，不自动执行真应力—真应变或颈缩后的本构反演。",
            "单试样采样点不构成独立试样重复；批次对比须使用试样级特征汇总。",
        ),
    },
    "spectra": {
        "applicability_scope": (
            "单调递增坐标轴（nm、cm^-1、eV、Hz）上的拉曼、红外吸光度或光致发光正峰光谱。",
            "显式声明基线策略（none/linear）与信号单位下的正突出度阈值。",
        ),
        "out_of_scope_cases": (
            "透射率（transmittance）谱线的吸收谷不可直接使用正峰提取，需先转换或选用谷检测。",
            "未提供激发波长时不可将原始波长直接换算为拉曼位移。",
            "不同曝光时间或未做参考校正的光谱不可直接比较绝对峰强。",
        ),
        "known_limitations": (
            "候选峰位与面积为描述性信号特征，不构成已验证的化学键或振动模式归属。",
            "端点线性背景对宽荧光包络存在偏差，严重重叠峰需额外分峰拟合与残差核验。",
        ),
    },
    "xrd": {
        "applicability_scope": (
            "0–180° 范围内严格递增的 2θ（deg）粉末 X 射线衍射一维扫描谱。",
            "用于背景评估、候选衍射峰提取、表观峰宽（FWHM）与面积统计。",
        ),
        "out_of_scope_cases": (
            "缺少已知辐射波长（如 Cu Kα）时不可计算晶面间距 d 或执行 Scherrer 晶粒尺寸估计。",
            "无标准参考峰表/CIF 理论谱对照时，严禁直接输出确定性物相鉴定结论。",
            "非 2θ 坐标（如 q 空间、d 间距或弧度 rad）不可直接进入角度协议。",
        ),
        "known_limitations": (
            "经验峰形拟合与候选峰排序不替代全谱 Rietveld 结构精修。",
            "表观峰宽包含仪器展宽贡献，未扣除标准样品仪器展宽前不可宣称真实微晶尺寸。",
        ),
    },
    "battery": {
        "applicability_scope": (
            "带明确 cell_id、正整数 cycle 及容量单位（Ah/mAh）或带 phase（charge/discharge/rest）"
            "标记的时间—电流充放电曲线。",
            "用于单电芯容量积分、同电芯基准循环保持率（retention_pct）与配对库仑效率计算。",
        ),
        "out_of_scope_cases": (
            "仅有单次循环的数据不可外推长循环寿命保持率或衰减拐点。",
            "不同倍率（C-rate）、温度或截止电压混排且未分组时，不可直接横向比较循环衰减速率。",
            "充电与放电未按先充后放顺序配对时，不可报告有效配对库仑效率。",
        ),
        "known_limitations": (
            "当前确定性节点聚焦电化学循环容量与保持率统计，不含 dQ/dV 微分容量峰归属或 EIS 等效电路拟合。",
            "跨电芯归一化被禁止，每颗电芯均以自身基准循环计算保持率；异常循环保留原因标记而不静默丢弃。",
        ),
    },
    "thermal": {
        "applicability_scope": (
            "单调升温或明确分段的热重分析（TGA）与差示扫描量热（DSC）曲线，具备明确温度单位（°C/K）与质量/热流单位。",
            "用于失重台阶、DTG 速率峰及吸/放热特征峰的描述性提取与对比。",
        ),
        "out_of_scope_cases": (
            "升降温循环未拆分为单调温区前，不可直接执行一阶导数（DTG）或热流峰积分。",
            "缺少升温速率、吹扫气氛（N2/空气）及样品质量记录时，不可直接进行动力学活化能反演或比焓定标。",
            "仪器基线漂移未提供空白坩埚参比时，不可将绝对热流值解释为标准相变焓。",
        ),
        "known_limitations": (
            "特征温度（onset/peak）高度依赖升温速率、样品量与基线切线选取，仅在相同测试条件下可比。",
            "描述性热效应峰不直接证明分解产物化学组成，需联用质谱/红外（TG-IR/MS）等独立证据。",
        ),
    },
}

_EXTENDED_NOTES: dict[str, list[tuple[str, str, str, str, str, str]]] = {
    "battery": [
        (
            "schema",
            "电芯标识与循环编号完整性",
            "明确每条记录对应的 cell_id 与正整数 cycle 编号。",
            "禁止跨电芯混合归一化；同一电芯同一循环在汇总模式下不可存在重复行。",
            "materials.battery_cycles",
            "battery_iec",
        ),
        (
            "units",
            "容量、电流与时间单位契约",
            "显式声明容量单位（Ah/mAh）或原始曲线的时间、电流与放电符号约定。",
            "未声明充放电电流符号约定前，不可对时间—电流曲线执行梯形积分。",
            "materials.battery_cycles",
            "battery_ce",
        ),
        (
            "phases",
            "充放电工步分段与单调时间",
            "按 charge/discharge/rest 连续工步分段，核验段内时间严格递增。",
            "时间回退、工步符号矛盾或采样点少于 2 的段必须标记失败并保留原因。",
            "materials.battery_cycles",
            "battery_iec",
        ),
        (
            "baseline",
            "同电芯基准循环与保持率",
            "以指定基准循环（或首有效循环）计算单电芯容量保持率。",
            "单循环数据不可用于评估循环衰减趋势；基准循环无效时保持率须置空。",
            "materials.battery_cycles",
            "battery_iec",
        ),
        (
            "efficiency",
            "配对库仑效率条件",
            "在同循环先充后放且充放电容量均有效正值时计算库仑效率。",
            "存在残缺工步或充放电顺序颠倒时，不可静默输出库仑效率。",
            "materials.battery_cycles",
            "battery_iec",
        ),
        (
            "conditions",
            "倍率、温度与独立电芯统计",
            "比较不同工艺或电解液配方时，按独立电芯汇总并核对倍率与温控一致。",
            "同一电芯的多周循环为纵向重复测量，不增加独立电芯样本量。",
            "ContrastStudy",
            "battery_iec",
        ),
    ],
    "thermal": [
        (
            "ramp",
            "温区单调性与升降温分段",
            "核验温度轴单位（°C/K）及分析段内的严格单调性。",
            "包含降温或恒温平台的原始曲线须先按温程分段后再求导或寻峰。",
            "materials.thermal",
            "tga_astm",
        ),
        (
            "atmosphere",
            "升温速率与吹扫气氛前提",
            "记录升温速率（K/min）、吹扫气氛与样品初始质量。",
            "气氛或升温速率不一致时，特征失重/相变温度不可直接横向比较。",
            "materials.thermal",
            "tga_astm",
        ),
        (
            "baseline",
            "浮力效应与空白基线校正",
            "保留原始热流/质量曲线，明确是否经过空白坩埚基线扣除。",
            "未扣除仪器基线漂移时，峰面积仅作相对参考，不作为绝对标准相变焓。",
            "materials.thermal",
            "dsc_astm",
        ),
        (
            "transitions",
            "玻璃化转变与熔融/分解峰区分",
            "区分台阶型转变（Tg/失重台阶）与峰型事件（熔融/结晶/DTG 峰）。",
            "正峰提取不适用于直接识别台阶型 Tg 拐点，需核对信号与导数形态。",
            "materials.thermal",
            "dsc_astm",
        ),
        (
            "noise",
            "微分（DTG）噪声放大控制",
            "对含噪 TGA 曲线求导前评估采样间隔与平滑窗口对峰位偏移的影响。",
            "过度平滑会展宽并偏移分解峰温，须对比处理前后曲线。",
            "materials.thermal",
            "smooth",
        ),
        (
            "replicates",
            "样品装填与独立平行测试",
            "按独立试样汇总起始温度、峰值温度与残炭率，标注装样量差异。",
            "单次测试的局部波动不代表材料批次统计显著差异。",
            "ContrastStudy",
            "tga_astm",
        ),
    ],
}


def extended_task_catalog() -> list[dict[str, Any]]:
    """Return all 5 typical materials tasks (30 method cards) with explicit boundaries."""
    base_tasks = task_catalog()
    enriched: list[dict[str, Any]] = []
    for task in base_tasks:
        boundary = TASK_BOUNDARIES[task["id"]]
        enriched.append(
            {
                **deepcopy(task),
                "protocol_compiler_ready": True,
                "applicability_scope": list(boundary["applicability_scope"]),
                "out_of_scope_cases": list(boundary["out_of_scope_cases"]),
                "known_limitations": list(boundary["known_limitations"]),
            }
        )

    titles = {"battery": "锂电池充放电与循环衰减", "thermal": "TG/DSC 热分析"}
    operations = {"battery": "materials.battery_cycles", "thermal": "materials.thermal"}
    for task_id, notes in _EXTENDED_NOTES.items():
        boundary = TASK_BOUNDARIES[task_id]
        enriched.append(
            {
                "id": task_id,
                "title": titles[task_id],
                "version": VERSION,
                "operation": operations[task_id],
                "protocol_compiler_ready": True,
                "applicability_scope": list(boundary["applicability_scope"]),
                "out_of_scope_cases": list(boundary["out_of_scope_cases"]),
                "known_limitations": list(boundary["known_limitations"]),
                "cards": [
                    {
                        "id": f"{task_id}.{key}",
                        "title": title,
                        "objective": objective,
                        "conditions": conditions,
                        "operation": operation,
                        "version": VERSION,
                        "source": deepcopy(EXTENDED_SOURCES[source]),
                    }
                    for key, title, objective, conditions, operation, source in notes
                ],
            }
        )
    return enriched


def search_domain_method_cards(
    query: str = "",
    *,
    task: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Retrieve structured method cards and boundaries across all 5 typical material tasks."""
    import re

    tokens = {
        tok
        for tok in re.findall(r"[a-z0-9_.-]+|[\u4e00-\u9fff]+", str(query or "").lower())
        if len(tok) >= 2
    }
    task_filter = str(task or "").strip().lower() or None
    scored: list[tuple[int, dict[str, Any]]] = []
    boundaries: dict[str, Any] = {}

    for entry in extended_task_catalog():
        tid = entry["id"]
        if task_filter and tid != task_filter:
            continue
        boundaries[tid] = {
            "title": entry["title"],
            "operation": entry["operation"],
            "applicability_scope": list(entry["applicability_scope"]),
            "out_of_scope_cases": list(entry["out_of_scope_cases"]),
            "known_limitations": list(entry["known_limitations"]),
        }
        for card in entry["cards"]:
            haystack = " ".join(
                [
                    tid,
                    entry["title"],
                    card["id"],
                    card["title"],
                    card["objective"],
                    card["conditions"],
                    card["operation"],
                ]
            ).lower()
            score = sum(2 if tok in card["title"].lower() else 1 for tok in tokens if tok in haystack)
            if task_filter == tid:
                score += 3
            if not tokens or score > 0:
                scored.append(
                    (
                        score,
                        {
                            "card_id": f"K:task.{card['id']}",
                            "task": tid,
                            "task_title": entry["title"],
                            "title": card["title"],
                            "objective": card["objective"],
                            "conditions": card["conditions"],
                            "operation": card["operation"],
                            "source": card.get("source", {}),
                            "applicability_scope": list(entry["applicability_scope"]),
                            "out_of_scope_cases": list(entry["out_of_scope_cases"]),
                            "known_limitations": list(entry["known_limitations"]),
                        },
                    )
                )

    scored.sort(key=lambda item: (-item[0], item[1]["card_id"]))
    return {
        "cards": [item[1] for item in scored[: max(1, min(int(top_k), 15))]],
        "task_boundaries": boundaries,
    }

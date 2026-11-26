"""Runtime physical & methodological GUARD checks for materials workflows.

Lowers method-card applicability premises into executable runtime checks so
out-of-scope or physically invalid inputs are caught during workflow execution
and surfaced explicitly in generated reports and replay bundles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from materials_quality.assets.catalog_bridge import cached_default_asset_graph


@dataclass(frozen=True)
class GuardFinding:
    """Single runtime guard finding."""

    code: str
    severity: str  # "block" | "warn"
    message: str
    recommendation: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "recommendation": self.recommendation,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class GuardReport:
    """Aggregated result of runtime GUARD evaluation."""

    task: str
    status: str  # "pass" | "warn" | "block"
    findings: tuple[GuardFinding, ...] = ()
    not_verified: tuple[str, ...] = ()
    applicability_scope: tuple[str, ...] = ()
    out_of_scope_cases: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status != "block"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "status": self.status,
            "passed": self.passed,
            "findings": [item.to_dict() for item in self.findings],
            "not_verified": list(self.not_verified),
            "applicability_scope": list(self.applicability_scope),
            "out_of_scope_cases": list(self.out_of_scope_cases),
            "known_limitations": list(self.known_limitations),
        }


def _task_boundaries(task: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    graph = cached_default_asset_graph()
    node = graph.get(f"W:protocol.{task}")
    if node is None:
        return (), (), ()
    return node.applicability_scope, node.out_of_scope_cases, node.known_limitations


def _numeric_pair(table: pd.DataFrame, x_col: str, y_col: str) -> tuple[np.ndarray, np.ndarray]:
    if x_col not in table.columns or y_col not in table.columns:
        missing = [c for c in (x_col, y_col) if c not in table.columns]
        raise ValueError(f"GUARD check missing required column(s): {missing}")
    x = pd.to_numeric(table[x_col], errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(table[y_col], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def guard_mechanics_curve(
    table: pd.DataFrame,
    *,
    strain_col: str = "strain",
    stress_col: str = "stress",
    fit_range: tuple[float, float] | None = None,
    min_r2: float = 0.95,
    sort: bool = False,
) -> GuardReport:
    """Validate elastic-region monotonicity, positive modulus, and linear-fit R²."""
    scope, out_of_scope, limitations = _task_boundaries("mechanics")
    findings: list[GuardFinding] = []
    not_verified: list[str] = []

    x, y = _numeric_pair(table, strain_col, stress_col)
    if sort and len(x) >= 2:
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
    if len(x) < 3:
        findings.append(
            GuardFinding(
                code="MECHANICS_INSUFFICIENT_POINTS",
                severity="block",
                message=f"有效应变-应力数据点仅 {len(x)} 个，不足以可靠拟合杨氏模量。",
                recommendation="请核实导入范围与列名，确保至少包含 3 个以上有效数据点。",
                evidence={"valid_points": int(len(x))},
            )
        )
    else:
        if fit_range is not None:
            lo, hi = float(fit_range[0]), float(fit_range[1])
            seg_mask = (x >= lo) & (x <= hi)
            sx, sy = x[seg_mask], y[seg_mask]
        else:
            not_verified.append("未显式指定弹性拟合区间 fit_range，仅对前 25% 应变段执行启发式线性检查。")
            cutoff = max(3, len(x) // 4)
            sx, sy = x[:cutoff], y[:cutoff]

        if len(sx) < 3:
            findings.append(
                GuardFinding(
                    code="MECHANICS_FIT_RANGE_TOO_FEW_POINTS",
                    severity="block",
                    message=f"弹性拟合区间内仅 {len(sx)} 个点，无法评估线性度。",
                    recommendation="请调整 fit_range 以覆盖真实线弹性加载段。",
                    evidence={"segment_points": int(len(sx)), "fit_range": list(fit_range) if fit_range else None},
                )
            )
        else:
            diffs = np.diff(sx)
            if np.any(diffs < -1e-12):
                findings.append(
                    GuardFinding(
                        code="MECHANICS_NON_MONOTONIC_ELASTIC_SEGMENT",
                        severity="block",
                        message="弹性拟合段内应变非单调递增（疑似循环加卸载或卸载回弹曲线），禁止直接做单调拉伸模量拟合。",
                        recommendation="请先按加载阶段切分单调加载支路，或改用循环滞回分析方法。",
                        evidence={"negative_step_count": int(np.sum(diffs < -1e-12))},
                    )
                )
            if np.std(sx) > 0 and np.std(sy) > 0:
                slope, intercept = np.polyfit(sx, sy, 1)
                pred = slope * sx + intercept
                ss_res = float(np.sum((sy - pred) ** 2))
                ss_tot = float(np.sum((sy - np.mean(sy)) ** 2))
                r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
                if slope <= 0:
                    findings.append(
                        GuardFinding(
                            code="MECHANICS_NON_POSITIVE_MODULUS",
                            severity="block",
                            message=f"弹性拟合斜率为 {slope:.4g}（非正值），违背单轴拉伸正模量物理前提。",
                            recommendation="请检查应力/应变符号、列映射或是否误选了卸载段。",
                            evidence={"slope": float(slope), "r2": float(r2)},
                        )
                    )
                elif len(x) >= 5 and r2 < min_r2:
                    findings.append(
                        GuardFinding(
                            code="MECHANICS_LOW_ELASTIC_R2",
                            severity="block",
                            message=f"弹性段线性拟合 R² = {r2:.4f}，低于阈值 {min_r2:.2f}，可能混入屈服段或非线性趾部。",
                            recommendation="请人工复核应力-应变曲线并收缩 fit_range 至严格线性区间。",
                            evidence={"slope": float(slope), "r2": float(r2), "min_r2": float(min_r2)},
                        )
                    )

    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "pass")
    return GuardReport(
        task="mechanics",
        status=status,
        findings=tuple(findings),
        not_verified=tuple(not_verified),
        applicability_scope=scope,
        out_of_scope_cases=out_of_scope,
        known_limitations=limitations,
    )


def guard_spectra_signal(
    table: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    mode: str = "absorbance",
) -> GuardReport:
    """Block positive-peak extraction on transmittance valleys or non-monotonic axes."""
    scope, out_of_scope, limitations = _task_boundaries("spectra")
    findings: list[GuardFinding] = []
    not_verified: list[str] = []

    x, y = _numeric_pair(table, x_col, y_col)
    if len(x) < 3:
        findings.append(
            GuardFinding(
                code="SPECTRA_INSUFFICIENT_POINTS",
                severity="block",
                message=f"有效光谱数据点仅 {len(x)} 个，不足以执行基线与寻峰分析。",
                recommendation="请核实导入文件格式与坐标列。",
                evidence={"valid_points": int(len(x))},
            )
        )
    else:
        diffs = np.diff(x)
        is_inc = bool(np.all(diffs > 0))
        is_dec = bool(np.all(diffs < 0))
        if not (is_inc or is_dec):
            findings.append(
                GuardFinding(
                    code="SPECTRA_NON_MONOTONIC_AXIS",
                    severity="block",
                    message="光谱横坐标存在重复或非单调跳变，可能混入了多条曲线或未分组谱图。",
                    recommendation="请先按样品/扫描编号分组或检查重复横坐标点，不可盲目排序拼接。",
                    evidence={"points": int(len(x))},
                )
            )

        mode_lower = str(mode or "").casefold()
        if mode_lower in {"transmittance", "t%", "%t"}:
            findings.append(
                GuardFinding(
                    code="SPECTRA_TRANSMITTANCE_POSITIVE_PEAK_BLOCKED",
                    severity="block",
                    message="透射率谱（Transmittance）吸收特征为向下谷值，禁止直接套用正向峰提取。",
                    recommendation="请先转换为吸光度 A = -log10(T) 或改用谷值检测流程。",
                    evidence={"declared_mode": mode},
                )
            )
        else:
            # Heuristic check: values concentrated near 90-100 with deep downward dips.
            p90 = float(np.percentile(y, 90))
            p50 = float(np.percentile(y, 50))
            p05 = float(np.percentile(y, 5))
            if 70.0 <= p90 <= 105.0 and p50 >= 80.0 and (p50 - p05) > 2.0 * max(1e-6, p90 - p50):
                findings.append(
                    GuardFinding(
                        code="SPECTRA_LIKELY_TRANSMITTANCE_VALLEY",
                        severity="block",
                        message="检测到基线位于 80~100 且特征向下凹陷（疑似透射率 %T 谱），已拦截正向峰提取。",
                        recommendation="请确认纵轴物理量；若为透射率请转换为吸光度后再做基线与寻峰。",
                        evidence={"p05": p05, "p50": p50, "p90": p90},
                    )
                )

    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "pass")
    return GuardReport(
        task="spectra",
        status=status,
        findings=tuple(findings),
        not_verified=tuple(not_verified),
        applicability_scope=scope,
        out_of_scope_cases=out_of_scope,
        known_limitations=limitations,
    )


def guard_xrd_phase_claim(
    *,
    has_reference_pattern: bool = False,
    claims_phase_id: bool = False,
    two_theta_values: np.ndarray | list[float] | None = None,
) -> GuardReport:
    """Prevent unverified XRD phase identification when no reference pattern is matched."""
    scope, out_of_scope, limitations = _task_boundaries("xrd")
    findings: list[GuardFinding] = []
    not_verified: list[str] = []

    if claims_phase_id and not has_reference_pattern:
        findings.append(
            GuardFinding(
                code="XRD_PHASE_ID_WITHOUT_REFERENCE",
                severity="block",
                message="当前流程未接入标准参考衍射谱（CIF / ICDD PDF），禁止直接输出确定性物相鉴定结论。",
                recommendation="仅可报告 2θ 峰位、d 间距与相对强度；如需物相归属请先接入标准 CIF/PDF 参考谱比对。",
                evidence={"has_reference_pattern": False, "claims_phase_id": True},
            )
        )
    elif not has_reference_pattern:
        not_verified.append("未关联标准参考谱（CIF/PDF），本次 XRD 分析仅限峰位与 d 间距提取，不含物相定性鉴定。")

    if two_theta_values is not None:
        arr = np.asarray(two_theta_values, dtype=float)
        arr = arr[np.isfinite(arr)]
        if len(arr) >= 2 and (float(np.min(arr)) < 0.0 or float(np.max(arr)) > 180.0):
            findings.append(
                GuardFinding(
                    code="XRD_ANGLE_OUT_OF_PHYSICAL_RANGE",
                    severity="block",
                    message=f"2θ 角度范围 [{float(np.min(arr)):.2f}, {float(np.max(arr)):.2f}] 超出物理有效区间 [0, 180]°。",
                    recommendation="请核实横坐标是否为 2θ（度）而非 d 间距或 Q 矢量。",
                    evidence={"min_two_theta": float(np.min(arr)), "max_two_theta": float(np.max(arr))},
                )
            )

    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "pass")
    return GuardReport(
        task="xrd",
        status=status,
        findings=tuple(findings),
        not_verified=tuple(not_verified),
        applicability_scope=scope,
        out_of_scope_cases=out_of_scope,
        known_limitations=limitations,
    )


def guard_battery_cycles(
    table: pd.DataFrame,
    *,
    cycle_col: str = "cycle",
    c_rate_col: str | None = None,
    requested_metric: str = "retention",
) -> GuardReport:
    """Block cycle-life retention extrapolation on single-cycle or ungrouped multi-rate data."""
    scope, out_of_scope, limitations = _task_boundaries("battery")
    findings: list[GuardFinding] = []
    not_verified: list[str] = []

    if cycle_col not in table.columns:
        findings.append(
            GuardFinding(
                code="BATTERY_MISSING_CYCLE_COLUMN",
                severity="block",
                message=f"缺少循环编号列 {cycle_col!r}，无法按循环计算容量保持率与库仑效率。",
                recommendation="请确认循环编号列名，或先按充放电 phase 分段生成 cycle 列。",
                evidence={"missing_column": cycle_col},
            )
        )
    else:
        cycles = pd.to_numeric(table[cycle_col], errors="coerce").dropna().unique()
        if requested_metric in {"retention", "cycle_life", "fade_rate"} and len(cycles) < 2:
            findings.append(
                GuardFinding(
                    code="BATTERY_SINGLE_CYCLE_RETENTION_BLOCKED",
                    severity="block",
                    message=f"数据仅包含 {len(cycles)} 个有效循环，禁止推算长循环寿命保持率或衰减速率。",
                    recommendation="单循环数据仅可报告当次充放电容量与单周库仑效率，不得外推循环寿命。",
                    evidence={"unique_cycles": int(len(cycles))},
                )
            )
        if c_rate_col and c_rate_col in table.columns:
            rates = table[c_rate_col].dropna().unique()
            if len(rates) > 1:
                findings.append(
                    GuardFinding(
                        code="BATTERY_MIXED_CRATE_UNGROUPED",
                        severity="warn",
                        message=f"检测到 {len(rates)} 种不同倍率（{c_rate_col}）混排，直接汇总衰减率可能失真。",
                        recommendation="请先按倍率或温度条件分组后再比较容量保持率。",
                        evidence={"distinct_c_rates": int(len(rates))},
                    )
                )
        else:
            not_verified.append("未提供倍率（C-rate）或测试温度列，假设同一电芯在一致工况下循环。")

    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "pass")
    return GuardReport(
        task="battery",
        status=status,
        findings=tuple(findings),
        not_verified=tuple(not_verified),
        applicability_scope=scope,
        out_of_scope_cases=out_of_scope,
        known_limitations=limitations,
    )


def guard_thermal_curve(
    table: pd.DataFrame,
    *,
    temp_col: str = "temperature_C",
    signal_col: str = "mass_pct",
    heating_rate: float | None = None,
    atmosphere: str | None = None,
) -> GuardReport:
    """Validate single-segment TG/DSC temperature monotonicity and test metadata."""
    scope, out_of_scope, limitations = _task_boundaries("thermal")
    findings: list[GuardFinding] = []
    not_verified: list[str] = []

    x, _ = _numeric_pair(table, temp_col, signal_col)
    if len(x) < 5:
        findings.append(
            GuardFinding(
                code="THERMAL_INSUFFICIENT_POINTS",
                severity="block",
                message=f"有效热分析数据点仅 {len(x)} 个，不足以计算失重台阶或 DTG 峰。",
                recommendation="请核实温度与质量/热流列配置。",
                evidence={"valid_points": int(len(x))},
            )
        )
    else:
        diffs = np.diff(x)
        if not (np.all(diffs >= -1e-9) or np.all(diffs <= 1e-9)):
            findings.append(
                GuardFinding(
                    code="THERMAL_NON_MONOTONIC_TEMPERATURE",
                    severity="block",
                    message="温度轴同时包含升温与降温回扫段，禁止直接作为单一升温段计算 DTG 或 Tg。",
                    recommendation="请先按升降温段（segment）拆分后再分别分析。",
                    evidence={"points": int(len(x))},
                )
            )

    if heating_rate is None:
        not_verified.append("未声明升温速率（K/min），不同升温速率下的 Tg 与分解峰温不可直接横向对比。")
    if not atmosphere:
        not_verified.append("未声明吹扫气氛（如 N2 / 空气 / Ar），氧化与热解机理待实验记录确认。")

    status = "block" if any(f.severity == "block" for f in findings) else ("warn" if findings else "pass")
    return GuardReport(
        task="thermal",
        status=status,
        findings=tuple(findings),
        not_verified=tuple(not_verified),
        applicability_scope=scope,
        out_of_scope_cases=out_of_scope,
        known_limitations=limitations,
    )


def evaluate_runtime_guards(
    task: str,
    table: pd.DataFrame | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> GuardReport:
    """Unified dispatcher for runtime GUARD checks across the 5 typical material tasks."""
    cfg = dict(config or {})
    if task == "mechanics":
        if table is None:
            raise ValueError("mechanics GUARD requires a DataFrame")
        return guard_mechanics_curve(
            table,
            strain_col=str(cfg.get("strain_col", "strain")),
            stress_col=str(cfg.get("stress_col", "stress")),
            fit_range=tuple(cfg["fit_range"]) if cfg.get("fit_range") is not None else None,
            min_r2=float(cfg.get("min_r2", 0.95)),
            sort=bool(cfg.get("sort", False)),
        )
    if task == "spectra":
        if table is None:
            raise ValueError("spectra GUARD requires a DataFrame")
        return guard_spectra_signal(
            table,
            x_col=str(cfg.get("x_col", "wavenumber")),
            y_col=str(cfg.get("y_col", "intensity")),
            mode=str(cfg.get("mode", "absorbance")),
        )
    if task == "xrd":
        two_theta = None
        x_col = str(cfg.get("x_col", "two_theta"))
        if table is not None and x_col in table.columns:
            two_theta = pd.to_numeric(table[x_col], errors="coerce").to_numpy(dtype=float)
        return guard_xrd_phase_claim(
            has_reference_pattern=bool(cfg.get("has_reference_pattern", False)),
            claims_phase_id=bool(cfg.get("claims_phase_id", False)),
            two_theta_values=two_theta,
        )
    if task == "battery":
        if table is None:
            raise ValueError("battery GUARD requires a DataFrame")
        return guard_battery_cycles(
            table,
            cycle_col=str(cfg.get("cycle_col", "cycle")),
            c_rate_col=cfg.get("c_rate_col"),
            requested_metric=str(cfg.get("requested_metric", "retention")),
        )
    if task == "thermal":
        if table is None:
            raise ValueError("thermal GUARD requires a DataFrame")
        return guard_thermal_curve(
            table,
            temp_col=str(cfg.get("temp_col", "temperature_C")),
            signal_col=str(cfg.get("signal_col", "mass_pct")),
            heating_rate=cfg.get("heating_rate"),
            atmosphere=cfg.get("atmosphere"),
        )
    raise ValueError(f"Unsupported GUARD task: {task!r}")


def build_boundary_disclosure(
    task: str | None = None,
    *,
    guard_report: GuardReport | dict[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a uniform Scope & Limitations disclosure payload for reports & bundles."""
    scope: list[str] = []
    out_of_scope: list[str] = []
    limitations: list[str] = []
    standards_refs: list[dict[str, str]] = []
    not_verified: list[str] = []
    guard_findings: list[dict[str, Any]] = []
    guard_status = "not_evaluated"

    if task:
        graph = cached_default_asset_graph()
        node = graph.get(f"W:protocol.{task}")
        if node is not None:
            scope.extend(node.applicability_scope)
            out_of_scope.extend(node.out_of_scope_cases)
            limitations.extend(node.known_limitations)
            standards_refs.extend(dict(ref) for ref in node.standards_refs)

    if isinstance(guard_report, GuardReport):
        guard_dict = guard_report.to_dict()
    elif isinstance(guard_report, dict):
        guard_dict = dict(guard_report)
    else:
        guard_dict = None

    if guard_dict is not None:
        guard_status = str(guard_dict.get("status", "unknown"))
        guard_findings.extend(guard_dict.get("findings") or [])
        for item in guard_dict.get("not_verified") or []:
            if item not in not_verified:
                not_verified.append(str(item))

    if isinstance(assessment, dict):
        for check in assessment.get("checks") or []:
            if isinstance(check, dict) and check.get("status") in {"not_verified", "need_info", "change_method"}:
                label = str(check.get("title") or check.get("id") or "前提检查")
                reason = str(check.get("reason") or check.get("message") or check.get("status"))
                entry = f"{label}：{reason}"
                if entry not in not_verified:
                    not_verified.append(entry)

    return {
        "task": task or "general",
        "guard_status": guard_status,
        "applicability_scope": scope,
        "out_of_scope_cases": out_of_scope,
        "not_verified_conditions": not_verified,
        "guard_findings": guard_findings,
        "known_limitations": limitations,
        "standards_refs": standards_refs,
    }

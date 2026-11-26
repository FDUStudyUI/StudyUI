"""Optional PyBaMM-backed single-cell electrochemical discharge simulation plugin.

Explicitly declares parameter-set provenance, model fidelity (SPM/SPMe/DFN),
and temperature/C-rate applicability boundaries. Degrades gracefully when
``pybamm`` is not installed.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from typing import Any

import numpy as np

INSTALL_HINT = "pip install 'studyui-materials-quality[compute]'"
SUPPORTED_MODELS = ("SPM", "SPMe", "DFN")
DEFAULT_APPLICABILITY_SCOPE = (
    "适用于单电芯（single-cell）理想均质电极在温和倍率与常温稳态假设下的放电曲线基线仿真（SPM/SPMe/DFN）。",
)
BASE_LIMITATIONS = (
    "单电芯模型不包含电芯模组热耦合、极耳欧姆压降空间分布、长期析锂/副反应老化及非标电解液配方差异；"
    "参数集仅代表其原始文献电芯体系，迁移至其他材料体系前须重新标定。",
)


def pybamm_available() -> bool:
    """Return True when ``pybamm`` can be imported in the active environment."""
    return importlib.util.find_spec("pybamm") is not None


def evaluate_operating_boundaries(
    *,
    model_name: str,
    c_rate: float,
    ambient_temp_C: float,
) -> list[str]:
    """Return physics applicability warnings for the requested operating point."""
    warnings: list[str] = []
    if model_name == "SPM" and c_rate > 2.0:
        warnings.append(
            f"当前倍率 {c_rate}C 高于 2C，SPM 模型忽略电解液浓度极化误差显著，建议切换至 SPMe 或 DFN。"
        )
    if c_rate > 5.0:
        warnings.append(f"极高倍率 {c_rate}C 下单电芯等温假设易失效，需结合热耦合与析锂边界核查。")
    if ambient_temp_C < 10.0 or ambient_temp_C > 45.0:
        warnings.append(
            f"环境温度 {ambient_temp_C} °C 偏离默认参数集标定区间"
            f"（10–45 °C），低温内阻与高温副反应可能显著偏离。"
        )
    return warnings


def _summarize_curve(
    time_s: list[float],
    voltage_V: list[float],
    current_A: list[float],
) -> dict[str, float]:
    t = np.asarray(time_s, dtype=float)
    v = np.asarray(voltage_V, dtype=float)
    i = np.asarray(current_A, dtype=float)
    if t.size < 2 or v.size != t.size or i.size != t.size:
        raise ValueError("Simulation curves (time_s, voltage_V, current_A) must have equal length >= 2")
    if not (np.isfinite(t).all() and np.isfinite(v).all() and np.isfinite(i).all()):
        raise ValueError("Simulation curves must contain only finite numerical values")
    if np.any(np.diff(t) < 0):
        raise ValueError("Simulation time_s must be non-decreasing")
    dt_h = np.diff(t) / 3600.0
    avg_i = 0.5 * (i[:-1] + i[1:])
    avg_p = 0.5 * (i[:-1] * v[:-1] + i[1:] * v[1:])
    capacity_ah = float(np.sum(np.abs(avg_i) * dt_h))
    energy_wh = float(np.sum(np.abs(avg_p) * dt_h))
    return {
        "duration_s": round(float(t[-1] - t[0]), 3),
        "initial_voltage_V": round(float(v[0]), 4),
        "final_voltage_V": round(float(v[-1]), 4),
        "discharge_capacity_Ah": round(capacity_ah, 5),
        "discharge_energy_Wh": round(energy_wh, 5),
    }


def simulate_single_cell_discharge(
    *,
    model_name: str = "SPM",
    parameter_set: str = "Chen2020",
    c_rate: float = 1.0,
    ambient_temp_C: float = 25.0,
    cutoff_voltage_V: float = 2.5,
    t_points: int = 100,
    backend: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a single-cell constant-C-rate discharge simulation via PyBaMM.

    Supports dependency-injected ``backend`` for deterministic contract testing
    when ``pybamm`` is not installed.
    """
    if model_name not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported model_name {model_name!r}; expected one of {SUPPORTED_MODELS}")
    if c_rate <= 0.0:
        raise ValueError("c_rate must be positive")
    if t_points < 2:
        raise ValueError("t_points must be >= 2")

    boundary_warnings = evaluate_operating_boundaries(
        model_name=model_name,
        c_rate=c_rate,
        ambient_temp_C=ambient_temp_C,
    )
    provenance = {
        "model_name": model_name,
        "parameter_set": parameter_set,
        "c_rate": float(c_rate),
        "ambient_temp_C": float(ambient_temp_C),
        "cutoff_voltage_V": float(cutoff_voltage_V),
    }

    if backend is not None:
        raw = backend(
            model_name=model_name,
            parameter_set=parameter_set,
            c_rate=float(c_rate),
            ambient_temp_C=float(ambient_temp_C),
            cutoff_voltage_V=float(cutoff_voltage_V),
            t_points=t_points,
        )
        time_s = [float(x) for x in raw["time_s"]]
        voltage_V = [float(x) for x in raw["voltage_V"]]
        current_A = [float(x) for x in raw["current_A"]]
        summary = _summarize_curve(time_s, voltage_V, current_A)
        return {
            "status": "ok",
            "plugin": "pybamm_battery",
            "backend": "injected_backend",
            "provenance": provenance,
            "summary": summary,
            "series": {
                "time_s": time_s,
                "voltage_V": voltage_V,
                "current_A": current_A,
            },
            "boundary_warnings": boundary_warnings,
            "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
            "known_limitations": list(BASE_LIMITATIONS),
        }

    if not pybamm_available():
        return {
            "status": "unavailable",
            "plugin": "pybamm_battery",
            "missing_dependency": "pybamm",
            "install_hint": INSTALL_HINT,
            "provenance": provenance,
            "summary": None,
            "series": None,
            "boundary_warnings": boundary_warnings,
            "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
            "known_limitations": [
                *BASE_LIMITATIONS,
                "当前环境未安装可选求解器 pybamm，已优雅降级并返回安装提示，不执行电化学仿真。",
            ],
        }

    import pybamm  # type: ignore[import-not-found]

    model_cls = getattr(pybamm.lithium_ion, model_name)
    model = model_cls()
    param = pybamm.ParameterValues(parameter_set)
    param["Ambient temperature [K]"] = float(ambient_temp_C) + 273.15
    experiment = pybamm.Experiment([f"Discharge at {c_rate}C until {cutoff_voltage_V} V"])
    sim = pybamm.Simulation(model, parameter_values=param, experiment=experiment)
    solution = sim.solve()

    t_raw = np.asarray(solution["Time [s]"].entries, dtype=float)
    v_raw = np.asarray(solution["Voltage [V]"].entries, dtype=float)
    i_raw = np.asarray(solution["Current [A]"].entries, dtype=float)
    if t_raw.size > t_points:
        idx = np.linspace(0, t_raw.size - 1, t_points, dtype=int)
        t_raw, v_raw, i_raw = t_raw[idx], v_raw[idx], i_raw[idx]

    time_s = [round(float(x), 4) for x in t_raw]
    voltage_V = [round(float(x), 5) for x in v_raw]
    current_A = [round(float(x), 5) for x in i_raw]
    summary = _summarize_curve(time_s, voltage_V, current_A)
    return {
        "status": "ok",
        "plugin": "pybamm_battery",
        "backend": "pybamm",
        "provenance": provenance,
        "summary": summary,
        "series": {
            "time_s": time_s,
            "voltage_V": voltage_V,
            "current_A": current_A,
        },
        "boundary_warnings": boundary_warnings,
        "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
        "known_limitations": list(BASE_LIMITATIONS),
    }

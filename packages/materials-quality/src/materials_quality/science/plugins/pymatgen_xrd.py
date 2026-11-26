"""Optional pymatgen-backed XRD theoretical pattern and candidate peak matching plugin.

Explicitly scopes outputs to candidate phase screening and never replaces
Rietveld refinement. Degrades gracefully when ``pymatgen`` is not installed.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Sequence
from typing import Any

INSTALL_HINT = "pip install 'langflow-materials-quality[compute]'"
XRD_LIMITATION_NOTICE = (
    "仅作候选比对，不替代 Rietveld 精修；未考虑择优取向、仪器展宽、非晶背景及多相定量权重。"
)
DEFAULT_APPLICABILITY_SCOPE = (
    "适用于已知晶体结构（CIF）在常见实验室单色靶材（如 CuKa、CoKa、MoKa）下的理论粉晶衍射峰位初筛。",
)


def pymatgen_available() -> bool:
    """Return True when ``pymatgen`` can be imported in the active environment."""
    return importlib.util.find_spec("pymatgen") is not None


def _normalize_peak(raw: dict[str, Any]) -> dict[str, Any]:
    two_theta = float(raw.get("two_theta_deg", raw.get("two_theta", 0.0)))
    intensity = float(raw.get("intensity_rel", raw.get("intensity", 0.0)))
    d_spacing = raw.get("d_spacing_angstrom", raw.get("d_spacing"))
    hkls = raw.get("hkls", [])
    return {
        "two_theta_deg": round(two_theta, 4),
        "intensity_rel": round(intensity, 3),
        "d_spacing_angstrom": round(float(d_spacing), 5) if d_spacing is not None else None,
        "hkls": list(hkls) if isinstance(hkls, (list, tuple)) else [str(hkls)],
    }


def compute_theoretical_xrd_from_cif(
    cif_text: str,
    *,
    wavelength: str = "CuKa",
    two_theta_range: tuple[float, float] = (10.0, 90.0),
    min_intensity: float = 1.0,
    calculator: Callable[..., Sequence[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Compute theoretical powder XRD reflections from a CIF string.

    Supports dependency-injected ``calculator`` for deterministic contract testing
    when ``pymatgen`` is not installed.
    """
    if not isinstance(cif_text, str) or not cif_text.strip():
        raise ValueError("cif_text must be a non-empty CIF string")
    lo, hi = float(two_theta_range[0]), float(two_theta_range[1])
    if lo < 0.0 or hi > 180.0 or lo >= hi:
        raise ValueError(f"Invalid two_theta_range: {two_theta_range!r}")

    if calculator is not None:
        raw_peaks = calculator(
            cif_text=cif_text,
            wavelength=wavelength,
            two_theta_range=(lo, hi),
        )
        peaks = [
            _normalize_peak(item)
            for item in raw_peaks
            if float(item.get("intensity_rel", item.get("intensity", 0.0))) >= min_intensity
        ]
        peaks.sort(key=lambda item: item["two_theta_deg"])
        return {
            "status": "ok",
            "plugin": "pymatgen_xrd",
            "backend": "injected_calculator",
            "wavelength": wavelength,
            "two_theta_range": [lo, hi],
            "peak_count": len(peaks),
            "peaks": peaks,
            "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
            "known_limitations": [XRD_LIMITATION_NOTICE],
        }

    if not pymatgen_available():
        return {
            "status": "unavailable",
            "plugin": "pymatgen_xrd",
            "missing_dependency": "pymatgen",
            "install_hint": INSTALL_HINT,
            "wavelength": wavelength,
            "two_theta_range": [lo, hi],
            "peak_count": 0,
            "peaks": [],
            "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
            "known_limitations": [
                XRD_LIMITATION_NOTICE,
                "当前环境未安装可选求解器 pymatgen，已优雅降级并返回安装提示，不执行理论衍射计算。",
            ],
        }

    from pymatgen.analysis.diffraction.xrd import XRDCalculator  # type: ignore[import-not-found]
    from pymatgen.core import Structure  # type: ignore[import-not-found]

    structure = Structure.from_str(cif_text, fmt="cif")
    calc = XRDCalculator(wavelength=wavelength)
    pattern = calc.get_pattern(structure, two_theta_range=(lo, hi))
    peaks: list[dict[str, Any]] = []
    for x_val, y_val, hkls, d_val in zip(
        pattern.x,
        pattern.y,
        pattern.hkls,
        pattern.d_hkls,
        strict=False,
    ):
        if float(y_val) < min_intensity:
            continue
        formatted_hkls = [str(entry.get("hkl")) for entry in hkls if isinstance(entry, dict)]
        peaks.append(
            _normalize_peak(
                {
                    "two_theta_deg": float(x_val),
                    "intensity_rel": float(y_val),
                    "d_spacing_angstrom": float(d_val),
                    "hkls": formatted_hkls,
                }
            )
        )
    peaks.sort(key=lambda item: item["two_theta_deg"])
    return {
        "status": "ok",
        "plugin": "pymatgen_xrd",
        "backend": "pymatgen",
        "formula": structure.composition.reduced_formula,
        "wavelength": wavelength,
        "two_theta_range": [lo, hi],
        "peak_count": len(peaks),
        "peaks": peaks,
        "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
        "known_limitations": [XRD_LIMITATION_NOTICE],
    }


def match_measured_xrd_peaks(
    measured_peaks: Sequence[dict[str, Any]],
    theoretical_peaks: Sequence[dict[str, Any]],
    *,
    tol_deg: float = 0.35,
    min_rel_intensity: float = 5.0,
) -> dict[str, Any]:
    """Match measured XRD peaks against theoretical candidate peaks within ``tol_deg``."""
    if tol_deg <= 0.0:
        raise ValueError("tol_deg must be positive")

    norm_measured = [_normalize_peak(p) for p in measured_peaks]
    norm_theory = [
        _normalize_peak(p)
        for p in theoretical_peaks
        if float(p.get("intensity_rel", p.get("intensity", 0.0))) >= min_rel_intensity
    ]

    candidate_pairs: list[tuple[float, int, int]] = []
    for m_idx, m_peak in enumerate(norm_measured):
        for t_idx, t_peak in enumerate(norm_theory):
            delta = abs(m_peak["two_theta_deg"] - t_peak["two_theta_deg"])
            if delta <= tol_deg:
                candidate_pairs.append((delta, m_idx, t_idx))
    candidate_pairs.sort(key=lambda item: (item[0], item[1], item[2]))

    matched_measured_to_theory: dict[int, tuple[int, float]] = {}
    matched_theory_indices: set[int] = set()
    for delta, m_idx, t_idx in candidate_pairs:
        if m_idx in matched_measured_to_theory or t_idx in matched_theory_indices:
            continue
        matched_measured_to_theory[m_idx] = (t_idx, delta)
        matched_theory_indices.add(t_idx)

    matches: list[dict[str, Any]] = []
    unmatched_measured: list[dict[str, Any]] = []
    for m_idx, m_peak in enumerate(norm_measured):
        assigned = matched_measured_to_theory.get(m_idx)
        if assigned is not None:
            best_idx, best_delta = assigned
            t_peak = norm_theory[best_idx]
            matches.append(
                {
                    "measured_two_theta_deg": m_peak["two_theta_deg"],
                    "theoretical_two_theta_deg": t_peak["two_theta_deg"],
                    "delta_deg": round(m_peak["two_theta_deg"] - t_peak["two_theta_deg"], 4),
                    "abs_delta_deg": round(best_delta, 4),
                    "theoretical_intensity_rel": t_peak["intensity_rel"],
                    "hkls": t_peak["hkls"],
                }
            )
        else:
            unmatched_measured.append(m_peak)

    unmatched_theoretical = [
        t_peak for idx, t_peak in enumerate(norm_theory) if idx not in matched_theory_indices
    ]

    measured_cov = len(matches) / len(norm_measured) if norm_measured else 0.0
    theory_cov = len(matched_theory_indices) / len(norm_theory) if norm_theory else 0.0
    mean_abs_delta = (
        sum(item["abs_delta_deg"] for item in matches) / len(matches) if matches else None
    )
    max_abs_delta = max((item["abs_delta_deg"] for item in matches), default=None)

    if measured_cov + theory_cov > 0:
        f1 = 2.0 * measured_cov * theory_cov / (measured_cov + theory_cov)
        shift_penalty = (mean_abs_delta / tol_deg) * 0.2 if mean_abs_delta is not None else 0.0
        candidate_score = max(0.0, min(1.0, round(f1 * (1.0 - shift_penalty), 4)))
    else:
        candidate_score = 0.0

    return {
        "status": "ok",
        "plugin": "pymatgen_xrd",
        "tol_deg": tol_deg,
        "matched_count": len(matches),
        "measured_count": len(norm_measured),
        "theoretical_count": len(norm_theory),
        "measured_coverage": round(measured_cov, 4),
        "theoretical_coverage": round(theory_cov, 4),
        "mean_abs_delta_deg": round(mean_abs_delta, 4) if mean_abs_delta is not None else None,
        "max_abs_delta_deg": round(max_abs_delta, 4) if max_abs_delta is not None else None,
        "candidate_score": candidate_score,
        "matches": matches,
        "unmatched_measured": unmatched_measured,
        "unmatched_theoretical": unmatched_theoretical,
        "caveat": XRD_LIMITATION_NOTICE,
        "applicability_scope": list(DEFAULT_APPLICABILITY_SCOPE),
        "known_limitations": [XRD_LIMITATION_NOTICE],
    }

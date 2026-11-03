"""Frozen analytic spectra, independently parameterized truth and honest scoring.

Truth comes from generating Gaussian centers/widths/integrals, never from a peak
detector. Separated peaks have known candidate rules (larger amplitude or greater
wavelength). Overlapping shoulders and clipping are stress cases with *withheld*
candidate/width truth: component centers are not local maxima after superposition.
Finite cells/repeated curves are not IID draws from a scientific population.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

MANIFEST_VERSION = "analytic-spectra/1"
DEV_SCENARIOS = (
    "isolated",
    "competing",
    "external_interference",
    "window_edge",
    "uneven_grid",
    "noisy",
    "noise_only",
    "sloping_baseline",
    "unit_um",
    "duplicate_coordinates",
    "malformed_unit",
    "legal_repeats",
)
HOLDOUT_SCENARIOS = (*DEV_SCENARIOS, "overlapping_shoulder", "saturation")
STRATEGIES = ("legacy_relative", "absolute", "noise_reference")
SELECTIONS = ("highest_prominence", "redmost")
# These limits are frozen before evaluation. They bound a controlled noiseless
# sampled-center exercise, not a promised real-data accuracy or a holdout target.
ACCEPTANCE = {
    "subset": ["isolated", "competing", "external_interference", "unit_um", "uneven_grid"],
    "strategy": "absolute",
    "split": "dev",
    "cell": 0,
    "replicate": 0,
    "candidate_correct_fraction": 1.0,
    "peak_recall": 1.0,
    "unmatched_detected_peaks": 0,
    "position_tolerance": "max(1.25 nm, 2 * largest native sampling gap converted to nm)",
    "scope": "isolated analytic peaks, no physical identity, no universal noise performance threshold",
}


@dataclass
class SpectralCase:
    case_id: str
    scenario: str
    split: str
    cell_key: str
    seed: int
    table: pd.DataFrame
    config: dict
    truth: list[dict]
    parameters: dict


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def generate_case(scenario, *, split, cell, replicate):
    """Generate one task (one or two curves) using fixed, non-overlapping cells.

    Development widths 3/5 nm and amplitudes 1/1.6 differ from holdout widths
    8/11 nm and amplitudes 2.4/3.3; noisy holdout is deliberately harder. Seeds
    use disjoint numeric ranges. Holdout adds unidentifiable overlapping/clipped
    mechanisms rather than presenting shuffled copies of development examples.
    """
    if split not in {"dev", "holdout"} or type(cell) is not int or cell not in (0, 1):
        raise ValueError("split must be dev/holdout and cell must be integer 0/1")
    allowed = DEV_SCENARIOS if split == "dev" else HOLDOUT_SCENARIOS
    if scenario not in allowed or type(replicate) is not int or replicate < 0:
        raise ValueError("unknown scenario for split or invalid replicate")
    case_id = f"{split}/{scenario}/cell-{cell}/rep-{replicate}"
    seed = int(hashlib.sha256(case_id.encode()).hexdigest()[:8], 16) % 100_000_000
    seed += 1_000_000_000 if split == "holdout" else 0
    rng = np.random.default_rng(seed)
    sigma = ((3.0, 5.0) if split == "dev" else (8.0, 11.0))[cell] * (1 + 0.03 * replicate)
    amplitude = ((1.0, 1.6) if split == "dev" else (2.4, 3.3))[cell]
    amplitude *= 1 + rng.uniform(-0.03, 0.03)
    noise = (
        ((0.015, 0.035) if split == "dev" else (0.12, 0.28))[cell]
        if scenario in {"noisy", "noise_only"}
        else 0.0
    )
    parameters = {
        "sigma_nm": sigma,
        "amplitude": amplitude,
        "noise_sd": noise,
        "sampling": "uneven" if scenario == "uneven_grid" else "uniform",
        "baseline": "linear" if scenario == "sloping_baseline" else "zero",
    }
    cell_key = _canonical(
        {
            "scenario": scenario,
            "sigma_base_nm": ((3, 5) if split == "dev" else (8, 11))[cell],
            "amplitude_base": ((1, 1.6) if split == "dev" else (2.4, 3.3))[cell],
            "noise_sd": noise,
            "sampling": parameters["sampling"],
        }
    )
    x = np.linspace(600.0, 900.0, 601)
    if scenario == "uneven_grid":
        x[1:-1] += rng.uniform(-0.21, 0.21, len(x) - 2)
    center = 760.0 + rng.uniform(-4, 4)
    components = [(center, amplitude, sigma)]
    window = [700.0, 820.0]
    if scenario == "noise_only":
        components = []
    elif scenario == "competing":
        components = [(730.0, amplitude, sigma), (790.0, amplitude * 0.6, sigma)]
    elif scenario == "external_interference":
        components = [
            (650.0, amplitude * (100 if split == "dev" else 1000), sigma),
            (760.0, amplitude, sigma),
        ]
    elif scenario == "window_edge":
        components = [((700.0 if cell == 0 else 820.0), amplitude, sigma)]
    elif scenario == "overlapping_shoulder":
        components = [(755.0, amplitude, sigma), (755.0 + 1.4 * sigma, amplitude * 0.55, sigma)]
    scale = 1000.0 if scenario == "unit_um" else 1.0
    config = {
        "x_unit": "um" if scale == 1000 else "nm",
        "intensity_unit": "count",
        "lambda10_window_nm": window,
        "baseline": "none",
        "bootstrap_samples": 0,
        "peak_distance_x": 10.0 / scale,
    }
    baseline = 0.3 + 0.001 * (x - 600) if scenario == "sloping_baseline" else np.zeros_like(x)
    if scenario == "sloping_baseline":
        config["baseline"] = {"method": "anchors", "points": [[600.0, 0.3], [900.0, 0.6]]}
    y = baseline.copy()
    for mean, height, width in components:
        y += height * np.exp(-0.5 * ((x - mean) / width) ** 2)
    if noise:
        y += rng.normal(0, noise, len(x))
    if scenario == "saturation":
        y = np.minimum(y, amplitude * 0.65)
    table = pd.DataFrame({"curve_id": "curve-01", "x": x / scale, "y": y})
    if scenario == "duplicate_coordinates":
        table.loc[20, "x"] = table.loc[19, "x"]
    if scenario == "malformed_unit":
        config["x_unit"] = "second"
    invalid = scenario in {"duplicate_coordinates", "malformed_unit"}
    identifiable = scenario not in {"overlapping_shoulder", "saturation"}
    peaks = [
        {
            "center_nm": mean,
            "amplitude": height,
            "sigma_nm": width,
            "fwhm_nm": 2 * math.sqrt(2 * math.log(2)) * width,
        }
        for mean, height, width in components
    ]
    in_window = [p for p in peaks if window[0] <= p["center_nm"] <= window[1]]
    targets = {
        "highest_prominence": max(in_window, key=lambda p: p["amplitude"])["center_nm"]
        if in_window
        else None,
        "redmost": max(p["center_nm"] for p in in_window) if in_window else None,
    }
    integral = sum(
        height
        * width
        * math.sqrt(math.pi / 2)
        * (math.erf((900 - mean) / (math.sqrt(2) * width)) - math.erf((600 - mean) / (math.sqrt(2) * width)))
        for mean, height, width in components
    )
    truth = [
        {
            "curve_id": "curve-01",
            "valid_input": not invalid,
            "candidate_scorable": identifiable and not invalid,
            "peak_scorable": identifiable and not invalid,
            "targets_nm": targets if identifiable else None,
            "peaks": peaks,
            "window_peak_count": len(in_window),
            "tolerance_nm": max(1.25, 2 * float(np.diff(x).max())),
            "integral_native": integral / scale if identifiable else None,
            "width_scorable": identifiable and len(peaks) == 1 and not noise,
            "truth_note": "analytic isolated-component centers"
            if identifiable
            else "withheld: overlapping/clipped component centers are not identifiable local maxima",
        }
    ]
    if scenario == "legal_repeats":
        other = table.copy()
        other["curve_id"] = "curve-02"
        table = pd.concat([table, other], ignore_index=True)
        truth.append({**truth[0], "curve_id": "curve-02"})
    return SpectralCase(case_id, scenario, split, cell_key, seed, table, config, truth, parameters)


def build_pool():
    """Return the immutable 260-task pool, including 20 two-curve tasks."""
    return [
        generate_case(scenario, split=split, cell=cell, replicate=replicate)
        for split, scenarios in (("dev", DEV_SCENARIOS), ("holdout", HOLDOUT_SCENARIOS))
        for scenario in scenarios
        for cell in (0, 1)
        for replicate in range(5)
    ]


def strategy_config(case, strategy, selection):
    if strategy not in STRATEGIES or selection not in SELECTIONS:
        raise ValueError("unknown evaluation strategy or selection")
    config = {**case.config, "prominence_mode": strategy, "lambda10_selection": selection}
    if strategy == "absolute":
        config["prominence"] = 0.15
    elif strategy == "noise_reference":
        scale = 1000.0 if case.config["x_unit"] == "um" else 1.0
        config.update(noise_window=[875.0 / scale, 900.0 / scale], noise_multiplier=5.0)
    return config


def _finite(value):
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def score_case(case, result, *, selection):
    """Score each *expected* curve, retaining failed/absent output denominators.

    One-to-one minimum-distance matches are made against generating centers with
    a frozen sampling tolerance. Widths compare only isolated, noiseless curves;
    analytical finite-domain Gaussian integrals are compared in native x units.
    Candidate correctness and ambiguous expected count are separate diagnostics.
    """
    summaries = {r["curve_id"]: r for r in result.get("curve_summary", [])}
    features = result.get("features", [])
    rows = []
    scale = 1000.0 if case.config["x_unit"] == "um" else 1.0
    for truth in case.truth:
        observed = summaries.get(truth["curve_id"], {})
        status = observed.get("status", "missing_summary")
        rejected = bool(result.get("exception")) or status == "failed"
        candidate = observed.get("window_candidate_nm", observed.get("lambda10_nm"))
        target = truth["targets_nm"][selection] if truth["candidate_scorable"] else None
        error = abs(float(candidate) - target) if target is not None and _finite(candidate) else None
        correct = (
            (error is not None and error <= truth["tolerance_nm"])
            if target is not None
            else (status == "completed" and not _finite(candidate))
        )
        row = {
            "case_id": case.case_id,
            "scenario": case.scenario,
            "split": case.split,
            "cell_key": case.cell_key,
            "seed": case.seed,
            "curve_id": truth["curve_id"],
            "analysis_status": status,
            "valid_input": truth["valid_input"],
            "rejection_correct": rejected if not truth["valid_input"] else None,
            "valid_input_rejected": rejected if truth["valid_input"] else None,
            "candidate_scorable": truth["candidate_scorable"],
            "candidate_detected": _finite(candidate),
            "target_present": target is not None if truth["candidate_scorable"] else None,
            "target_nm": target,
            "observed_candidate_nm": float(candidate) if _finite(candidate) else None,
            "candidate_error_nm": error,
            "candidate_correct": correct if truth["candidate_scorable"] else None,
            "tolerance_nm": truth["tolerance_nm"],
            "true_peak_count": None,
            "detected_peak_count": None,
            "matched_peaks": None,
            "unmatched_detected_peaks": None,
            "peak_position_mae_nm": None,
            "fwhm_relative_error": None,
            "integral_relative_error": None,
            "ambiguity_correct": None,
            "truth_note": truth["truth_note"],
            "error": result.get("exception", observed.get("error")),
        }
        count = observed.get("candidate_count", observed.get("lambda10_candidate_count"))
        if truth["candidate_scorable"]:
            row["ambiguity_correct"] = count == truth["window_peak_count"] if count is not None else None
        if truth["peak_scorable"]:
            detected = [
                f
                for f in features
                if f.get("curve_id") == truth["curve_id"] and _finite(f.get("peak_position"))
            ]
            positions = np.array([float(f["peak_position"]) * scale for f in detected])
            centers = np.array([p["center_nm"] for p in truth["peaks"]])
            matches = []
            if len(positions) and len(centers):
                distances = abs(positions[:, None] - centers[None, :])
                rr, cc = linear_sum_assignment(np.where(distances <= truth["tolerance_nm"], distances, 1e12))
                matches = [
                    (int(i), int(j), float(distances[i, j]))
                    for i, j in zip(rr, cc, strict=True)
                    if distances[i, j] <= truth["tolerance_nm"]
                ]
            row.update(
                true_peak_count=len(centers),
                detected_peak_count=len(positions),
                matched_peaks=len(matches),
                unmatched_detected_peaks=len(positions) - len(matches),
                peak_position_mae_nm=float(np.mean([m[2] for m in matches])) if matches else None,
            )
            if truth["width_scorable"] and matches:
                i, j, _ = matches[0]
                width = detected[i].get("fwhm")
                if _finite(width):
                    row["fwhm_relative_error"] = abs(float(width) * scale / truth["peaks"][j]["fwhm_nm"] - 1)
            areas = observed.get("areas")
            if areas and truth["integral_native"] and _finite(areas[0].get("area")):
                row["integral_relative_error"] = abs(float(areas[0]["area"]) / truth["integral_native"] - 1)
        rows.append(row)
    return rows


def evaluate_cases(cases, *, strategies=STRATEGIES, selections=SELECTIONS):
    """Run the real public extractor. Exceptions become retained scored failures."""
    from materials_quality.science.spectrum_batch import analyze_spectra

    records = []
    for case in cases:
        for strategy in strategies:
            for selection in selections:
                config = strategy_config(case, strategy, selection)
                start = time.perf_counter()
                try:
                    result = analyze_spectra(case.table, config).data
                except (ValueError, TypeError, ArithmeticError) as exc:
                    result = {"exception": f"{type(exc).__name__}: {exc}"}
                elapsed = time.perf_counter() - start
                for row in score_case(case, result, selection=selection):
                    noise_unavailable = strategy == "noise_reference" and case.parameters["noise_sd"] == 0
                    row["strategy_applicability"] = (
                        "invalid_input"
                        if not row["valid_input"]
                        else "no_stochastic_reference_noise"
                        if noise_unavailable
                        else "applicable"
                    )
                    row["correct_stop"] = row["rejection_correct"] is True or (
                        noise_unavailable and row["valid_input_rejected"] is True
                    )
                    row["unexpected_rejection"] = (
                        row["valid_input_rejected"] is True and not noise_unavailable
                    )
                    row.update(
                        strategy=strategy,
                        selection=selection,
                        elapsed_seconds=elapsed,
                        config_sha256=_sha(config),
                    )
                    records.append(row)
    return records


def _metrics(rows):
    candidate = [r for r in rows if r["candidate_scorable"]]
    rejection = [r for r in rows if not r["valid_input"]]
    valid = [r for r in rows if r["valid_input"]]
    peak_rows = [r for r in rows if r["true_peak_count"] is not None]
    true_peaks = sum(r["true_peak_count"] for r in peak_rows)
    detected_peaks = sum(r["detected_peak_count"] for r in peak_rows)
    matched = sum(r["matched_peaks"] for r in peak_rows)
    correct = sum(r["candidate_correct"] is True for r in candidate)
    present = [r for r in candidate if r["target_present"]]
    absent = [r for r in candidate if not r["target_present"]]
    candidate_errors = [r["candidate_error_nm"] for r in candidate if r["candidate_error_nm"] is not None]
    widths = [r["fwhm_relative_error"] for r in rows if r["fwhm_relative_error"] is not None]
    areas = [r["integral_relative_error"] for r in rows if r["integral_relative_error"] is not None]
    task_keys = {(r["case_id"], r["strategy"], r["selection"]) for r in rows}
    return {
        "task_runs": len(task_keys),
        "unique_tasks": len({r["case_id"] for r in rows}),
        "curve_runs": len(rows),
        "candidate_scored_curves": len(candidate),
        "candidate_correct_curves": correct,
        "candidate_accuracy": correct / len(candidate) if candidate else None,
        "candidate_detected_curves": sum(r["candidate_detected"] for r in candidate),
        "target_present_curves": len(present),
        "target_absent_curves": len(absent),
        "true_positive_curves": sum(r["candidate_detected"] for r in present),
        "false_negative_curves": sum(not r["candidate_detected"] for r in present),
        "false_positive_curves": sum(r["candidate_detected"] for r in absent),
        "correct_absence_curves": sum(r["candidate_correct"] is True for r in absent),
        "candidate_error_observed_denominator": len(candidate_errors),
        "candidate_observed_mae_nm": float(np.mean(candidate_errors)) if candidate_errors else None,
        "unscorable_valid_curves": sum(not r["candidate_scorable"] for r in valid),
        "rejection_scored_curves": len(rejection),
        "correct_rejections": sum(r["rejection_correct"] is True for r in rejection),
        "valid_input_curves": len(valid),
        "valid_input_rejections": sum(r["valid_input_rejected"] is True for r in valid),
        "correct_stops": sum(r["correct_stop"] for r in rows),
        "unexpected_rejections": sum(r["unexpected_rejection"] for r in rows),
        "strategy_applicable_curves": sum(r["strategy_applicability"] == "applicable" for r in rows),
        "true_peaks": true_peaks,
        "detected_peaks": detected_peaks,
        "matched_peaks": matched,
        "peak_recall": matched / true_peaks if true_peaks else None,
        "peak_precision": matched / detected_peaks if detected_peaks else None,
        "fwhm_observed_denominator": len(widths),
        "fwhm_mean_relative_error": float(np.mean(widths)) if widths else None,
        "integral_observed_denominator": len(areas),
        "integral_mean_relative_error": float(np.mean(areas)) if areas else None,
        "elapsed_task_seconds": sum(
            next(r["elapsed_seconds"] for r in rows if (r["case_id"], r["strategy"], r["selection"]) == key)
            for key in task_keys
        ),
    }


def summarize(records):
    strata = {}
    for row in records:
        key = (row["split"], row["scenario"], row["cell_key"], row["strategy"], row["selection"])
        strata.setdefault(key, []).append(row)
    failed = [
        r
        for r in records
        if r["candidate_correct"] is False
        or r["rejection_correct"] is False
        or r["unexpected_rejection"] is True
    ]
    return {
        "schema": MANIFEST_VERSION,
        "overall": _metrics(records),
        "strata": [
            {
                **dict(zip(("split", "scenario", "cell_key", "strategy", "selection"), key, strict=True)),
                **_metrics(rows),
            }
            for key, rows in strata.items()
        ],
        "uncertainty": {
            "interval": None,
            "reason": "Frozen deterministic parameter cells are not IID "
            "population trials; curves/rules share tasks. No binomial CI is justified.",
        },
        "failure_curve_runs": len(failed),
        "failure_task_ids": sorted({r["case_id"] for r in failed}),
        "interpretation": "Candidate accuracy includes missing/failed curves in its denominator; "
        "MAE, width and integral errors are conditional on available outputs. Stress "
        "overlap/clipping truth is withheld; this is not physical mode identification. "
        "Valid-input rejections include appropriate zero-noise reference stops, distinguished "
        "from unexpected rejection of an applicable method. No candidate failures are removed.",
    }


def _git_metadata(path):
    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    return {"commit": git("rev-parse", "HEAD"), "dirty_porcelain": git("status", "--porcelain")}


def run_evaluation(output_dir, *, cases=None, strategies=STRATEGIES, selections=SELECTIONS):
    """Write traceable CSV/JSON/summary/manifest into a fresh directory only."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    cases = build_pool() if cases is None else list(cases)
    configs = [
        {"case_id": c.case_id, "strategy": s, "selection": rule, "config": strategy_config(c, s, rule)}
        for c in cases
        for s in strategies
        for rule in selections
    ]
    inputs = [
        {
            "case_id": c.case_id,
            "scenario": c.scenario,
            "split": c.split,
            "cell_key": c.cell_key,
            "seed": c.seed,
            "parameters": c.parameters,
            "truth": c.truth,
            "input_sha256": _sha(c.table.to_dict("list")),
        }
        for c in cases
    ]
    source = Path(__file__).resolve()
    package = source.parents[3]
    source_hashes = {}
    for folder in (source.parent, source.parents[1] / "science"):
        for file in sorted(folder.glob("*.py")):
            source_hashes[str(file.relative_to(package)).replace("\\", "/")] = hashlib.sha256(
                file.read_bytes()
            ).hexdigest()
    versions = {}
    for name in ("langflow-materials-quality", "numpy", "scipy", "pandas", "pint"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not-installed (source execution)"
    manifest = {
        "schema": MANIFEST_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "truth_scope": "analytic spectral candidates; no physical mode identity",
        "seed_split_policy": "dev seeds [0,1e8); holdout [1e9,1.1e9); parameter cells disjoint; "
        "holdout alone adds overlapping shoulders and saturation",
        "task_count": len(cases),
        "curve_count": sum(len(c.truth) for c in cases),
        "strategies": list(strategies),
        "selections": list(selections),
        "acceptance": ACCEPTANCE,
        "inputs": inputs,
        "effective_configs": configs,
        "config_sha256": _sha(configs),
        "inputs_sha256": _sha(inputs),
        "source_sha256": source_hashes,
        "git": _git_metadata(package),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "versions": versions,
        },
        "limits": [
            "No real instrument data or physical mode labels are used.",
            "No population inference or confidence interval from finite deterministic cells.",
            "No model repair loop or automatic actions evaluated in this increment.",
        ],
    }
    start = time.perf_counter()
    records = evaluate_cases(cases, strategies=strategies, selections=selections)
    summary = summarize(records)
    summary["wall_seconds"] = time.perf_counter() - start
    for name, data in (("manifest", manifest), ("per_case", records), ("summary", summary)):
        (output / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
    with (output / "per_case.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]) if records else ["case_id"])
        writer.writeheader()
        writer.writerows(records)
    artifacts = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(output.iterdir())
        if file.is_file()
    }
    (output / "artifact_hashes.json").write_text(_canonical(artifacts), encoding="utf-8")
    return summary

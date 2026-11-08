"""Independent repeated-design simulation and closed-form inference references.

Every trial draws fresh sample-unit effects and technical measurement noise.
Technical rows share their unit effect and are deliberately not independent units.
The independent oracle uses explicit sample variance, Satterthwaite degrees of
freedom and Student quantiles; it never calls a production aggregator or t-test.
Monte Carlo uncertainty describes these simulated designs, not real experiments.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm, t

SCHEMA = "independent-design-evaluation/1"
DEFAULT_REPETITIONS = 32  # 16 prespecified strata -> 512 independently drawn trials.
DEFAULT_SEED = 20261103
ORACLE_TOLERANCE = 1e-10


@dataclass
class DesignTrial:
    trial_id: str
    seed: int
    table: pd.DataFrame
    config: dict
    truth: dict


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def generate_trial(*, seed, n_per_group, technical_replicates, effect, variance, design="independent"):
    """Generate Normal random unit effects plus condition-specific Normal noise.

    Independent model: Y_gij = effect * I(g=A) + U_gi + epsilon_gij.
    Unit SD(A,B)=(1,1) or (1,2); technical SD=(.4,.4) or (.7,.3).
    Paired model shares U_i; an additional N(0,.5^2) pair difference is split
    equally between conditions. The estimand is always population mean(A-B).
    """
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if type(n_per_group) is not int or n_per_group < 1:
        raise ValueError("n_per_group must be a positive integer")
    if type(technical_replicates) is not int or technical_replicates < 1:
        raise ValueError("technical_replicates must be a positive integer")
    if not isinstance(variance, str) or variance not in {"balanced", "heterogeneous"}:
        raise ValueError("unsupported variance scenario or design")
    if not isinstance(design, str) or design not in {"independent", "paired"}:
        raise ValueError("unsupported variance scenario or design")
    if type(effect) not in (int, float) or isinstance(effect, bool) or not math.isfinite(effect):
        raise ValueError("effect must be finite")
    rng = np.random.default_rng(seed)
    unit_sd = [1.0, 1.0] if variance == "balanced" else [1.0, 2.0]
    technical_sd = [0.4, 0.4] if variance == "balanced" else [0.7, 0.3]
    shared = rng.normal(0, 1, n_per_group) if design == "paired" else None
    paired_difference = rng.normal(0, 0.5, n_per_group) if design == "paired" else None
    rows = []
    for g, label in enumerate(("A", "B")):
        for i in range(n_per_group):
            unit_effect = (
                shared[i] + (0.5 if g == 0 else -0.5) * paired_difference[i]
                if design == "paired"
                else rng.normal(0, unit_sd[g])
            )
            identifier = f"pair-{i:03d}" if design == "paired" else f"{label}-unit-{i:03d}"
            for j in range(technical_replicates):
                value = (effect if g == 0 else 0.0) + unit_effect + rng.normal(0, technical_sd[g])
                rows.append(
                    {
                        "group": label,
                        "variable": "response",
                        "experimental_unit": identifier,
                        "sample_id": f"{label}-{i:03d}-technical-{j:02d}",
                        "value": float(value),
                    }
                )
    truth = {
        "design": design,
        "variance": variance,
        "n_per_group": n_per_group,
        "technical_replicates": technical_replicates,
        "true_difference": float(effect),
        "unit_sd_a_b": unit_sd,
        "technical_sd_a_b": technical_sd,
        "paired_difference_sd": 0.5 if design == "paired" else None,
        "alpha": 0.05,
        "experimental_unit": "sample unit, not technical row",
    }
    config = {
        "design": design,
        "strategy": "parametric",
        "alpha": 0.05,
        "small_sample_policy": "descriptive",
        "correction": "holm",
    }
    identifier = f"{design}/{variance}/n-{n_per_group}/r-{technical_replicates}/effect-{effect:g}/seed-{seed}"
    return DesignTrial(identifier, seed, pd.DataFrame(rows), config, truth)


def build_trials(*, repetitions=DEFAULT_REPETITIONS, seed=DEFAULT_SEED):
    """Create independent trials for each fixed design; effect 0/2 alternates.

    A separate SeedSequence child supplies every trial RNG. No paired-condition
    or technical rows are counted as additional independent simulation trials.
    """
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    settings = [
        (n, r, variance, effect)
        for n in (4, 8)
        for r in (1, 3)
        for variance in ("balanced", "heterogeneous")
        for _ in range(repetitions)
        for effect in (0.0, 2.0)
    ]
    streams = np.random.SeedSequence(seed).spawn(len(settings))
    return [
        generate_trial(
            seed=int(stream.generate_state(1, dtype=np.uint64)[0]),
            n_per_group=n,
            technical_replicates=r,
            effect=effect,
            variance=variance,
        )
        for (n, r, variance, effect), stream in zip(settings, streams, strict=True)
    ]


def closed_form_interval(a, b, *, paired=False, alpha=0.05):
    """Explicit Welch/Satterthwaite or paired-t formula, independent of pipeline."""
    a, b = list(map(float, a)), list(map(float, b))
    if min(len(a), len(b)) < 2 or (paired and len(a) != len(b)):
        raise ValueError("oracle requires at least two units and matched paired lengths")
    if not all(map(math.isfinite, a)) or not all(map(math.isfinite, b)):
        raise ValueError("oracle requires finite unit values")
    if (
        type(alpha) not in (int, float)
        or isinstance(alpha, bool)
        or not math.isfinite(alpha)
        or not 0 < alpha < 1
    ):
        raise ValueError("alpha must be a finite number strictly between 0 and 1")
    try:
        difference = statistics.mean(a) - statistics.mean(b)
        if paired:
            differences = [x - y for x, y in zip(a, b, strict=True)]
            variance_mean = statistics.variance(differences) / len(differences)
            degrees = len(differences) - 1
        else:
            va, vb = statistics.variance(a) / len(a), statistics.variance(b) / len(b)
            variance_mean = va + vb
            # Guard the Satterthwaite denominator before dividing: both groups
            # being constant makes it exactly zero (ZeroDivisionError otherwise).
            denominator = va**2 / (len(a) - 1) + vb**2 / (len(b) - 1)
            if not denominator:
                raise ValueError("oracle reference distribution unavailable for degenerate variance")
            degrees = variance_mean**2 / denominator
        if not math.isfinite(variance_mean) or variance_mean <= 0:
            raise ValueError("oracle reference distribution unavailable for degenerate variance")
        se = math.sqrt(variance_mean)
        statistic = difference / se
        critical = float(t.ppf(1 - alpha / 2, degrees))
    except (OverflowError, ArithmeticError):
        raise ValueError("oracle reference distribution unavailable for extreme values") from None
    return {
        "mean_difference": difference,
        "ci_low": difference - critical * se,
        "ci_high": difference + critical * se,
        "statistic": statistic,
        "p_raw": float(2 * t.sf(abs(statistic), degrees)),
        "df": float(degrees),
        "n_a": len(a),
        "n_b": len(b),
    }


def _reference_arrays(frame):
    groups = defaultdict(lambda: defaultdict(list))
    rows = defaultdict(list)
    for row in frame.itertuples(index=False):
        groups[row.group][row.experimental_unit].append(float(row.value))
        rows[row.group].append(float(row.value))
    units = {
        label: [statistics.mean(values) for _, values in sorted(mapping.items())]
        for label, mapping in groups.items()
    }
    return units, rows


def evaluate_trial(trial):
    """Call real contrast_study on technical rows, independently aggregate oracle."""
    from materials_quality.science.contrast_study import contrast_study

    units, technical = _reference_arrays(trial.table)
    paired = trial.truth["design"] == "paired"
    oracle = closed_form_interval(units["A"], units["B"], paired=paired, alpha=trial.config["alpha"])
    naive = closed_form_interval(technical["A"], technical["B"], paired=paired, alpha=trial.config["alpha"])
    start = time.perf_counter()
    error = None
    try:
        actual = contrast_study(trial.table, config=trial.config).data["pairwise"][0]
    except (ValueError, TypeError, ArithmeticError) as exc:
        actual = {}
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - start
    comparison = {
        "mean_difference": "mean_difference",
        "p_raw": "p_raw",
        "ci_low": "mean_difference_ci_low",
        "ci_high": "mean_difference_ci_high",
        "statistic": "statistic",
    }
    agrees = all(
        actual.get(key) is not None
        and math.isclose(float(actual[key]), oracle[name], rel_tol=ORACLE_TOLERANCE, abs_tol=ORACLE_TOLERANCE)
        for name, key in comparison.items()
    )
    agrees = agrees and actual.get("n_a") == oracle["n_a"] and actual.get("n_b") == oracle["n_b"]
    low, high = actual.get("mean_difference_ci_low"), actual.get("mean_difference_ci_high")
    true_difference = trial.truth["true_difference"]
    estimated = low is not None and high is not None
    p = actual.get("p_raw")
    output = {
        "trial_id": trial.trial_id,
        "seed": trial.seed,
        **trial.truth,
        "technical_rows": len(trial.table),
        "n_a": actual.get("n_a"),
        "n_b": actual.get("n_b"),
        "mean_difference": actual.get("mean_difference"),
        "p_raw": p,
        "ci_low": low,
        "ci_high": high,
        "ci_width": high - low if estimated else None,
        "ci_status": actual.get("ci_status"),
        "ci_method": actual.get("ci_method"),
        "covers_truth": low <= true_difference <= high if estimated else None,
        "rejects_null": p < trial.config["alpha"] if p is not None else None,
        "oracle_agreement": bool(agrees),
        "oracle_df": oracle["df"],
        "oracle_mean_difference": oracle["mean_difference"],
        "oracle_p_raw": oracle["p_raw"],
        "oracle_ci_low": oracle["ci_low"],
        "oracle_ci_high": oracle["ci_high"],
        "naive_n_a": naive["n_a"],
        "naive_n_b": naive["n_b"],
        "naive_p_raw": naive["p_raw"],
        "naive_ci_low": naive["ci_low"],
        "naive_ci_high": naive["ci_high"],
        "naive_ci_width": naive["ci_high"] - naive["ci_low"],
        "naive_covers_truth": naive["ci_low"] <= true_difference <= naive["ci_high"],
        "naive_rejects_null": naive["p_raw"] < trial.config["alpha"],
        "error": error,
        "elapsed_seconds": elapsed,
    }
    return output


def evaluate_trials(trials):
    return [evaluate_trial(trial) for trial in trials]


def binomial_mc(successes, denominator):
    """Plug-in MCSE plus Wilson 95% interval for *independent simulated trials*."""
    if type(denominator) is not int or denominator < 0:
        raise ValueError("denominator must be a nonnegative integer")
    if type(successes) is not int or isinstance(successes, bool) or not 0 <= successes <= denominator:
        raise ValueError("successes must be an integer from 0 to denominator")
    if not denominator:
        return {
            "successes": successes,
            "denominator": 0,
            "estimate": None,
            "monte_carlo_se": None,
            "wilson_low": None,
            "wilson_high": None,
        }
    p = successes / denominator
    z = float(norm.ppf(0.975))
    divisor = 1 + z**2 / denominator
    center = (p + z**2 / (2 * denominator)) / divisor
    radius = z * math.sqrt(p * (1 - p) / denominator + z**2 / (4 * denominator**2)) / divisor
    return {
        "successes": successes,
        "denominator": denominator,
        "estimate": p,
        "monte_carlo_se": math.sqrt(p * (1 - p) / denominator),
        "wilson_low": max(0.0, center - radius),
        "wilson_high": min(1.0, center + radius),
    }


def _continuous(values):
    return {
        "denominator": len(values),
        "mean": statistics.mean(values) if values else None,
        "monte_carlo_se": statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None,
    }


def summarize_design(records):
    cells = defaultdict(list)
    keys = ("design", "variance", "n_per_group", "technical_replicates", "true_difference")
    for row in records:
        cells[tuple(row[k] for k in keys)].append(row)
    strata = []
    for cell, rows in cells.items():
        observed = [r for r in rows if r["covers_truth"] is not None]
        tested = [r for r in rows if r["rejects_null"] is not None]
        strata.append(
            {
                **dict(zip(keys, cell, strict=True)),
                "trials": len(rows),
                "pipeline_failures": sum(r["error"] is not None for r in rows),
                "oracle_mismatches": sum(not r["oracle_agreement"] for r in rows),
                "coverage": binomial_mc(sum(r["covers_truth"] for r in observed), len(observed)),
                "coverage_counting_missing_as_failure": binomial_mc(
                    sum(r["covers_truth"] is True for r in rows), len(rows)
                ),
                "rejection": binomial_mc(sum(r["rejects_null"] for r in tested), len(tested)),
                "rejection_interpretation": "type_I_error" if cell[-1] == 0 else "power_at_declared_shift",
                "mean_ci_width": _continuous([r["ci_width"] for r in observed]),
                "naive_coverage": binomial_mc(sum(r["naive_covers_truth"] for r in rows), len(rows)),
                "naive_rejection": binomial_mc(sum(r["naive_rejects_null"] for r in rows), len(rows)),
                "naive_mean_ci_width": _continuous([r["naive_ci_width"] for r in rows]),
            }
        )
    return {
        "schema": SCHEMA,
        "independent_trials": len(records),
        "strata": strata,
        "oracle_mismatches": sum(not r["oracle_agreement"] for r in records),
        "pipeline_failures": sum(r["error"] is not None for r in records),
        "failed_trial_ids": [r["trial_id"] for r in records if not r["oracle_agreement"] or r["error"]],
        "interpretation": "Each cell uses independent normal-model simulation trials. Monte Carlo errors "
        "and Wilson intervals quantify simulation precision conditional on that design. "
        "Nonzero-shift rejection is power, not Type I error. No universal coverage pass target is set. "
        "Individual mean-difference intervals are unadjusted; this is not simultaneous coverage. "
        "The row-level comparator intentionally ignores correlation within sample units.",
    }


def run_design_evaluation(output_dir, *, trials=None):
    """Persist all trial outcomes and reproducible design/source metadata, fresh only."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    trials = build_trials() if trials is None else list(trials)
    source = Path(__file__).resolve()
    package = source.parents[3]
    source_files = (
        source,
        source.parents[1] / "science/contrast_study.py",
        source.parents[1] / "science/contracts.py",
        package / "scripts/evaluate_design.py",
    )
    hashes = {
        str(file.relative_to(package)).replace("\\", "/"): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in source_files
    }
    versions = {}
    for name in ("numpy", "scipy", "pandas", "statsmodels", "langflow-materials-quality"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed; source execution"
    git = subprocess.run(
        ["git", "-C", str(package), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    specs = [
        {
            "trial_id": trial.trial_id,
            "seed": trial.seed,
            "parameters": trial.truth,
            "config": trial.config,
            "input_sha256": _hash(trial.table.to_dict("list")),
        }
        for trial in trials
    ]
    manifest = {
        "schema": SCHEMA,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "rng_policy": "Independent SeedSequence child RNG per trial; unit effects and technical "
        "noise drawn independently except explicitly shared within-unit/pair effects.",
        "model": "Independent: Y_gij=effect*I(g=A)+U_gi+epsilon_gij; Normal unit and technical noise. "
        "Paired: shared U_i and N(0,.5^2) pair difference; tests exercise paired formula.",
        "oracle": "Python statistics sample variance; explicit Welch-Satterthwaite or paired-t "
        "formula; scipy Student quantile/survival only, no production aggregation/t-test.",
        "acceptance": {
            "numeric_oracle_relative_and_absolute_tolerance": ORACLE_TOLERANCE,
            "coverage_or_type_I_pass_threshold": None,
        },
        "trials": specs,
        "config_and_input_sha256": _hash(specs),
        "source_sha256": hashes,
        "git_commit": git.stdout.strip() if git.returncode == 0 else None,
        "environment": {
            "python": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
            "versions": versions,
            "threads": {
                k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
            },
        },
        "limits": [
            "Results depend on declared normal effects/noise, sample size and replication.",
            "No observed DeepSeek percentages are assumed or reused.",
            "This is simulation validation, not evidence of independence in real samples.",
            "Small-n descriptive/model-based policies are tested separately, not population theorems.",
        ],
    }
    start = time.perf_counter()
    records = evaluate_trials(trials)
    summary = summarize_design(records)
    summary["wall_seconds"] = time.perf_counter() - start
    for filename, data in (
        ("manifest.json", manifest),
        ("per_trial.json", records),
        ("summary.json", summary),
    ):
        (output / filename).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
    with (output / "per_trial.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]) if records else ["trial_id"])
        writer.writeheader()
        writer.writerows(records)
    integrity = {
        file.name: hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(output.iterdir())
        if file.is_file()
    }
    (output / "artifact_hashes.json").write_text(_canonical(integrity), encoding="utf-8")
    return summary

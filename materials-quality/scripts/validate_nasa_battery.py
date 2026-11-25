"""Reproduce NASA PCoE B0005 discharge capacities and independently check retention."""

import argparse
import json
import shutil
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

import numpy as np
import pandas as pd
from scipy.io import loadmat

from materials_quality.context import table_fingerprint
from materials_quality.science.battery import analyze_battery_cycles

SOURCE = "https://phm-datasets.s3.amazonaws.com/NASA/5.+Battery+Data+Set.zip"
ARCHIVE_SHA256 = "82302a7db4fc1b34e0b6676326610438d43b816bdf11a69d1d012a464ef2f92e"
MAT_SHA256 = "0eae4585baf3f200c09fe24c5ab884f1889679fc75206ca1aa19da704104f0b0"
MEMBER = "5. Battery Data Set/1. BatteryAgingARC-FY08Q4.zip"
ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts" / "nasa_battery"
CUTOFF_V = 2.7
CAPACITY_TOLERANCE_AH = 0.0001
RETENTION_TOLERANCE_PP = 0.01
CONFIG = {
    "mode": "raw",
    "time_unit": "s",
    "current_unit": "A",
    "current_sign": "discharge_negative",
    "sign_tolerance_a": 0.01,
}


def _file_sha256(path):
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_mat(download):
    mat = ARTIFACTS / "B0005.mat"
    if not mat.exists():
        archive = ARTIFACTS / "NASA_battery.zip"
        if not archive.exists():
            if not download:
                raise SystemExit(
                    "NASA source is absent. Run with --download to fetch the official 200 MiB ZIP."
                )
            temporary = archive.with_suffix(".zip.part")
            try:
                with urlopen(SOURCE, timeout=120) as remote, temporary.open("wb") as local:
                    shutil.copyfileobj(remote, local, length=1024 * 1024)
                if _file_sha256(temporary) != ARCHIVE_SHA256:
                    raise ValueError("NASA archive SHA-256 differs from the recorded version")
                temporary.replace(archive)
            finally:
                temporary.unlink(missing_ok=True)
        if _file_sha256(archive) != ARCHIVE_SHA256:
            raise ValueError("NASA archive SHA-256 differs from the recorded version")
        with ZipFile(archive) as outer, ZipFile(BytesIO(outer.read(MEMBER))) as inner:
            content = inner.read("B0005.mat")
        if sha256(content).hexdigest() != MAT_SHA256:
            raise ValueError("B0005.mat SHA-256 differs from the recorded version")
        mat.write_bytes(content)
    if _file_sha256(mat) != MAT_SHA256:
        raise ValueError("B0005.mat SHA-256 differs from the recorded version")
    return mat


def validate(mat):
    operations = loadmat(mat, simplify_cells=True)["B0005"]["cycle"]
    discharge = [
        (position, item) for position, item in enumerate(operations, 1) if item["type"] == "discharge"
    ]
    samples, references = [], []
    for cycle, (position, item) in enumerate(discharge, 1):
        trace = item["data"]
        crossing = np.flatnonzero(np.asarray(trace["Voltage_measured"]) <= CUTOFF_V)
        if len(crossing) == 0 or crossing[0] < 1:
            raise ValueError(f"discharge #{cycle} lacks a valid sampled 2.7 V crossing")
        endpoint = crossing[0] + 1
        samples.append(
            pd.DataFrame(
                {
                    "cell_id": "B0005",
                    "cycle": cycle,
                    "phase": "discharge",
                    "time": trace["Time"][:endpoint],
                    "current": trace["Current_measured"][:endpoint],
                }
            )
        )
        references.append(
            {
                "cycle": cycle,
                "source_operation_1_based": position,
                "reference_capacity_ah": float(trace["Capacity"]),
                "ambient_temperature_c": float(item["ambient_temperature"]),
                "cutoff_sample_voltage_v": float(trace["Voltage_measured"][endpoint - 1]),
                "cutoff_sample_time_s": float(trace["Time"][endpoint - 1]),
            }
        )
    raw = pd.concat(samples, ignore_index=True)
    reference = pd.DataFrame(references)
    if len(reference) != 168 or not np.isfinite(reference["reference_capacity_ah"]).all():
        raise ValueError("expected 168 B0005 discharge records with finite source capacities")
    reference["reference_retention_pct"] = (
        reference["reference_capacity_ah"] / reference.loc[0, "reference_capacity_ah"] * 100
    )
    result = analyze_battery_cycles(raw, CONFIG)
    comparison = reference.merge(
        result.features[["cycle", "discharge_capacity_ah", "retention_pct", "status"]],
        on="cycle",
        how="outer",
        validate="one_to_one",
    )
    comparison["capacity_error_ah"] = (
        comparison["discharge_capacity_ah"] - comparison["reference_capacity_ah"]
    )
    comparison["retention_error_pp"] = comparison["retention_pct"] - comparison["reference_retention_pct"]
    cap_error = comparison["capacity_error_ah"].abs()
    retention_error = comparison["retention_error_pp"].abs()
    passed = bool(
        len(comparison) == 168
        and comparison["status"].eq("valid").all()
        and cap_error.le(CAPACITY_TOLERANCE_AH).all()
        and retention_error.le(RETENTION_TOLERANCE_PP).all()
    )
    report = {
        "passed": passed,
        "source_archive": SOURCE,
        "recorded_archive_sha256": ARCHIVE_SHA256,
        "mat_sha256": _file_sha256(mat),
        "raw_derived_input_sha256": table_fingerprint(raw),
        "record_count": len(operations),
        "discharge_cycle_count": len(comparison),
        "derived_trace_sample_count": len(raw),
        "cutoff_v": CUTOFF_V,
        "cutoff_rule": "retain through first measured voltage <= 2.7 V, without interpolation",
        "reference_field": "B0005.cycle(discharge).data.Capacity",
        "reference_ambient_temperature_c": sorted(reference["ambient_temperature_c"].unique().tolist()),
        "battery_config": CONFIG,
        "max_absolute_capacity_error_ah": float(cap_error.max()),
        "mean_absolute_capacity_error_ah": float(cap_error.mean()),
        "capacity_error_tolerance_ah": CAPACITY_TOLERANCE_AH,
        "max_absolute_retention_error_pp": float(retention_error.max()),
        "retention_error_tolerance_pp": RETENTION_TOLERANCE_PP,
        "first_reference_capacity_ah": float(comparison.loc[0, "reference_capacity_ah"]),
        "last_reference_capacity_ah": float(comparison.iloc[-1]["reference_capacity_ah"]),
        "last_reference_retention_pct": float(comparison.iloc[-1]["reference_retention_pct"]),
        "last_computed_retention_pct": float(comparison.iloc[-1]["retention_pct"]),
    }
    return report, raw, comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download", action="store_true", help="fetch the NASA archive if no local copy exists"
    )
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report, raw, comparison = validate(_verified_mat(args.download))
    raw.to_csv(ARTIFACTS / "b0005_cutoff_input.csv", index=False, lineterminator="\n")
    comparison.to_csv(ARTIFACTS / "cycle_comparison.csv", index=False, lineterminator="\n")
    encoded = json.dumps(report, indent=2, allow_nan=False)
    (ARTIFACTS / "benchmark.json").write_text(encoded + "\n", encoding="utf-8", newline="\n")
    print(encoded)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

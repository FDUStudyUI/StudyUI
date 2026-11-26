#!/usr/bin/env python3
"""Generate the deterministic materials-science fixtures for the harness benchmark.

The tasks are derived from the public MatOS benchmark profile's task categories
and its "materials benchmark task pitfalls" note (units, XRD/spectroscopy,
mechanics, thermal analysis, battery cycling, regression, data quality).  The
files are synthetic and fully deterministic so the benchmark can be rescored
without network access or a judge model.

Run from the repository root:

    .demo-venv/Scripts/python.exe materials-quality/testfixtures/harness_bench/generate_fixtures.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


def write_csv(relative: str, header: list[str], rows: list[list[object]]) -> None:
    path = FIXTURES / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def mechanics() -> None:
    rows: list[list[float]] = []
    # Perfect linear elastic region: E = 200 GPa = 200000 MPa.
    for index in range(21):
        strain = round(index * 0.0001, 6)
        rows.append([strain, round(200000.0 * strain, 6)])
    # Plastic region with 500 MPa UTS at 5.2% strain, then a short plateau and
    # a small softening tail so the maximum is unambiguous.
    strain = 0.0021
    while strain <= 0.1001:
        if strain <= 0.052:
            stress = 400.0 + 2000.0 * (strain - 0.002)
        elif strain <= 0.09:
            stress = 500.0
        else:
            stress = 500.0 - 2000.0 * (strain - 0.09)
        rows.append([round(strain, 6), round(stress, 6)])
        strain += 0.0005
    # Keep the coordinate strictly increasing even after float accumulation.
    unique: list[list[float]] = []
    for row in rows:
        if not unique or row[0] > unique[-1][0]:
            unique.append(row)
    write_csv("mechanics/tensile.csv", ["strain_fraction", "stress_MPa"], unique)


def xrd() -> None:
    peaks = [(21.50, 400.0), (30.60, 700.0), (35.40, 1200.0), (43.30, 300.0), (57.20, 250.0), (62.70, 200.0)]
    sigma = 0.12
    rows: list[list[float]] = []
    for index in range(3501):
        two_theta = round(10.0 + index * 0.02, 6)
        intensity = 50.0 + 0.1 * (two_theta - 10.0)
        for center, amplitude in peaks:
            intensity += amplitude * math.exp(-0.5 * ((two_theta - center) / sigma) ** 2)
        rows.append([two_theta, round(intensity, 6)])
    write_csv("xrd/xrd_scan.csv", ["two_theta_deg", "intensity"], rows)


def thermal() -> None:
    rows: list[list[float]] = []
    for index in range(155):
        temperature = 30.0 + index * 5.0
        # Two smooth 20% loss stages separated by a plateau.
        first = 20.0 / (1.0 + math.exp(-(temperature - 220.0) / 18.0))
        second = 20.0 / (1.0 + math.exp(-(temperature - 550.0) / 18.0))
        mass = 100.0 - first - second
        rows.append([round(temperature, 6), round(mass, 6)])
    write_csv("thermal/tga.csv", ["temperature_C", "mass_pct"], rows)


def regression() -> None:
    kb = 8.617333262e-5
    ea = 0.85
    sigma0 = 1000.0
    rows: list[list[float]] = []
    for temperature_c in range(300, 701, 25):
        temperature_k = temperature_c + 273.15
        sigma = sigma0 * math.exp(-ea / (kb * temperature_k))
        rows.append(
            [
                temperature_c,
                f"{sigma:.12g}",
                f"{1.0 / temperature_k:.12g}",
                f"{math.log(sigma):.12g}",
            ]
        )
    write_csv(
        "regression/arrhenius.csv",
        ["temperature_C", "conductivity_S_cm", "inv_T_K", "ln_sigma"],
        rows,
    )


def battery() -> None:
    rows: list[list[object]] = []
    for cycle in range(1, 101):
        discharge = 180.0 - (36.0 * (cycle - 1) / 99.0)
        efficiency = 99.8 - 0.002 * (cycle - 1)
        charge = discharge / (efficiency / 100.0)
        rows.append(["cell-A", cycle, f"{discharge:.6f}", f"{charge:.6f}"])
    write_csv(
        "battery/battery_cycles.csv",
        ["cell_id", "cycle", "discharge_capacity_mAh_g", "charge_capacity_mAh_g"],
        rows,
    )


def quality() -> None:
    rows: list[list[str]] = [
        ["S01", "25", "0.0120", "baseline"],
        ["S02", "50", "0.0150", "baseline"],
        ["S03", "75", "0.0180", "baseline"],
        ["S04", "", "0.0210", "missing temperature"],
        ["S05", "125", "-0.0020", "negative conductivity"],
        ["S06", "150", "0.0300", "baseline"],
        ["S07", "175", "0.0330", ""],
        ["S08", "2500", "0.0400", "temperature outlier"],
        ["S09", "225", "0.0450", "baseline"],
        ["S10", "250", "0.0480", "baseline"],
        ["S11", "275", "", "missing conductivity"],
        ["S12", "300", "0.0550", "baseline"],
        ["S13", "325", "0.0580", "baseline"],
        ["S14", "350", "0.0600", "baseline"],
        ["S15", "375", "-0.0060", "negative conductivity"],
        ["S16", "400", "0.0660", "baseline"],
        ["S17", "425", "0.0690", "baseline"],
        ["S18", "450", "0.0720", "baseline"],
        ["S19", "2200", "0.0750", "temperature outlier"],
        ["S20", "500", "0.0780", "baseline"],
    ]
    # Two exact duplicate data rows: S03 and S09 each appear twice.  Duplicates
    # are exact across all four columns, including their note text.
    rows.append(list(rows[2]))
    rows.append(list(rows[8]))
    write_csv("quality/quality_audit.csv", ["sample_id", "temperature_C", "conductivity_S_cm", "note"], rows)


def main() -> None:
    mechanics()
    xrd()
    thermal()
    regression()
    battery()
    quality()
    print(f"fixtures written under {FIXTURES}")


if __name__ == "__main__":
    main()

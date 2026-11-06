"""Independent raw-data checks of the five stored reference graphs.

References use elementary array operations and a direct SciPy test, not the
StudyUI analysis implementations. This checks the supplied demos, not an LLM.
"""

import argparse
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from materials_quality.demos.catalog import list_datasets, read_demo_bytes
from materials_quality.demos.reference import load_reference_flow


def _close(actual, expected, name, checks, *, atol=1e-8):
    if not np.allclose(actual, expected, atol=atol, rtol=1e-8):
        raise AssertionError(f"{name}: actual={actual}, expected={expected}")
    checks[name] = {"actual": np.asarray(actual).tolist(), "expected": np.asarray(expected).tolist()}


def evaluate_case(item):
    # Initialize native PDF bindings on the caller thread before LFX's workers.
    import fitz  # noqa: F401
    from lfx.graph import Graph

    case = item["id"]
    raw = read_demo_bytes(case)
    original = (
        pd.read_csv(io.BytesIO(raw), sep=r"\s+", comment="#")
        if case == "zirconia_xrd"
        else (pd.read_csv(io.BytesIO(raw)))
    )
    payload = load_reference_flow(case)
    roles = payload["studyui_reference"]["nodes"]
    graph = Graph.from_payload(payload)
    for step in graph.start():
        if hasattr(step, "valid") and not step.valid:
            raise AssertionError(f"Invalid {case} workflow step: {step}")

    def output(role, port="report"):
        result = graph.get_vertex(roles[role]).results[port]
        return result.data if port == "report" else result

    checks = {}
    assert output("import")["data"]["source_sha256"] == item["sha256"]
    pd.testing.assert_frame_equal(pd.DataFrame(output("import", "table")), original, check_dtype=False)
    if case == "ti64_tensile":
        x, y = original.strain.to_numpy(), original.stress.to_numpy()
        mask = x <= 0.0008
        slope, intercept = np.polyfit(x[mask], y[mask], 1)
        diff = y - (slope * (x - 0.002) + intercept)
        i = np.flatnonzero((x[:-1] >= 0.002) & (diff[:-1] >= 0) & (diff[1:] <= 0))[0]
        crossing = y[i] + diff[i] / (diff[i] - diff[i + 1]) * (y[i + 1] - y[i])
        result = output("analysis")["data"]
        _close(result["elastic_modulus_MPa"], slope, "modulus_MPa", checks)
        _close(result["yield_stress_MPa"], crossing, "offset_yield_MPa", checks)
        _close(result["ultimate_strength_MPa"], y.max(), "maximum_stress_MPa", checks)
        assert result["fracture_strain"] is None
    elif case == "raman_spectra":
        features = output("analysis", "features")
        assert len(features) == 16 and features.curve_id.nunique() == 8
        selected = features[features.peak_position.between(650, 850)]
        expected = []
        for _curve, rows in original.groupby("curve_id", sort=True):
            window = rows[rows.wavelength_nm.between(650, 850)]
            expected.append(float(window.loc[window.intensity_counts.idxmax(), "wavelength_nm"]))
        _close(selected.sort_values("curve_id").peak_position, expected, "window_peaks_nm", checks)
        _close(selected.groupby("group").peak_position.mean(), [715, 755], "group_means_nm", checks)
    elif case == "material_contrast":
        values = original.groupby(["group", "experimental_unit"]).value.mean()
        a, b = values.loc["A"].to_numpy(), values.loc["B"].to_numpy()
        units = output("analysis", "units")
        assert len(units) == 8
        _close(sorted(units.value.tolist()), sorted(values.tolist()), "unit_means", checks)
        pair = output("analysis", "features").iloc[0]
        expected = stats.ttest_ind(a, b, equal_var=False).pvalue
        _close(pair.p_raw, expected, "welch_p", checks)
        _close(pair.p_adjusted, expected, "holm_one_comparison_p", checks)
    elif case == "zirconia_xrd":
        y = original.Intensity.to_numpy()
        # Direct local maxima over an explicitly chosen demo height; no peak library.
        maxima = np.flatnonzero((y[1:-1] > y[:-2]) & (y[1:-1] >= y[2:]) & (y[1:-1] > 150)) + 1
        expected = original["2Theta"].iloc[maxima].tolist()
        result = output("analysis")["data"]
        _close([p["position"] for p in result["peaks"]], expected, "candidate_peaks_deg", checks, atol=0.03)
        assert result["matches"] == [] and result["fit"] is None
    else:
        assert original.Cycle.nunique() == 1
        for role, phase in (("charge", "Charge"), ("discharge", "Discharge")):
            expected = original[original.Step == phase].reset_index(drop=True)
            actual = pd.DataFrame(output(role, "table")).reset_index(drop=True)
            pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
            dt = np.diff(expected.Time_s)
            current = np.abs(expected.Current_A.to_numpy())
            integrated = float(np.sum(dt * (current[:-1] + current[1:]) / 2) / 3.6)
            supplied = float(expected.Capacity_mAh.max() - expected.Capacity_mAh.min())
            assert not np.isclose(integrated, supplied, rtol=0.01)
            checks[role] = {
                "rows": len(actual),
                "supplied_capacity_span_mAh": supplied,
                "current_time_integral_mAh": integrated,
                "capacity_consistent": False,
            }
    report = output("report")
    html_path = Path(report["artifacts"][0])
    html = html_path.read_text("utf-8")
    assert item["sha256"] in html and "data:image/png;base64," in html
    assert read_demo_bytes(case) == raw
    return {
        "dataset_id": case,
        "source_sha256": item["sha256"],
        "rows": len(original),
        "checks": checks,
        "report": str(html_path),
        "passed": True,
    }


def evaluate():
    return {
        "scope": "supplied demonstration files; deterministic graph and raw-data reference checks",
        "cases": [evaluate_case(item) for item in list_datasets()],
        "passed": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

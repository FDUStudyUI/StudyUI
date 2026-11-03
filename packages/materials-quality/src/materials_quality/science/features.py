"""Typed peak features from existing scientific results, without re-running algorithms."""

import numpy as np
import pandas as pd

FEATURE_COLUMNS = [
    "curve_id",
    "group",
    "peak_index",
    "peak_position",
    "height",
    "prominence",
    "fwhm",
    "area",
    "baseline",
    "x_unit",
    "intensity_unit",
]


def feature_units(frame, x_unit, intensity_unit):
    """Attach units only to columns actually present in this feature table."""
    units = {name: x_unit for name in ("peak_position", "fwhm")}
    units.update({name: intensity_unit for name in ("height", "prominence", "baseline")})
    units["area"] = f"{intensity_unit}*{x_unit}"
    units.update({c: "nm" for c in frame if c.endswith("_nm")})
    frame.attrs["units"] = {name: unit for name, unit in units.items() if name in frame}
    return frame


def features_for(operation, result, curve_id=None, group=None):
    """Return one row per measured peak; coordinates retain their declared units.

    Single-curve spectra/XRD have no required specimen ID. Callers processing a
    batch can supply that identity explicitly. Empty peak lists remain empty;
    the batch analyzer separately retains every specimen in its curve summary.
    """
    existing = getattr(result, "features", None)
    if existing is not None:
        frame = existing.copy(deep=True)
        if curve_id is not None:
            frame["curve_id"] = curve_id
        if group is not None:
            frame["group"] = group
        frame.attrs["units"] = {k: v for k, v in frame.attrs.get("units", {}).items() if k in frame}
        return frame
    if operation not in {"materials.spectra", "materials.xrd"}:
        return pd.DataFrame()
    parameters = result.data.get("transform", {}).get("parameters", {})
    x_unit = parameters.get("x_unit", result.data.get("x_unit", "unspecified"))
    intensity_unit = parameters.get("intensity_unit", parameters.get("y_unit", "unspecified"))
    rows = []
    for index, peak in enumerate(result.data.get("peaks", [])):
        sample = peak.get("index")
        base = np.nan
        if result.table is not None and "baseline" in result.table and isinstance(sample, int):
            if 0 <= sample < len(result.table):
                base = result.table["baseline"].iloc[sample]
        rows.append(
            {
                "curve_id": curve_id,
                "group": group,
                "peak_index": index,
                "peak_position": peak.get("position"),
                "height": peak.get("height"),
                "prominence": peak.get("prominence"),
                "fwhm": peak.get("fwhm"),
                "area": peak.get("area_between_bases"),
                "baseline": base,
                "x_unit": x_unit,
                "intensity_unit": intensity_unit,
            }
        )
    frame = pd.DataFrame(rows, columns=FEATURE_COLUMNS)
    if x_unit == "nm":
        frame["peak_position_nm"] = frame["peak_position"]
        frame["fwhm_nm"] = frame["fwhm"]
    return feature_units(frame, x_unit, intensity_unit)

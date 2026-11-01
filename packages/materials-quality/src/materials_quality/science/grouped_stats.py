"""Grouped descriptive statistics with explicit normalization and column units."""

import numpy as np
import pandas as pd

from .contracts import NodeResult, numeric_matrix, require_table
from .preprocessing import table_units


def grouped_summary(table, config=None):
    c = dict(config or {})
    keys = c.get("group_by") or [c.get("group")]
    if isinstance(keys, str):
        keys = [keys]
    columns = c.get("columns") or [c.get("column")]
    if not keys or len(set(keys)) != len(keys) or len(set(columns)) != len(columns):
        raise ValueError("group_by and columns must contain distinct column names")
    frame = require_table(table, [*keys, *columns])
    numeric_matrix(frame, columns)
    if frame[keys].isna().any().any():
        raise ValueError("group labels cannot be missing")
    mode = c.get("output_format", "long")
    if mode not in {"long", "wide"}:
        raise ValueError("output_format must be long or wide")
    normalize = c.get("normalize_by_group", False)
    if type(normalize) is not bool:
        raise ValueError("normalize_by_group must be boolean")
    units = table_units(frame, declared=c.get("units"))
    rows, warnings = [], []
    for labels, block in frame.groupby(keys[0] if len(keys) == 1 else keys, sort=False, observed=True):
        labels = (labels,) if len(keys) == 1 else labels
        for col in columns:
            values = block[col].to_numpy(dtype=float)
            if normalize:
                denominator = float(values.mean())
                if denominator == 0:
                    raise ValueError(f"cannot normalize zero within-group mean: {col}")
                values = values / denominator
            if len(values) == 1:
                warnings.append("Sample standard deviation is undefined for singleton groups.")
            rows.append(
                {
                    **dict(zip(keys, labels, strict=True)),
                    "variable": col,
                    "count": len(values),
                    "mean": float(values.mean()),
                    "std": float(values.std(ddof=1)) if len(values) > 1 else None,
                    "median": float(np.median(values)),
                    "q25": float(np.quantile(values, 0.25)),
                    "q75": float(np.quantile(values, 0.75)),
                    "min": float(values.min()),
                    "max": float(values.max()),
                }
            )
    result = pd.DataFrame(rows)
    statistic_columns = ["count", "mean", "std", "median", "q25", "q75", "min", "max"]
    column_units = {}
    if mode == "long":
        if units or normalize:
            result["unit"] = result.variable.map(lambda v: "1" if normalize else units.get(v, "unspecified"))
        known = {"1" if normalize else units.get(v, "unspecified") for v in columns}
        if len(known) == 1:
            column_units = {name: next(iter(known)) for name in statistic_columns if name != "count"}
    else:
        wide = []
        for labels, block in result.groupby(keys[0] if len(keys) == 1 else keys, sort=False, observed=True):
            labels = (labels,) if len(keys) == 1 else labels
            row = dict(zip(keys, labels, strict=True))
            for _, record in block.iterrows():
                for name in statistic_columns:
                    target = f"{record.variable}_{name}"
                    if target in row:
                        raise ValueError("wide output column name collision")
                    row[target] = record[name]
                    if name != "count" and (normalize or record.variable in units):
                        column_units[target] = "1" if normalize else units[record.variable]
            wide.append(row)
        result = pd.DataFrame(wide)
    result.attrs["units"] = {k: v for k, v in column_units.items() if k in result.columns}
    return NodeResult(
        table=result,
        data={
            "method": "grouped_descriptive",
            "ddof": 1,
            "parameters": c,
            "units": dict(result.attrs["units"]),
            "input_units": units,
            "normalization": "divide by within-group variable mean" if normalize else "none",
            "output_format": mode,
        },
        warnings=list(dict.fromkeys(warnings)),
    )

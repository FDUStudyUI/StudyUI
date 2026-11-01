"""Independent threshold segmentation with explicit per-image calibration."""

import hashlib
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import NodeResult
from .materials import microstructure


def analyze_images(paths, config=None):
    c = dict(config or {})
    if not isinstance(paths, (list, tuple)) or not paths:
        raise ValueError("select at least one image path")
    sources = [Path(p).expanduser().resolve() for p in paths]
    if len(set(sources)) != len(sources):
        raise ValueError("duplicate exact image paths")
    identities = {str(p): hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:16] for p in sources}
    records = c.get("calibrations")
    if records is None:
        records = []
    if isinstance(records, pd.DataFrame):
        records = records.to_dict("records")
    overrides = {}
    for row in records:
        key = row.get("path") or row.get("image_id")
        canonical = (
            str(Path(key).expanduser().resolve())
            if isinstance(key, str) and Path(key).is_absolute()
            else None
        )
        matches = [p for p in sources if canonical == str(p) or key == identities[str(p)]]
        if len(matches) != 1:
            raise ValueError("calibration must match an exact absolute path or exact image_id")
        target = str(matches[0])
        if target in overrides:
            raise ValueError("duplicate calibration identity")
        overrides[target] = row
    output = Path(c.get("output_dir") or tempfile.mkdtemp(prefix="studyui-image-batch-")).resolve()
    summaries = []
    regions = []
    artifacts = []
    warnings = []
    image_reports = []
    on_error = c.get("on_error", "stop")
    if on_error not in {"stop", "continue"}:
        raise ValueError("on_error must be stop or continue")
    for source in sources:
        image_id = identities[str(source)]
        row = overrides.get(str(source), {})
        settings = {k: v for k, v in c.items() if k not in {"calibrations", "on_error"}}
        supplied = {
            k: v for k, v in row.items() if k in {"pixel_size", "spatial_unit"} and v is not None and v != ""
        }
        settings.update(supplied)
        settings.update(
            {"path": str(source), "output_dir": str(output / image_id), "segmentation": "threshold"}
        )
        group = row.get("group") or c.get("group", "all")
        try:
            if supplied and set(supplied) != {"pixel_size", "spatial_unit"}:
                raise ValueError("per-image physical calibration needs both pixel_size and spatial_unit")
            result = microstructure(config=settings)
            feature = result.table.copy()
            feature.insert(0, "image_id", image_id)
            feature.insert(1, "source", str(source))
            feature.insert(2, "group", group)
            feature["length_unit"] = result.data["length_unit"]
            feature["area_unit"] = result.data["area_unit"]
            regions.append(feature)
            summary = {
                "image_id": image_id,
                "source": str(source),
                "group": group,
                "status": "completed",
                "particle_count": len(feature),
                "area_fraction": result.data["area_fraction"],
                "length_unit": result.data["length_unit"],
                "area_unit": result.data["area_unit"],
                "pixel_size": result.data["pixel_size"],
            }
            for metric in ["area", "equivalent_diameter"]:
                values = feature[metric].to_numpy(dtype=float)
                for name, q in [("q10", 0.1), ("median", 0.5), ("q90", 0.9)]:
                    summary[f"{metric}_{name}"] = float(np.quantile(values, q)) if len(values) else None
                summary[f"{metric}_mean"] = float(values.mean()) if len(values) else None
            summaries.append(summary)
            artifacts.extend(result.artifacts)
            warnings.extend(f"{image_id}: {w}" for w in result.warnings)
            image_reports.append(
                {
                    "image_id": image_id,
                    "source": str(source),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "data": result.data,
                    "artifacts": result.artifacts,
                    "warnings": result.warnings,
                }
            )
        except Exception as exc:
            if on_error == "stop":
                raise
            summaries.append(
                {
                    "image_id": image_id,
                    "source": str(source),
                    "group": group,
                    "status": "failed",
                    "error": str(exc),
                }
            )
    summary_frame = pd.DataFrame(summaries)
    features = (
        pd.concat(regions, ignore_index=True)
        if regions
        else pd.DataFrame(
            columns=["image_id", "source", "group", "area", "equivalent_diameter", "length_unit", "area_unit"]
        )
    )
    groups = []
    if "length_unit" not in summary_frame:
        summary_frame["length_unit"] = None
    completed = summary_frame.loc[summary_frame.status == "completed"]
    for (group, unit), block in completed.groupby(["group", "length_unit"], sort=False, observed=True):
        selected = features.loc[features.image_id.isin(block.image_id)]
        record = {
            "group": group,
            "length_unit": unit,
            "image_count": len(block),
            "particle_count": len(selected),
            "image_mean_area_fraction": float(block.area_fraction.mean()),
        }
        for metric in ["area", "equivalent_diameter"]:
            v = selected[metric].to_numpy(dtype=float)
            for name, q in [("q10", 0.1), ("median", 0.5), ("q90", 0.9)]:
                record[f"{metric}_{name}"] = float(np.quantile(v, q)) if len(v) else None
        groups.append(record)
    failed = int((summary_frame.status == "failed").sum())
    return NodeResult(
        table=summary_frame,
        features=features,
        artifacts=artifacts,
        warnings=warnings
        + [
            "Group particle quantiles pool detected 2-D regions within a shared declared unit; "
            "they are descriptive and do not treat particles as independent experimental replicates.",
            "Calibration is supplied by the user; scale bars are not automatically recognized. "
            "Pixel-only results are kept separate from physical units.",
        ],
        data={
            "images": image_reports,
            "group_summary": groups,
            "counts": {"total": len(sources), "completed": len(sources) - failed, "failed": failed},
            "execution_status": "failed" if failed == len(sources) else "partial" if failed else "completed",
            "parameters": c,
        },
    )

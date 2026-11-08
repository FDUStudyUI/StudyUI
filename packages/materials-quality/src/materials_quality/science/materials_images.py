"""Explicitly calibrated 2-D morphology and supervised pixel classification."""

from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from scipy.ndimage import gaussian_filter, gaussian_gradient_magnitude
from skimage.filters import threshold_otsu
from skimage.measure import label, regionprops

from .contracts import NodeResult, artifact_path, read_path
from .materials_curves import positive


def _image(config, data):
    if data is not None and "image" in data:
        source = "upstream image array"
        array = np.asarray(data["image"], dtype=float).copy()
    else:
        path = read_path(config, data)
        source = str(path)
        with Image.open(path) as image:
            # Keep luminance in 0..255 for RGB; grayscale images retain their native numeric scale.
            grayscale = image.mode in {"1", "L", "I", "F"} or image.mode.startswith("I;16")
            if not grayscale and image.mode != "RGB":
                image = image.convert("RGB")
            array = np.asarray(image).astype(float)
    if array.ndim == 3 and array.shape[-1] in (3, 4):
        array = array[..., :3] @ np.array([0.2126, 0.7152, 0.0722])
    if array.ndim != 2 or min(array.shape) < 2 or not np.isfinite(array).all():
        raise ValueError("image must be a finite 2-D grayscale or RGB image with at least 2x2 pixels")
    return array, source


def _segment(image, config, data):
    method = config.get("segmentation", "threshold")
    if method == "threshold":
        threshold = config.get("threshold", "otsu")
        if threshold == "otsu":
            if np.ptp(image) == 0:
                raise ValueError(
                    "Otsu threshold is undefined for a constant image; supply an explicit threshold"
                )
            threshold = float(threshold_otsu(image))
        else:
            threshold = float(threshold)
            if not np.isfinite(threshold):
                raise ValueError("threshold must be finite")
        foreground = config.get("foreground", "bright")
        if foreground not in {"bright", "dark"}:
            raise ValueError("foreground must be bright or dark")
        mask = image > threshold if foreground == "bright" else image <= threshold
        return mask, {"method": "threshold", "threshold": threshold, "foreground": foreground}, []
    if method != "ml":
        raise ValueError("segmentation must be threshold or ml")
    if data is None or "training_labels" not in data:
        raise ValueError(
            "supervised ML requires same-image training_labels (-1 unlabelled, 0 background, 1 foreground)"
        )
    labels = np.asarray(data["training_labels"])
    if labels.shape != image.shape or not np.isin(labels, [-1, 0, 1]).all():
        raise ValueError("training_labels must match image shape and contain only -1, 0, 1")
    selected = labels >= 0
    if set(np.unique(labels[selected])) != {0, 1}:
        raise ValueError("training_labels must include both background 0 and foreground 1 examples")
    if np.ptp(image) == 0:
        raise ValueError("constant image has no learnable intensity features")
    from sklearn.ensemble import RandomForestClassifier

    # Intensity-only is the transparent default. Texture features require representative boundary labels.
    normalized = (image - image.min()) / np.ptp(image)
    blur = gaussian_filter(normalized, 1)
    variance = np.maximum(gaussian_filter(normalized**2, 1) - blur**2, 0)
    features = np.stack(
        [
            normalized,
            blur,
            gaussian_filter(normalized, 2),
            gaussian_gradient_magnitude(normalized, 1),
            variance,
        ],
        axis=-1,
    )
    feature_names = [
        "intensity",
        "Gaussian sigma1",
        "Gaussian sigma2",
        "gradient sigma1",
        "local variance sigma1",
    ]
    feature_mode = config.get("ml_features", "intensity")
    if feature_mode == "intensity":
        features = features[..., :1]
        feature_names = feature_names[:1]
    elif feature_mode != "multiscale":
        raise ValueError("ml_features must be intensity or multiscale")
    seed = config.get("random_state", 0)
    if type(seed) is not int:
        raise ValueError("random_state must be an integer")
    classifier = RandomForestClassifier(
        n_estimators=100, random_state=seed, max_features=None, class_weight="balanced", n_jobs=1
    )
    classifier.fit(features[selected], labels[selected])
    predicted = classifier.predict(features.reshape(-1, features.shape[-1])).reshape(image.shape)
    info = {
        "method": "supervised random-forest pixel classifier",
        "training_pixels": int(selected.sum()),
        "label_counts": {str(i): int((labels == i).sum()) for i in (0, 1)},
        "random_state": seed,
        "features": feature_names,
        "n_estimators": 100,
        "pretrained_model": False,
    }
    return (
        predicted == 1,
        info,
        [
            "Segmentation uses user-labelled pixels from this image; "
            "no held-out accuracy or pretrained material model is claimed."
        ],
    )


def morphology(config, data):
    image, source = _image(config, data)
    warnings = []
    pixel_size = config.get("pixel_size")
    unit = config.get("spatial_unit")
    if pixel_size is None and unit is None:
        pixel_size, unit = 1.0, "px"
        warnings.append("No spatial calibration supplied: lengths are pixels and areas are pixel squared.")
    elif pixel_size is None or not isinstance(unit, str) or not unit.strip() or unit == "px":
        raise ValueError(
            "physical calibration requires positive pixel_size and a physical spatial_unit (for example um)"
        )
    else:
        pixel_size = positive(pixel_size, "pixel_size")
        if not np.isfinite(pixel_size * pixel_size):
            raise ValueError(
                "pixel_size is too large to produce finite calibrated areas; "
                "choose a smaller physical pixel size"
            )
    connectivity = config.get("connectivity", 1)
    if type(connectivity) is not int or connectivity not in {1, 2}:
        raise ValueError("connectivity must be 1 (4-neighbour) or 2 (8-neighbour)")
    minimum = config.get("min_area_pixels", 1)
    if type(minimum) is not int or minimum < 1:
        raise ValueError("min_area_pixels must be a positive integer")
    feature = config.get("feature", "particle")
    if feature not in {"particle", "pore", "grain"}:
        raise ValueError(
            "feature must be particle, pore, or grain, according to supplied image interpretation"
        )
    mask, segmentation, model_warnings = _segment(image, config, data)
    warnings.extend(model_warnings)
    initial_fraction = float(mask.mean())
    labelled = label(mask, connectivity=connectivity)
    counts = np.bincount(labelled.ravel())
    keep = counts >= minimum
    keep[0] = False
    mask = keep[labelled]
    labelled = label(mask, connectivity=connectivity)
    rows = []
    for region in regionprops(labelled):
        rows.append(
            {
                "label": int(region.label),
                "area_pixels": int(region.area),
                "area": float(region.area * pixel_size**2),
                "equivalent_diameter": float(region.equivalent_diameter_area * pixel_size),
                "major_axis_length": float(region.axis_major_length * pixel_size),
                "minor_axis_length": float(region.axis_minor_length * pixel_size),
                "centroid_row": float(region.centroid[0] * pixel_size),
                "centroid_column": float(region.centroid[1] * pixel_size),
                "touches_border": bool(
                    region.bbox[0] == 0
                    or region.bbox[1] == 0
                    or region.bbox[2] == image.shape[0]
                    or region.bbox[3] == image.shape[1]
                ),
            }
        )
    frame = pd.DataFrame(
        rows,
        columns=[
            "label",
            "area_pixels",
            "area",
            "equivalent_diameter",
            "major_axis_length",
            "minor_axis_length",
            "centroid_row",
            "centroid_column",
            "touches_border",
        ],
    )
    diameter = frame["equivalent_diameter"]
    summary = {
        "count": len(frame),
        "mean": float(diameter.mean()) if len(frame) else None,
        "median": float(diameter.median()) if len(frame) else None,
        "std": float(diameter.std(ddof=1)) if len(frame) > 1 else None,
        "min": float(diameter.min()) if len(frame) else None,
        "max": float(diameter.max()) if len(frame) else None,
    }
    mask_path = artifact_path(config, "materials_mask.png")
    labels_path = artifact_path(config, "materials_labels.npy")
    # Never overwrite an input image, even when overwrite=true was requested for artifacts.
    if source != "upstream image array" and Path(source) in {mask_path, labels_path}:
        raise ValueError("artifact output would overwrite the source image; select a different output_dir")
    Image.fromarray((mask * 255).astype(np.uint8)).save(mask_path)
    np.save(labels_path, labelled, allow_pickle=False)
    warnings.append(
        "Connected regions are 2-D image features; touching grains/particles are not automatically separated "
        "and area fraction is not a measured 3-D volume fraction."
    )
    if frame["touches_border"].any():
        warnings.append("Some components touch the image border; their apparent sizes can be truncated.")
    return NodeResult(
        table=frame,
        data={
            "source": source,
            "image_shape": list(image.shape),
            "segmentation": segmentation,
            "component_count": len(frame),
            "feature": feature,
            "area_fraction": float(mask.mean()),
            "area_fraction_before_size_filter": initial_fraction,
            "porosity_area_fraction": float(mask.mean()) if feature == "pore" else None,
            "length_unit": unit,
            "area_unit": f"{unit}^2",
            "pixel_size": pixel_size,
            "diameter_statistics": summary,
            "transform": {
                "parameters": dict(config),
                "raw_preserved": True,
                "affected_pixels": int(mask.size),
                "removed_foreground_pixels": int(round(initial_fraction * mask.size)) - int(mask.sum()),
            },
        },
        artifacts=[str(mask_path), str(labels_path)],
        warnings=warnings,
    )

"""Self-contained scientific figure style and evidence bundle; Python/Matplotlib only."""

import hashlib
import json
import textwrap
import warnings
from copy import deepcopy
from functools import wraps
from threading import RLock
from uuid import uuid4
from xml.etree import ElementTree as ET

import matplotlib as mpl
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib import pyplot as plt
from matplotlib.colors import is_color_like, to_hex
from PIL import Image

from materials_quality.common import json_value
from materials_quality.context import table_fingerprint

from .contracts import NodeResult, artifact_path
from .preprocessing import table_units

PALETTE = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#5F6B76", "#7B5AA6")
_LOCK = RLock()
PAPER_WIDTH_MM = 150.0
_SUFFIXES = {"png": ".png", "svg": ".svg", "pdf": ".pdf", "tiff": ".tiff"}


def series_style(label, config):
    label = str(label)
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    mapping = config.get("color_map", {})
    if not isinstance(mapping, dict) or any(
        not isinstance(k, str) or not is_color_like(v) for k, v in mapping.items()
    ):
        raise ValueError("color_map must map series labels to valid Matplotlib colors")
    return {
        "color": to_hex(mapping.get(label, PALETTE[digest[0] % len(PALETTE)])),
        "linestyle": ("-", "--", "-.", ":")[digest[1] % 4],
        "marker": ("o", "s", "^", "D", "v", "P", "X", "*")[digest[2] % 8],
    }


def _settings(config):
    profile = config.get("profile", "preview")
    if profile not in {"preview", "paper"}:
        raise ValueError("profile must be preview or paper")
    dpi = config.get("dpi", 300 if profile == "paper" else 150)
    if type(dpi) is not int or not 72 <= dpi <= 1200:
        raise ValueError("dpi must be an integer between 72 and 1200")
    formats = config.get("formats", ["png", "svg", "pdf", "tiff"] if profile == "paper" else ["png"])
    if (
        not isinstance(formats, list)
        or not formats
        or any(f not in {"png", "svg", "pdf", "tiff"} for f in formats)
    ):
        raise ValueError("formats must be a nonempty list of png/svg/pdf/tiff")
    kind = config.get("data_kind", "unspecified")
    if kind not in {"unspecified", "synthetic", "measured", "simulated", "derived"}:
        raise ValueError("data_kind must be unspecified/synthetic/measured/simulated/derived")
    available = {f.name for f in font_manager.fontManager.ttflist}
    fonts = [
        f
        for f in ("DejaVu Sans", "Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "WenQuanYi Zen Hei")
        if f in available
    ]
    return {
        "font.family": fonts or ["sans-serif"],
        "font.sans-serif": fonts or ["DejaVu Sans"],
        "font.size": 9 if profile == "paper" else 10,
        "axes.labelsize": 10,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.fontsize": 8.5,
        "axes.linewidth": 0.8,
        "lines.linewidth": 1.6,
        "lines.markersize": 4,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#52606D",
        "text.color": "#243746",
        "axes.labelcolor": "#243746",
        "xtick.color": "#52606D",
        "ytick.color": "#52606D",
        "legend.frameon": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "text.usetex": False,
        "savefig.facecolor": "white",
        "axes.formatter.use_mathtext": True,
    }


def plot_operation(function):
    """Serialize this library's rendering and restore rc/RNG-independent state on every path."""

    @wraps(function)
    def wrapped(table=None, *, config=None, data=None, tables=None):
        c = deepcopy(config or {})
        settings = _settings(c)
        if isinstance(table, pd.DataFrame):
            c["units"] = table_units(table, data, c.get("units"))
            c["_figure_source"] = {
                "table_sha256": table_fingerprint(table),
                "rows": len(table),
                "columns": list(table.columns),
            }
        c["_series_styles"] = {}
        c["_owned_figures"] = []
        with _LOCK, mpl.rc_context(settings):
            try:
                return function(table, config=c, data=data, tables=tables)
            finally:
                for owned in c["_owned_figures"]:
                    plt.close(owned)

    return wrapped


def styled_series(label, config):
    style = series_style(label, config)
    config.setdefault("_series_styles", {})[str(label)] = style
    return style


def figure(config):
    if "figsize" in config:
        width, height = config["figsize"]
    elif config.get("profile") == "paper" or "width_mm" in config:
        width = float(config.get("width_mm", PAPER_WIDTH_MM)) / 25.4
        height = float(config.get("height_mm", float(config.get("width_mm", PAPER_WIDTH_MM)) * 0.66)) / 25.4
    else:
        width, height = 7, 4.6
    if not np.isfinite([width, height]).all() or not 2 <= width <= 30 or not 2 <= height <= 30:
        raise ValueError("figure size must be between 2 and 30 inches per dimension")
    formats = config.get(
        "formats", ["png", "svg", "pdf", "tiff"] if config.get("profile") == "paper" else ["png"]
    )
    dpi = max(
        config.get("dpi", 300 if config.get("profile") == "paper" else 150), 600 if "tiff" in formats else 0
    )
    if width * height * dpi * dpi > 50_000_000:
        raise ValueError("requested raster exceeds 50 million pixels; reduce figure size or dpi")
    fig, ax = plt.subplots(figsize=(width, height), layout="constrained")
    config.setdefault("_owned_figures", []).append(fig)
    fig.get_layout_engine().set(rect=(0, 0.065, 1, 0.935))
    ax.grid(axis="y", color="#CAD2DA", alpha=0.4, linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(direction="out", length=3, width=0.7)
    return fig, ax


def legend(ax):
    handles, labels = ax.get_legend_handles_labels()
    if not labels:
        return
    labels = [textwrap.fill(label, 23) for label in labels]
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(1.015, 1), borderaxespad=0)


def _layout_qa(fig):
    renderer = fig.canvas.get_renderer()
    outer = fig.bbox
    issues = []
    texts = list(fig.texts)
    for ax in fig.axes:
        texts.extend([ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts])
        if ax.get_legend() is not None:
            texts.extend(ax.get_legend().get_texts())
    for text in texts:
        if text.get_visible() and text.get_text():
            box = text.get_window_extent(renderer)
            if (
                box.x0 < outer.x0 - 2
                or box.y0 < outer.y0 - 2
                or box.x1 > outer.x1 + 2
                or box.y1 > outer.y1 + 2
            ):
                issues.append("Text exceeds figure canvas: " + text.get_text()[:70])
    return issues


def finish(fig, config, name, payload):
    profile = config.get("profile", "preview")
    dpi = config.get("dpi", 300 if profile == "paper" else 150)
    formats = config.get("formats", ["png", "svg", "pdf", "tiff"] if profile == "paper" else ["png"])
    formats = list(dict.fromkeys(["png", *formats]))
    source = config.get("_figure_source", {})
    kind = config.get("data_kind", "unspecified")
    identity = {
        "synthetic": "SYNTHETIC DEMONSTRATION",
        "simulated": "SIMULATED DATA",
        "measured": "MEASURED DATA",
        "derived": "DERIVED DATA",
    }.get(kind, "")
    definition = payload.get("statistical_definition") or payload.get("error_definition") or ""
    footer = " | ".join(
        s for s in [identity, f"n = {source['rows']} input rows" if source else "", str(definition)] if s
    )
    note = fig.text(0.02, 0.014, "", fontsize=8, va="bottom", color="#52606D")
    renderer = fig.canvas.get_renderer()
    available_width = fig.bbox.width * 0.96
    lines, current = [], ""
    for word in footer.split():
        candidate = (current + " " + word).strip()
        width = renderer.get_text_width_height_descent(candidate, note.get_fontproperties(), False)[0]
        if current and width > available_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    note.set_text("\n".join(lines))
    bottom = max(0.065, (len(lines) * 10 + 6) / (fig.get_figheight() * 72))
    fig.get_layout_engine().set(rect=(0, bottom, 1, 1 - bottom))
    verification, paths, notices = [], [], []
    base = artifact_path(config, name + ".png")
    if any(base.with_suffix("." + suffix).exists() for suffix in [*formats, "json", "md"]):
        base = base.with_stem(base.stem + "-" + uuid4().hex[:8])
    try:
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always", UserWarning)
            fig.canvas.draw()
            notices += _layout_qa(fig)
            for fmt in formats:
                path = base.with_suffix(_SUFFIXES[fmt])
                kwargs = {"pil_kwargs": {"compression": "tiff_lzw"}} if fmt == "tiff" else {}
                fig.savefig(path, dpi=600 if fmt == "tiff" else dpi, format=fmt, **kwargs)
                record = {
                    "path": str(path),
                    "format": fmt,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                if fmt in {"png", "tiff"}:
                    with Image.open(path) as image:
                        image.load()
                        if min(image.size) < 100 or np.asarray(image.convert("RGB")).std() < 1:
                            raise ValueError("exported figure is empty or unreadable")
                        record.update(size=list(image.size), dpi=list(image.info.get("dpi", (dpi, dpi))))
                elif fmt == "svg":
                    tree = ET.parse(path)
                    if not tree.getroot().tag.endswith("svg"):
                        raise ValueError("invalid SVG export")
                    record["editable_text_elements"] = len(
                        tree.findall(".//{http://www.w3.org/2000/svg}text")
                    )
                else:
                    import fitz

                    with fitz.open(path) as doc:
                        record.update(
                            page_points=[doc[0].rect.width, doc[0].rect.height],
                            text_characters=len(doc[0].get_text()),
                        )
                paths.append(str(path))
                verification.append(record)
            notices += [
                str(w.message)
                for w in emitted
                if "Glyph" in str(w.message) or "constrained_layout" in str(w.message)
            ]
    finally:
        plt.close(fig)
    contract = {
        "backend": "python-matplotlib",
        "profile": profile,
        "data_kind": kind,
        "evidence_role": config.get(
            "evidence_role",
            "comparison" if name.startswith(("performance", "spectra", "mechanics")) else "diagnostic",
        ),
        "purpose": config.get("purpose", config.get("title", name.replace("-", " "))),
        "width_mm": fig.get_figwidth() * 25.4,
        "height_mm": fig.get_figheight() * 25.4,
        "series_styles": dict(sorted(config.get("_series_styles", {}).items())),
        "statistical_definition": definition,
        "observations_displayed": payload.get("observations_displayed"),
        "font_families": list(mpl.rcParams["font.sans-serif"]),
        "minimum_text_points": 8,
        "units": config.get("units", {}),
        "layout_warnings": sorted(set(notices)),
    }
    data = json_value(
        {
            **payload,
            "figure_contract": contract,
            "figure_verification": verification,
            "figure_previews": [paths[0]],
        }
    )
    if profile == "paper":
        manifest = base.with_suffix(".json")
        manifest.write_text(
            json.dumps({"source": source, **data}, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
            newline="\n",
        )
        caption = base.with_suffix(".md")
        caption.write_text(
            ("Synthetic demonstration. " if kind == "synthetic" else "")
            + str(config.get("title", name.replace("-", " ").capitalize()))
            + ". "
            + footer
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        paths += [str(manifest), str(caption)]
    return NodeResult(data=data, artifacts=paths, warnings=sorted(set(notices)))

"""Compile declared material methods to native, editable workflow forms.

Version 1 handles one monotonic curve per table. Batch and instrument-specific
tasks continue to use the existing batch nodes and general workflow builder.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

from materials_quality.science.material_tasks import assess_protocol

PROTOCOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "task": {"type": "string", "enum": ["mechanics", "spectra", "xrd", "battery", "thermal"]},
        "path": {"type": "string"},
        "x": {"type": "string"},
        "y": {"type": "string"},
        "x_unit": {"type": "string"},
        "y_unit": {"type": "string"},
        "fit_range": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
        "yield_offset": {"type": "number", "exclusiveMinimum": 0},
        "baseline": {"type": "string", "enum": ["none", "linear"]},
        "prominence": {"type": "number", "exclusiveMinimum": 0},
        "signal_kind": {"type": "string", "enum": ["intensity", "absorbance", "transmittance"]},
        "thermal_kind": {"type": "string", "enum": ["tg", "dsc"]},
        "heating_rate": {"type": "number", "exclusiveMinimum": 0},
        "atmosphere": {"type": "string"},
        "cell_col": {"type": "string"},
        "charge_col": {"type": "string"},
        "c_rate_col": {"type": "string"},
        "requested_metric": {"type": "string", "enum": ["retention", "cycle_life", "fade_rate", "capacity"]},
        "has_reference_pattern": {"type": "boolean"},
        "claims_phase_id": {"type": "boolean"},
        "file_format": {"type": "string", "enum": ["auto", "table", "xy"]},
        "sort": {"type": "boolean"},
        "import_options": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "sheet": {"type": ["string", "integer"]},
                "header": {"type": ["integer", "null"], "minimum": 0},
                "range": {"type": "string"},
                "delimiter": {"type": "string"},
                "encoding": {"type": "string"},
            },
        },
    },
    "required": ["task", "path", "x", "y", "x_unit", "y_unit"],
}


def load_protocol_input(spec):
    from materials_quality.science.io_nodes import instrument_import, table_import

    path = Path(spec["path"]).resolve()
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".tsv", ".txt", ".xlsx", ".xlsm", ".dat", ".xy", ".xye"}:
        raise ValueError("请选择表格文件或数值 XY 仪器文件。")
    if path.stat().st_size > 20_000_000:
        raise ValueError("任务预览上限为 20 MB；更大文件可使用现有批量或仪器节点。")
    raw = path.read_bytes()
    options = spec.get("import_options", {})
    selected = spec.get("file_format", "auto")
    numeric_xy = suffix in {".dat", ".xy", ".xye"}
    if selected == "auto" and suffix == ".txt":
        import re

        from materials_quality.science.io_nodes import _decode

        content, _ = _decode(path, options)
        first = next(
            (
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.lstrip().startswith(("#", ";"))
            ),
            "",
        )
        try:
            numeric_xy = len([float(v) for v in re.split(r"[,;\s]+", first)]) >= 2
        except ValueError:
            numeric_xy = False
    if selected == "xy" or (selected == "auto" and numeric_xy):
        key = "io.instrument_import"
        config = {
            "path": str(path),
            "format": "xy",
            **({"encoding": options["encoding"]} if options.get("encoding") else {}),
        }
        result = instrument_import(config=config)
    else:
        key = "io.table_import"
        config = {"path": str(path), "delimiter": "auto", **options}
        result = table_import(config=config)
    return result.table, raw, key, config


def compile_material_protocol(spec):
    return _compile_material_protocol(spec, load_protocol_input(spec))


def _compile_material_protocol(spec, input_bundle):
    from jsonschema import validate

    from materials_quality.science.catalog import entries
    from materials_quality.science.ui_config_import import config_to_form

    validate(spec, PROTOCOL_SCHEMA)
    task = spec["task"]
    required = (
        ["fit_range", "yield_offset"]
        if task == "mechanics"
        else []
        if task == "battery"
        else ["baseline", "prominence"]
    )
    missing = [name for name in required if name not in spec]
    if missing:
        raise ValueError("请确认方法参数：" + ", ".join(missing))
    path = Path(spec["path"]).resolve()
    table, raw, import_key, import_config = input_bundle
    x, y = spec["x"], spec["y"]
    if x == y or x not in table or y not in table:
        raise ValueError("横纵坐标必须对应文件中两个不同的实际列。")
    values = table[[x, y]].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if len(values) < 3 or not np.isfinite(values).all():
        raise ValueError("需要至少三个有限数值点；请先处理缺失或无效值。")
    if task != "battery":
        if spec.get("sort", False):
            values = values[np.argsort(values[:, 0], kind="stable")]
        if not np.all(np.diff(values[:, 0]) > 0):
            raise ValueError("此协议需要单条坐标严格单调递增的曲线；多曲线请使用批量分析节点。")
    if not spec["x_unit"].strip() or not spec["y_unit"].strip():
        raise ValueError("请确认横纵坐标单位。")
    analysis = {"x": x, "y": y}
    if spec.get("sort", False):
        analysis["sort"] = True
    if task == "mechanics":
        low, high = spec["fit_range"]
        if not (math.isfinite(low) and math.isfinite(high) and values[0, 0] <= low < high <= values[-1, 0]):
            raise ValueError("fit_range 必须在实测坐标范围内且上下限递增。")
        if ((values[:, 0] >= low) & (values[:, 0] <= high)).sum() < 3:
            raise ValueError("fit_range 至少需要三个实际测量点。")
        if spec["x_unit"] not in {"fraction", "%"} or spec["y_unit"] not in {"Pa", "kPa", "MPa", "GPa"}:
            raise ValueError("应变/应力单位不受支持，请在表单中确认并转换。")
        analysis.update(
            strain_unit=spec["x_unit"],
            stress_unit=spec["y_unit"],
            fit_range=spec["fit_range"],
            yield_offset=spec["yield_offset"],
            fracture_confirmed=False,
        )
    elif task == "battery":
        if spec["y_unit"] not in {"Ah", "mAh"}:
            raise ValueError("电池容量单位仅支持 Ah 或 mAh。")
    elif task == "thermal":
        if spec["x_unit"] not in {"degC", "K", "s", "min"}:
            raise ValueError("热分析横坐标单位仅支持 degC、K、s 或 min。")
        if spec["y_unit"] not in {"%", "mg", "g", "W/g", "mW/mg", "mW/g", "W", "mW"}:
            raise ValueError("热分析纵坐标单位不受支持。")
        if not math.isfinite(spec["prominence"]):
            raise ValueError("prominence 必须是有限正数。")
        analysis.update(
            kind=spec.get("thermal_kind", "tg"),
            x_unit=spec["x_unit"],
            y_unit=spec["y_unit"],
            baseline={"method": spec["baseline"]},
            prominence=spec["prominence"],
        )
    else:
        if task == "xrd" and spec["x_unit"] != "deg":
            raise ValueError("XRD 协议要求 2θ 坐标单位 deg。")
        if not math.isfinite(spec["prominence"]):
            raise ValueError("prominence 必须是有限正数。")
        analysis.update(
            x_unit=spec["x_unit"], baseline={"method": spec["baseline"]}, prominence=spec["prominence"]
        )
        analysis["intensity_unit" if task == "xrd" else "y_unit"] = spec["y_unit"]
    assessment = (
        {"status": "ready", "checks": [], "next_actions": []}
        if task in {"battery", "thermal"}
        else assess_protocol(table, spec)
    )
    if assessment["status"] != "ready":
        raise ValueError("；".join(assessment["next_actions"]))
    from materials_quality.science.runtime_guards import evaluate_runtime_guards

    guard_table = table.sort_values(x, kind="stable") if spec.get("sort", False) else table
    guard_cfg = {
        "strain_col": x,
        "stress_col": y,
        "x_col": x,
        "y_col": y,
        "sort": bool(spec.get("sort", False)),
    }
    if task == "mechanics":
        guard_cfg["fit_range"] = spec["fit_range"]
    elif task == "spectra":
        guard_cfg["mode"] = spec.get("signal_kind", "absorbance")
    elif task == "xrd":
        guard_cfg.update(
            has_reference_pattern=bool(spec.get("has_reference_pattern", False)),
            claims_phase_id=bool(spec.get("claims_phase_id", False)),
        )
    elif task == "battery":
        guard_cfg.update(
            cycle_col=x,
            c_rate_col=spec.get("c_rate_col"),
            requested_metric=spec.get("requested_metric", "retention"),
        )
    elif task == "thermal":
        guard_cfg.update(
            temp_col=x,
            signal_col=y,
            heating_rate=spec.get("heating_rate"),
            atmosphere=spec.get("atmosphere"),
        )
    guard_report = evaluate_runtime_guards(task, guard_table, config=guard_cfg)
    if not guard_report.passed:
        raise ValueError("；".join(item.message for item in guard_report.findings))
    catalog = {item["key"]: item for item in entries()}
    actions = []

    def node(alias, key, config, col):
        form = config_to_form(key, config)
        if form.get("ui_mode") != "form":
            raise ValueError(f"协议参数无法无损转换为可视化表单：{key}")
        actions.append(
            {
                "op": "add_node",
                "node_id": alias,
                "component_type": catalog[key]["class_name"],
                "config": form,
                "x": col * 340,
                "y": 100,
            }
        )

    def edge(source, output, target, port):
        actions.append({"op": "connect", "source": source, "output": output, "target": target, "input": port})

    node("raw", import_key, import_config, 0)
    if task == "battery":
        battery_cfg = {
            "mode": "summary",
            "cell_column": spec.get("cell_col", "cell_id"),
            "cycle_column": x,
            "discharge_capacity_column": y,
            "charge_capacity_column": spec.get("charge_col", ""),
            "capacity_unit": spec["y_unit"],
            "calculate_efficiency": bool(spec.get("charge_col")),
        }
        actions.append(
            {
                "op": "add_node",
                "node_id": "analysis",
                "component_type": "BatteryCycles",
                "config": battery_cfg,
                "x": 340,
                "y": 100,
            }
        )
        node(
            "plot",
            "viz.performance",
            {
                "method": "scatter",
                "x": "cycle",
                "y": "discharge_capacity_ah",
                "units": {"cycle": "1", "discharge_capacity_ah": "Ah"},
                "formats": ["png"],
                "title": "电池循环放电容量曲线",
            },
            2,
        )
        node("report", "export.report", {"format": "html", "title": "电池循环分析报告"}, 3)
        edge("raw", "table", "analysis", "input_table")
        edge("analysis", "features", "plot", "input_table")
        for source in ["raw", "analysis", "plot"]:
            edge(source, "report", "report", "reports")
        node("features", "export.table", {"format": "csv"}, 2)
        actions[-1]["y"] = 450
        edge("analysis", "features", "features", "input_table")
        edge("features", "report", "report", "reports")
        return {
            "actions": actions,
            "protocol": {
                "id": "materials." + task,
                "version": 1,
                "parameters": dict(spec, path=str(path)),
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "row_count": len(table),
                "assessment": assessment,
                "guard_report": guard_report.to_dict(),
                "method_basis": "用户确认参数；单电芯基准循环容量保持率计算，禁止跨电芯归一化与单循环外推"
                "寿命",
            },
        }
    node("analysis", "materials." + task, analysis, 1)
    plot_x, plot_y = ("strain_fraction", "stress_MPa") if task == "mechanics" else ("x", "raw_y")
    node(
        "plot",
        "viz.spectra",
        {
            "method": "line",
            "x": plot_x,
            "columns": [plot_y],
            "units": {
                plot_x: "1" if task == "mechanics" else spec["x_unit"],
                plot_y: "MPa" if task == "mechanics" else spec["y_unit"],
            },
            "formats": ["png"],
            "title": "应力—应变曲线" if task == "mechanics" else "实测信号曲线",
        },
        2,
    )
    node("report", "export.report", {"format": "html", "title": "材料分析报告"}, 3)
    edge("raw", "table", "analysis", "input_table")
    edge("raw", "report", "analysis", "input_data")
    edge("analysis", "table", "plot", "input_table")
    for source in ["raw", "analysis", "plot"]:
        edge(source, "report", "report", "reports")
    if task != "mechanics":
        node("features", "export.table", {"format": "csv"}, 2)
        actions[-1]["y"] = 450
        edge("analysis", "features", "features", "input_table")
        edge("features", "report", "report", "reports")
    return {
        "actions": actions,
        "protocol": {
            "id": "materials." + task,
            "version": 1,
            "parameters": dict(spec, path=str(path)),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "row_count": len(table),
            "assessment": assessment,
            "guard_report": guard_report.to_dict(),
            "method_basis": "用户确认参数；单曲线描述分析；XRD 与光谱输出候选峰，不自动归属物相或模式",
        },
    }

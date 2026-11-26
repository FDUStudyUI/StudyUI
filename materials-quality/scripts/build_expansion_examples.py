"""Portable form-based lessons for specimen joins, calibration and new analyses."""

import argparse
import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

from components.materials_batch.battery_cycles import BatteryCycles
from components.materials_batch.electrical import ElectricalAnalysis
from components.materials_skills.research_executor import ResearchSkillExecutor
from components.materials_skills.research_planner import ResearchSkillPlanner
from components.materials_sources.science_fixture_bundle import ScienceFixtureBundle
from scripts.build_batch_examples import _dump, _id, _science

ROOT = Path(__file__).resolve().parents[1]


def _source(suffix, frame):
    records = json.dumps({"records": frame.to_dict("records")}, allow_nan=False)
    return _id(ScienceFixtureBundle(), suffix).set(bundle_base64=base64.b64encode(records.encode()).decode())


def _calibration(suffix, source, **settings):
    return _science("preprocess.normalize", suffix, input_table=source.build_table, **settings)


def _report(case, title, *reports):
    return _science("export.report", case + "-report", cfg_title=title, reports=list(reports))


def _specimen_flow():
    ids = [f"{i:03}" for i in range(1, 7)]
    groups = ["A"] * 3 + ["B"] * 3
    frames = {"specimen-master": pd.DataFrame({"sample_id": ids, "batch": groups})}
    spectra, current = [], []
    for sample, group, center, slope in zip(
        ids, groups, [700, 705, 710, 730, 735, 740], [5, 4, 2, 10, 8, 5], strict=True
    ):
        for x in range(620, 861, 5):
            y = 2 + 5 * np.exp(-0.5 * ((x - center) / 10) ** 2)
            spectra.append({"sample_id": sample, "curve_id": "opt-" + sample, "group": group, "x": x, "y": y})
        for voltage in [-1, -0.5, 0, 0.5, 1]:
            current.append(
                {
                    "sample_id": sample,
                    "curve_id": "iv-" + sample,
                    "voltage": voltage,
                    "current": slope * voltage + 0.2,
                }
            )
    frames.update({"specimen-spectra": pd.DataFrame(spectra), "specimen-iv": pd.DataFrame(current)})
    master, optical_source, electrical_source = (_source(key, frame) for key, frame in frames.items())
    planner = _id(ResearchSkillPlanner(), "specimen-optical-plan").set(
        input_table=optical_source.build_table,
        task="spectra",
        data_kind="synthetic",
        x_unit="nm",
        y_unit="counts",
        window_confirmed=True,
        window_low=650,
        window_high=850,
        prominence_mode="指定突出度阈值",
        prominence=0.5,
        unit_mode="按样品汇总后比较",
        unit_column="sample_id",
        unit_confirmed=True,
        request="提取合成光谱窗口候选，并关联同批样品的 I-V 特征",
    )
    optical = _id(ResearchSkillExecutor(), "specimen-optical").set(
        input_table=optical_source.build_table,
        plan=planner.build_plan,
    )
    optical_columns = _science(
        "preprocess.filter",
        "specimen-optical-columns",
        input_table=optical.build_table,
        cfg_columns=["experimental_unit", "curve_id", "window_candidate_nm", "ambiguous"],
        cfg_rename={"curve_id": "optical_curve_id", "experimental_unit": "sample_id"},
    )
    corrected = _calibration(
        "specimen-calibration",
        electrical_source,
        cfg_method="blank_subtract",
        cfg_calibration_signal="current",
        cfg_calibration_input_unit="mA",
        cfg_calibration_blank=0.2,
        cfg_calibration_output="current_corrected",
        cfg_calibration_source="合成例的零电流偏置参考",
    )
    iv = _id(ElectricalAnalysis(), "specimen-iv-analysis").set(
        input_table=corrected.build_table,
        mode="iv",
        sample_id="sample_id",
        current="current_corrected",
        current_unit="mA",
        voltage_unit="V",
        voltage_min="-1",
        voltage_max="1",
    )
    merged = _science(
        "preprocess.merge",
        "specimen-merge",
        input_table=master.build_table,
        input_tables=[optical_columns.build_table, iv.build_features],
        cfg_method="specimen",
        cfg_on=["sample_id"],
    )
    plot = _science(
        "viz.performance",
        "specimen-plot",
        input_table=merged.build_table,
        cfg_x="window_candidate_nm",
        cfg_y="resistance_ohm",
        cfg_group="batch",
        cfg_data_kind="synthetic",
        cfg_formats=["png"],
    )
    report = _report(
        "specimen",
        "同批样品的光谱峰位与电阻",
        corrected.build_report,
        iv.build_report,
        optical.build_report,
        merged.build_report,
        plot.build_report,
    )
    nodes = [
        master,
        optical_source,
        planner,
        optical,
        optical_columns,
        electrical_source,
        corrected,
        iv,
        merged,
        plot,
        report,
    ]
    payload = _dump(nodes, "材料扩展01｜同批光谱与电学（合成）")
    positions = [
        (0, 0),
        (0, 300),
        (430, 300),
        (860, 300),
        (1290, 300),
        (0, 1150),
        (860, 1150),
        (1290, 1150),
        (1720, 300),
        (2150, 300),
        (2580, 300),
    ]
    coords = {node.get_id(): xy for node, xy in zip(nodes, positions, strict=True)}
    for vertex in payload["data"]["nodes"]:
        x, y = coords[vertex["id"]]
        vertex["position"] = {"x": x, "y": y}
    return payload, frames


def _mechanics_flow():
    raw = pd.read_csv(ROOT / "examples/science/materials/fixtures/synthetic_tensile.csv")
    frame = raw[["strain"]].assign(bridge_mV=raw["stress"] / 2 + 1)
    source = _source("mechanics-raw", frame)
    calibrated = _calibration(
        "mechanics-calibration",
        source,
        cfg_method="linear_calibration",
        cfg_calibration_signal="bridge_mV",
        cfg_calibration_input_unit="mV",
        cfg_calibration_output="stress_MPa",
        cfg_calibration_output_unit="MPa",
        cfg_calibration_source="合成标准对，已知换算 stress = 2 × (bridge − 1)",
        cfg_calibration_standards=[
            {"signal": 1, "value": 0},
            {"signal": 76, "value": 150},
            {"signal": 151, "value": 300},
        ],
    )
    planner = _id(ResearchSkillPlanner(), "mechanics-plan").set(
        input_table=calibrated.build_table,
        task="mechanics",
        data_kind="synthetic",
        request="用经线性标定的应力求拉伸模量",
        x_column="strain",
        y_column="stress_MPa",
        single_sample=True,
        strain_unit="fraction",
        stress_unit="MPa",
        fit_confirmed=True,
        fit_low=0,
        fit_high=0.0008,
    )
    mechanics = _id(ResearchSkillExecutor(), "mechanics-analysis").set(
        input_table=calibrated.build_table,
        plan=planner.build_plan,
    )
    report = _report("mechanics", "拉伸信号标定与力学指标", calibrated.build_report, mechanics.build_report)
    return _dump([source, calibrated, planner, mechanics, report], "材料扩展02｜拉伸信号标定（合成）"), {
        "mechanics-raw": frame,
    }


def _photoresponse_flow():
    time = np.arange(14)
    delta = np.minimum(np.clip((time - 2) * 2, 0, 8), np.clip((12 - time) * 2, 0, 8))
    frame = pd.DataFrame({"curve_id": "pulse-1", "time": time, "current": delta + 1})
    source = _source("photoresponse-raw", frame)
    photo = _id(ElectricalAnalysis(), "photoresponse-analysis").set(
        input_table=source.build_table,
        mode="photoresponse",
        current_unit="uA",
        time_unit="s",
        baseline_start="0",
        baseline_end="1",
        light_on="2",
        on_plateau_start="6",
        on_plateau_end="7",
        light_off="8",
        recovery_end="13",
    )
    export = _science("export.table", "photoresponse-export", input_table=photo.build_features)
    report = _report("photoresponse", "光响应开关的幅值和时间", photo.build_report, export.build_report)
    payload = _dump([source, photo, export, report], "材料扩展03｜光响应开关（合成）")
    return payload, {"photoresponse-raw": frame}


def _battery_flow():
    frame = pd.DataFrame(
        {
            "cell_id": ["A"] * 3 + ["B"] * 3,
            "cycle": [1, 2, 3] * 2,
            "discharge_capacity": [2, 1.8, 1.6, 1, 0.95, 0.9],
        }
    )
    source = _source("battery-capacity", frame)
    battery = _id(BatteryCycles(), "battery-analysis").set(input_table=source.build_table, capacity_unit="Ah")
    plot = _science(
        "viz.performance",
        "battery-plot",
        input_table=battery.build_features,
        cfg_x="cycle",
        cfg_y="retention_pct",
        cfg_group="cell_id",
        cfg_data_kind="synthetic",
        cfg_formats=["png"],
    )
    report = _report("battery", "逐电芯容量保持率", battery.build_report, plot.build_report)
    return _dump([source, battery, plot, report], "材料扩展04｜逐电芯容量保持率（合成）"), {
        "battery-capacity": frame,
    }


def build_examples(destination=None):
    target = Path(destination or ROOT / "examples/expansion_flows")
    target.mkdir(parents=True, exist_ok=True)
    cases = {}
    for case, builder in {
        "specimen": _specimen_flow,
        "mechanics": _mechanics_flow,
        "photoresponse": _photoresponse_flow,
        "battery": _battery_flow,
    }.items():
        payload, tables = builder()
        (target / f"{case}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        for name, frame in tables.items():
            frame.to_csv(target / f"{name}.csv", index=False, encoding="utf-8-sig")
        cases[case] = payload
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    build_examples(parser.parse_args().output)

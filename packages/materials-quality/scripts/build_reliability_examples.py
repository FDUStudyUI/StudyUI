"""Portable synthetic lessons for candidate rules, independent units and failures."""

import argparse
import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd

from components.materials_skills.research_executor import ResearchSkillExecutor
from components.materials_skills.research_planner import ResearchSkillPlanner
from examples.science_flows.fixture_source import ScienceFixtureBundle
from scripts.build_batch_examples import _dump, _id

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    x = np.arange(400.0, 901.0)
    y = 10 * np.exp(-0.5 * ((x - 530) / 10) ** 2)
    y += 2 * np.exp(-0.5 * ((x - 730) / 6) ** 2) + np.exp(-0.5 * ((x - 790) / 6) ** 2)
    competing = pd.DataFrame({"curve_id": ["particle-001"] * len(x), "x": x, "y": y})
    nested = []
    for group, shift in (("A", 0), ("B", 30)):
        for unit in range(3):
            for replicate in range(2):
                center = 700 + shift + unit * 5 + replicate
                nested.append(
                    pd.DataFrame({"x": x, "y": 5 * np.exp(-0.5 * ((x - center) / 7) ** 2)}).assign(
                        curve_id=f"{group}-{unit}-{replicate}", sample_id=f"{group}-{unit}", group=group
                    )
                )
    small = pd.DataFrame(
        [
            {"group": group, "variable": "window_candidate", "value": delta + i, "sample_id": f"{group}{i}"}
            for group, delta in (("A", 700), ("B", 730))
            for i in range(2)
        ]
    )
    failed = pd.DataFrame({"curve_id": ["invalid-signal"] * 3, "x": [700, 710, 720], "y": ["bad"] * 3})
    return {
        "competing": competing,
        "nested": pd.concat(nested, ignore_index=True),
        "small_n": small,
        "all_failed": failed,
    }


def build_examples(destination=None):
    target = Path(destination or ROOT / "examples/reliability_flows")
    target.mkdir(parents=True, exist_ok=True)
    common = {
        "task": "spectra",
        "x_unit": "nm",
        "y_unit": "counts",
        "window_confirmed": True,
        "window_low": 650,
        "window_high": 850,
        "prominence_mode": "指定突出度阈值",
        "prominence": 0.5,
    }
    settings = {
        "competing": {
            **common,
            "request": "比较窗口内竞争候选，分别查看最大突出度与最红端规则",
            "selection_rule": "突出度最大候选",
        },
        "nested": {
            **common,
            "request": "每个样品两条曲线，先按样品汇总再比较",
            "unit_mode": "按样品汇总后比较",
            "unit_column": "sample_id",
            "unit_confirmed": True,
        },
        "small_n": {
            "task": "contrast",
            "request": "每组只有两个独立单位，默认仅描述",
            "design": "independent",
            "unit_column": "sample_id",
            "sample_column": "sample_id",
            "value_unit": "nm",
        },
        "all_failed": {**common, "request": "非数值信号保留失败状态与可读报告"},
    }
    names = {
        "competing": "可靠性01｜竞争候选与选择规则",
        "nested": "可靠性02｜曲线与独立样品",
        "small_n": "可靠性03｜小样本仅描述",
        "all_failed": "可靠性04｜失败状态与追溯",
    }
    output = {}
    for case, frame in fixtures().items():
        records = frame.to_dict("records")
        source = _id(ScienceFixtureBundle(), case).set(
            bundle_base64=base64.b64encode(json.dumps({"records": records}).encode()).decode()
        )
        planner = _id(ResearchSkillPlanner(), case).set(
            input_table=source.build_table, data_kind="synthetic", **settings[case]
        )
        executor = _id(ResearchSkillExecutor(), case).set(
            input_table=source.build_table, plan=planner.build_plan
        )
        payload = _dump([source, planner, executor], names[case])
        (target / f"{case}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        frame.to_csv(target / f"{case}.csv", index=False, encoding="utf-8-sig")
        output[case] = payload
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    build_examples(parser.parse_args().output)

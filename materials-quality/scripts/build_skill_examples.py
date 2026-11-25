"""Portable three-node skill lessons with embedded synthetic records."""

import argparse
import base64
import json
from pathlib import Path

import pandas as pd

from components.materials_skills.research_executor import ResearchSkillExecutor
from components.materials_skills.research_planner import ResearchSkillPlanner
from components.materials_sources.science_fixture_bundle import ScienceFixtureBundle
from scripts.build_batch_examples import _dump, _id
from scripts.build_research_examples import synthetic_records

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    tensile = pd.read_csv(ROOT / "examples/science/materials/fixtures/synthetic_tensile.csv")
    frames = [
        tensile.assign(stress=tensile.stress * (1 + i / 10), sample_id=f"synthetic-{i + 1:02}")
        for i in range(20)
    ]
    contrast = [
        {
            "group": g,
            "variable": "strength",
            "value": i + delta + r / 10,
            "sample_id": f"{g}{i}-{r}",
            "experimental_unit": f"{g}{i}",
        }
        for g, delta in [("A", 0), ("B", 4)]
        for i in range(4)
        for r in range(3)
    ]
    return {
        "spectra": synthetic_records(),
        "mechanics": pd.concat(frames).to_dict("records"),
        "contrast": contrast,
    }


def build_examples(destination=None):
    target = Path(destination or ROOT / "examples/skill_flows")
    target.mkdir(parents=True, exist_ok=True)
    settings = {
        "spectra": {
            "request": "比较两组的光谱候选峰，绘制均值与四分位带",
            "x_unit": "nm",
            "y_unit": "counts",
            "window_confirmed": True,
            "window_low": 650,
            "window_high": 850,
            "baseline": "constant",
            "baseline_value": 2,
        },
        "mechanics": {
            "request": "批量计算拉伸弹性模量和偏移强度",
            "strain_unit": "fraction",
            "stress_unit": "MPa",
            "fit_confirmed": True,
            "fit_low": 0,
            "fit_high": 0.0008,
        },
        "contrast": {
            "request": "按独立试验单位比较两组材料强度",
            "design": "independent",
            "value_unit": "MPa",
        },
    }
    values = {}
    for task, records in fixtures().items():
        source = _id(ScienceFixtureBundle(), task).set(
            bundle_base64=base64.b64encode(json.dumps({"records": records}).encode()).decode()
        )
        planner = _id(ResearchSkillPlanner(), task).set(
            input_table=source.build_table, task=task, data_kind="synthetic", **settings[task]
        )
        executor = _id(ResearchSkillExecutor(), task).set(
            input_table=source.build_table, plan=planner.build_plan
        )
        title = {
            "spectra": "科研技能01｜批量光谱与候选峰",
            "mechanics": "科研技能02｜20份拉伸试样",
            "contrast": "科研技能03｜独立试验单位对照研究",
        }[task]
        payload = _dump([source, planner, executor], title)
        (target / f"{task}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
        pd.DataFrame(records).to_csv(target / f"{task}.csv", index=False, encoding="utf-8-sig")
        values[task] = payload
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    build_examples(parser.parse_args().output)

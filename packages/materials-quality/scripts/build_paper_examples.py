"""Portable visual lessons for source-backed methods, prediction and local repair."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.build_batch_examples import _dump, _science
from scripts.build_expansion_examples import _source

ROOT = Path(__file__).resolve().parents[1]


def spectral_table():
    x = np.linspace(600, 850, 101)
    return pd.DataFrame({"x": x, "y": 2 + 0.003 * (x - 600) + 5 * np.exp(-(((x - 720) / 15) ** 2))})


def regression_table():
    rng = np.random.default_rng(7301)
    x = rng.normal(size=(40, 6))
    table = pd.DataFrame(x, columns=[f"band_{i}" for i in range(6)])
    table["target"] = x @ np.array([2.0, -0.5, 1.0, 0, 0.3, 0]) + rng.normal(0, 0.01, len(x))
    table["sample_id"] = [f"sample-{i:02}" for i in range(len(x))]
    table["split"] = ["train"] * 30 + ["test"] * 10
    return table


def _report(name, evidence, *others):
    return _science(
        "export.report",
        name,
        input_table=evidence.build_table,
        input_data=evidence.build_report,
        reports=list(others),
        cfg_format="html",
    )


def build_examples(destination=None):
    target = Path(destination or ROOT / "examples/paper_flows")
    target.mkdir(parents=True, exist_ok=True)
    cases = {}
    table = spectral_table()
    source = _source("paper-spectrum", table)
    methods = _science(
        "lit.method_recommend",
        "paper-methods",
        input_table=source.build_table,
        cfg_query="AsLS",
        cfg_goal="baseline",
        cfg_signal_type="raman_intensity",
        cfg_x_unit="nm",
        cfg_y_unit="counts",
        cfg_positive_peaks="yes",
    )
    spectrum = _science(
        "materials.spectra",
        "paper-spectrum",
        input_table=source.build_table,
        cfg_x="x",
        cfg_y="y",
        cfg_x_unit="nm",
        cfg_y_unit="counts",
        cfg_baseline_method="asls",
        cfg_prominence=0.5,
        cfg_prominence_enabled="是",
        cfg_prominence_mode="显式阈值",
    )
    evidence = _science(
        "lit.result_evidence",
        "paper-evidence",
        input_table=spectrum.build_features,
        input_data=spectrum.build_report,
        cfg_columns=["peak_position", "fwhm", "area"],
        cfg_hypothesis="合成数据只验证算法链路；实际材料机制需要额外对照。",
    )
    report = _report("paper-spectrum-report", evidence, methods.build_report, spectrum.build_report)
    cases["01_spectrum_evidence"] = _dump(
        [source, methods, spectrum, evidence, report], "论文借鉴01｜光谱方法与结果证据（合成）"
    )
    table.to_csv(target / "spectrum.csv", index=False)

    table = regression_table()
    source = _source("paper-pls", table)
    model = _science(
        "materials.chemometrics",
        "paper-pls",
        input_table=source.build_table,
        cfg_method="pls",
        cfg_feature_columns=[f"band_{i}" for i in range(6)],
        cfg_target_column="target",
        cfg_sample_column="sample_id",
        cfg_split_column="split",
        cfg_n_components=4,
        cfg_cv_folds=3,
    )
    evidence = _science(
        "lit.result_evidence",
        "paper-pls-evidence",
        input_table=model.build_table,
        input_data=model.build_report,
        cfg_columns=["observed", "prediction", "residual"],
        cfg_identity_column="sample_id",
        cfg_max_rows=40,
    )
    report = _report("paper-pls-report", evidence, model.build_report)
    cases["02_pls_holdout"] = _dump(
        [source, model, evidence, report], "论文借鉴02｜PLS 训练与独立测试（合成）"
    )
    table.to_csv(target / "pls_samples.csv", index=False)

    table = pd.DataFrame({"group": ["A"] * 4 + ["B"] * 4, "value": [1.0, 2, 3, 4, 6, 7, 8, 9]})
    source = _source("paper-plan", table)
    plan = _science("materials.analysis_plan", "paper-plan", input_table=source.build_table)
    evidence = _science(
        "lit.result_evidence",
        "paper-plan-evidence",
        input_table=plan.build_table,
        input_data=plan.build_report,
        cfg_columns=["count", "mean"],
        cfg_identity_column="group",
    )
    report = _report("paper-plan-report", evidence, plan.build_report)
    cases["03_local_repair"] = _dump(
        [source, plan, evidence, report], "论文借鉴03｜分步执行与局部重算（合成）"
    )
    table.to_csv(target / "group_samples.csv", index=False)

    methods = _science(
        "lit.method_recommend",
        "paper-blocked",
        cfg_query="SNV",
        cfg_goal="normalization",
        cfg_signal_type="darkfield_intensity",
        cfg_x_unit="nm",
        cfg_y_unit="counts",
        cfg_allow_intensity_loss="no",
        cfg_nonzero_variance="yes",
    )
    report = _science(
        "export.report",
        "paper-blocked-report",
        input_table=methods.build_table,
        reports=[methods.build_report],
        cfg_title="绝对强度比较：不适用方法说明",
    )
    cases["04_incompatible_method"] = _dump([methods, report], "论文借鉴04｜拒绝不适用的标准化方法")
    for name, payload in cases.items():
        (target / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    return cases


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    print(json.dumps({"flows": list(build_examples(parser.parse_args().output))}, ensure_ascii=False))

"""Scientific conditions, inference and native V2 integration regressions."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from materials_quality.science.contrast_study import contrast_study
from materials_quality.skills.planning import make_plan, validate_plan


def spectrum():
    x = np.arange(400.0, 901.0)
    y = 10 * np.exp(-0.5 * ((x - 530) / 10) ** 2)
    y += 2 * np.exp(-0.5 * ((x - 730) / 6) ** 2) + np.exp(-0.5 * ((x - 790) / 6) ** 2)
    return pd.DataFrame({"curve_id": ["one"] * len(x), "x": x, "y": y})


def options():
    return {"x_unit": "nm", "y_unit": "counts", "peak_window": [650, 850]}


def unit_table(n=3):
    return pd.DataFrame(
        [
            {"group": g, "sample_id": f"{g}{i}", "variable": "peak", "value": i + d}
            for g, d in (("A", 0.0), ("B", 4.0))
            for i in range(n)
        ]
    )


def test_same_entity_sample_and_independent_unit_column_is_legal():
    f = unit_table()
    p = make_plan(
        f,
        task="contrast",
        parameters={"experimental_unit": "sample_id", "design": "independent", "value_unit": "nm"},
    )
    assert p["ready"], p["issues"]
    validate_plan(f, p)
    assert p["analysis_contract"]["roles"]["experimental_unit"] == "sample_id"


def test_contrast_difference_interval_matches_independent_welch_oracle():
    f = unit_table(4)
    r = contrast_study(f, config={"experimental_unit": "sample_id"})
    pair = r.features.iloc[0]
    expected = stats.ttest_ind([0, 1, 2, 3], [4, 5, 6, 7], equal_var=False).confidence_interval()
    assert pair.mean_difference_ci_low == pytest.approx(expected.low)
    assert pair.mean_difference_ci_high == pytest.approx(expected.high)
    assert pair.ci_method == "welch_t"
    assert pair.ci_status == "estimated"


def test_small_sample_default_is_descriptive_and_model_based_is_explicit():
    f = unit_table(2)
    r = contrast_study(f, config={"experimental_unit": "sample_id"})
    pair = r.features.iloc[0]
    assert pair.status == "descriptive_only_small_n"
    assert pd.isna(pair.p_raw)
    assert pd.isna(pair.mean_difference_ci_low)
    r = contrast_study(f, config={"experimental_unit": "sample_id", "small_sample_policy": "model_based"})
    assert r.features.iloc[0].ci_status == "estimated_small_n_model_assumptions"
    assert pd.notna(r.features.iloc[0].p_raw)


def test_single_unit_is_retained_descriptively_not_dropped_or_inferred():
    r = contrast_study(unit_table(1), config={"experimental_unit": "sample_id"})
    assert len(r.table) == 2
    assert r.features.iloc[0].n_a == 1
    assert pd.isna(r.features.iloc[0].p_raw)


def test_contract_change_with_same_values_invalidates_plan():
    from materials_quality.science.table_contract import attach_contract, make_contract

    f = spectrum()
    c = make_contract(f, granularity="point", roles={"curve_id": "curve_id", "x": "x", "response": "y"})
    f = attach_contract(f, c)
    p = make_plan(f, task="spectra", parameters=options())
    assert p["ready"], p["issues"]
    changed = make_contract(f, granularity="point", roles=c["roles"], units_state={"x": "user_confirmed"})
    altered = attach_contract(f, changed)
    with pytest.raises(ValueError, match="数据|contract|契约|stale"):
        validate_plan(altered, p)


def test_wrong_granularity_is_rejected_before_science_execution():
    from materials_quality.science.table_contract import attach_contract, make_contract

    f = spectrum()
    f = attach_contract(f, make_contract(f, granularity="group_summary", roles={"response": "y"}))
    p = make_plan(f, task="spectra", parameters=options())
    assert not p["ready"]
    assert any(i["field"] == "contract" for i in p["issues"])


def test_spectral_rule_and_threshold_plan_controls_reach_actual_execution(tmp_path):
    from materials_quality.skills.execution import execute_plan

    f = spectrum()
    p = make_plan(
        f,
        task="spectra",
        parameters={
            **options(),
            "selection_rule": "redmost",
            "prominence_mode": "absolute",
            "prominence": 0.5,
        },
    )
    assert p["ready"], p["issues"]
    r = execute_plan(f, p, tmp_path)
    assert r.table.iloc[0].window_candidate_nm == 790
    assert r.table.iloc[0].lambda10_nm == 790
    assert r.report["tables"]["table"]["contract"]["granularity"] == "curve"
    assert r.report["data"]["group_inference"]["status"] == "descriptive_only_no_independence_declaration"


def test_curve_independence_cannot_be_implicitly_or_model_confirmed():
    p = make_plan(spectrum(), task="spectra", parameters={**options(), "unit_mode": "curve"})
    assert not p["ready"]
    assert any(i["field"] == "unit_confirmed" for i in p["issues"])


def test_nested_curves_aggregate_to_sample_units_before_difference_ci(tmp_path):
    from materials_quality.skills.execution import execute_plan

    x = np.arange(650.0, 851.0)
    frames = []
    for group, shift in (("A", 0), ("B", 30)):
        for unit in range(3):
            for curve in range(2):
                center = 700 + shift + unit * 5 + curve
                frames.append(
                    pd.DataFrame(
                        {
                            "curve_id": f"{group}-{unit}-{curve}",
                            "group": group,
                            "sample_id": f"{group}-{unit}",
                            "x": x,
                            "y": 5 * np.exp(-0.5 * ((x - center) / 7) ** 2),
                        }
                    )
                )
    f = pd.concat(frames, ignore_index=True)
    p = make_plan(
        f,
        task="spectra",
        parameters={
            **options(),
            "unit_mode": "sample",
            "experimental_unit": "sample_id",
            "unit_confirmed": True,
        },
    )
    assert p["ready"], p["issues"]
    r = execute_plan(f, p, tmp_path)
    assert len(r.table) == 12
    pair = r.report["data"]["group_inference"]["pairwise"][0]
    assert pair["n_a"] == pair["n_b"] == 3
    assert pair["mean_difference"] == pytest.approx(-30)
    assert pair["mean_difference_ci_low"] < -30 < pair["mean_difference_ci_high"]
    declared = r.report["tables"]["table"]["contract"]
    assert declared["roles"]["experimental_unit"] == "experimental_unit"
    assert declared["experimental_design"]["confirmed"]
    downstream = make_plan(
        r.table,
        task="contrast",
        parameters={
            "variable": "selection_rule",
            "value": "window_candidate_nm",
            "sample_id": "curve_id",
            "experimental_unit": "curve_id",
            "design": "independent",
            "value_unit": "nm",
        },
    )
    assert not downstream["ready"]


def test_native_forms_use_choices_and_show_only_relevant_threshold_fields():
    from components.materials_skills.research_planner import ResearchSkillPlanner

    n = ResearchSkillPlanner().set(task="spectra")
    fields = n.to_frontend_node()["data"]["node"]["template"]
    assert "最红端候选" in fields["selection_rule"]["options"]
    assert fields["selection_rule"]["show"]
    assert not fields["noise_low"]["show"]
    n.set(prominence_mode="参考噪声窗口")
    fields = n.to_frontend_node()["data"]["node"]["template"]
    assert fields["noise_low"]["show"]
    assert "config_json" not in fields


def test_noise_interval_requires_confirmation_and_whole_curve_ids_are_legal():
    p = make_plan(spectrum(), task="spectra", parameters={**options(), "prominence_mode": "noise_reference"})
    assert not p["ready"]
    assert any(i["field"] == "noise_window" for i in p["issues"])
    assert make_plan(spectrum(), task="spectra", parameters=options())["ready"]


def test_all_failed_spectra_still_export_report_and_empty_detection_state(tmp_path):
    from materials_quality.skills.execution import execute_plan

    f = pd.DataFrame({"curve_id": ["bad"] * 3, "x": [700, 710, 720], "y": ["bad"] * 3})
    p = make_plan(f, task="spectra", parameters=options())
    r = execute_plan(f, p, tmp_path)
    assert r.report["status"] == "failed"
    assert r.report["counts"]["failed"] == 1
    assert r.groups.iloc[0].n_eligible == 0
    assert any(path.endswith("report.html") for path in r.artifacts)


def test_contract_units_cannot_be_overridden_when_dataframe_units_are_absent():
    from materials_quality.science.table_contract import attach_contract, make_contract

    f = unit_table()
    c = make_contract(
        f,
        granularity="point",
        roles={"response": "value"},
        units_state={"source": "instrument", "units": {"value": "Pa"}},
    )
    f = attach_contract(f, c)
    p = make_plan(
        f,
        task="contrast",
        parameters={"experimental_unit": "sample_id", "design": "independent", "value_unit": "MPa"},
    )
    assert not p["ready"]
    assert any(i["field"] == "value_unit" for i in p["issues"])


def test_generated_science_output_cache_respects_changed_contract():
    import asyncio

    from components.materials_preprocessing.preprocess_filter import SciencePreprocessFilter
    from materials_quality.batch.native import native_frame
    from materials_quality.science.table_contract import attach_contract, make_contract

    f = pd.DataFrame({"value": [1, 2]})
    c = make_contract(f, granularity="point", roles={"response": "value"})
    node = SciencePreprocessFilter().set(input_table=native_frame(attach_contract(f, c)))
    first = asyncio.run(node.resolve_output("table"))
    changed = make_contract(
        f, granularity="point", roles={"response": "value"}, units_state={"source": "confirmed"}
    )
    node.set(input_table=native_frame(attach_contract(f, changed)))
    second = asyncio.run(node.resolve_output("table"))
    assert first.attrs["contract"]["contract_sha256"] != second.attrs["contract"]["contract_sha256"]


def test_choice_value_mapping_can_omit_legacy_auto_without_conflicting_threshold(monkeypatch):
    from types import SimpleNamespace

    from materials_quality.science import ui_schema
    from materials_quality.science.ui_types import field

    specs = [
        field(
            "prominence_mode",
            "阈值",
            "choice",
            default="兼容自动",
            choices=["兼容自动", "指定"],
            value_map={"兼容自动": "legacy_auto", "指定": "absolute"},
            omit_values=["legacy_auto"],
        )
    ]
    monkeypatch.setattr(ui_schema, "fields_for", lambda key: specs)
    node = SimpleNamespace(config_mode="form", _parameters={}, cfg_prominence_mode="兼容自动")
    assert "prominence_mode" not in ui_schema.form_config(node, "materials.spectra")
    node.cfg_prominence_mode = "指定"
    assert ui_schema.form_config(node, "materials.spectra")["prominence_mode"] == "absolute"


def test_direct_contrast_cannot_bypass_coordinate_point_contract():
    from materials_quality.science.table_contract import attach_contract, make_contract

    f = unit_table()
    f = attach_contract(f, make_contract(f, granularity="point", roles={"response": "value"}))
    p = make_plan(
        f,
        task="contrast",
        parameters={"experimental_unit": "sample_id", "design": "independent", "value_unit": "nm"},
    )
    assert not p["ready"]
    with pytest.raises(ValueError, match="contract|契约|粒度"):
        contrast_study(f, config={"experimental_unit": "sample_id"})


def test_confidence_band_requires_independence_declaration():
    p = make_plan(spectrum(), task="spectra", parameters={**options(), "band": "ci95"})
    assert not p["ready"]
    assert any(i["field"] == "band" for i in p["issues"])


def test_sample_confidence_band_uses_unit_curves_and_small_sample_policy(monkeypatch, tmp_path):
    from materials_quality.skills import tasks

    x = np.arange(650.0, 851.0)
    records = []
    for group, shift in (("A", 0), ("B", 30)):
        for unit in range(3):
            for replicate in range(2):
                frame = pd.DataFrame({"x": x, "y": 5 * np.exp(-0.5 * ((x - 700 - shift - unit) / 7) ** 2)})
                records.append(
                    frame.assign(
                        curve_id=f"{group}{unit}-{replicate}", sample_id=f"{group}{unit}", group=group
                    )
                )
    f = pd.concat(records, ignore_index=True)
    p = make_plan(
        f,
        task="spectra",
        parameters={
            **options(),
            "band": "ci95",
            "unit_mode": "sample",
            "experimental_unit": "sample_id",
            "unit_confirmed": True,
        },
    )
    captured = []
    monkeypatch.setattr(tasks, "_plot", lambda result, call, frame, config: captured.append((frame, config)))
    tasks.spectral_task(f, p["parameters"], tmp_path)
    frame, config = captured[0]
    assert frame.groupby("group")[config["curve_id"]].nunique().tolist() == [3, 3]
    assert config["independence_confirmed"] is True


def test_untrusted_model_proposal_cannot_confirm_scientific_conditions():
    p = make_plan(
        spectrum(),
        proposal={
            "task": "spectra",
            "parameters": {**options(), "unit_mode": "curve", "unit_confirmed": True},
        },
    )
    assert not p["ready"]
    assert any(i["field"] == "unit_confirmed" for i in p["issues"])


@pytest.mark.parametrize(
    "override", [{"group": "other_group"}, {"value": "other_value"}, {"variable": "other_variable"}]
)
def test_direct_contrast_cannot_override_declared_roles(override):
    from materials_quality.science.table_contract import attach_contract, make_contract

    f = unit_table(3).assign(other_group=["A", "B"] * 3, other_value=100.0, other_variable="other")
    f = attach_contract(
        f,
        make_contract(
            f,
            granularity="measurement",
            roles={
                "response": "value",
                "group": "group",
                "variable": "variable",
                "experimental_unit": "sample_id",
            },
            experimental_design={"kind": "independent", "confirmed": True},
        ),
    )
    with pytest.raises(ValueError, match="contract|契约"):
        contrast_study(f, config={"experimental_unit": "sample_id", **override})


def test_difference_interval_and_descriptive_units_survive_export(tmp_path):
    from materials_quality.skills.execution import execute_plan

    f = unit_table(3)
    p = make_plan(
        f,
        task="contrast",
        parameters={"experimental_unit": "sample_id", "design": "independent", "value_unit": "MPa"},
    )
    r = execute_plan(f, p, tmp_path)
    assert r.features.attrs["units"]["mean_difference_ci_low"] == "MPa"
    assert r.groups.attrs["units"]["mean"] == "MPa"
    assert r.report["tables"]["features"]["contract"]["units_state"]["units"]["mean_difference"] == "MPa"

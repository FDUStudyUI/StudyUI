"""Native forms and serialized connections must exercise the actual skill runtime."""

import asyncio
import json

import pytest
from lfx.graph import Graph
from lfx.schema import DataFrame


def planner():
    from components.materials_skills.research_planner import ResearchSkillPlanner

    return ResearchSkillPlanner()


def test_planner_form_shows_only_task_relevant_fields_and_readable_preview():
    node = planner().set(task="spectra")
    data = node.to_frontend_node()["data"]["node"]["template"]
    assert data["x_unit"]["show"]
    assert not data["fit_confirmed"]["show"]
    assert not data["design"]["show"]
    assert "config_json" not in data
    node = planner().set(task="mechanics")
    data = node.to_frontend_node()["data"]["node"]["template"]
    assert data["fit_confirmed"]["show"]
    assert not data["x_unit"]["show"]
    f = DataFrame({"strain": [0, 0.0004, 0.0008, 0.004], "stress": [0, 80, 160, 203]})
    node.set(
        input_table=f,
        single_sample=True,
        strain_unit="fraction",
        stress_unit="MPa",
        fit_confirmed=True,
        fit_low=0,
        fit_high=0.0008,
    )
    assert node.build_plan().data["ready"]
    assert "可执行" in node.build_preview().text


def test_executor_cache_invalidation_pending_plans_and_native_outputs(tmp_path):
    from components.materials_skills.research_executor import ResearchSkillExecutor

    f = DataFrame({"strain": [0, 0.0004, 0.0008, 0.004], "stress": [0, 80, 160, 203]})
    p = (
        planner()
        .set(
            input_table=f,
            task="mechanics",
            single_sample=True,
            strain_unit="fraction",
            stress_unit="MPa",
            fit_confirmed=True,
            fit_low=0,
            fit_high=0.0008,
        )
        .build_plan()
    )
    node = ResearchSkillExecutor().set(input_table=f, plan=p, output_directory=str(tmp_path))
    asyncio.run(node.resolve_output("table"))
    assert node.build_table().iloc[0]["elastic_modulus_MPa"] == pytest.approx(200000)
    assert len(node.build_artifacts()) >= 5
    assert node.build_report().data["provenance"]["raw_preserved"]
    assert node.build_table().attrs["units"]["elastic_modulus_MPa"] == "MPa"
    f.loc[0, "stress"] = 7
    with pytest.raises(ValueError, match="数据|input"):
        asyncio.run(node.resolve_output("table"))


def test_real_runtime_output_cache_rechecks_changed_planner_inputs():
    f = DataFrame({"curve_id": ["a"] * 3, "x": [650, 700, 750], "y": [1, 3, 1]})
    n = planner().set(input_table=f, task="spectra", x_unit="nm", y_unit="counts")
    first = asyncio.run(n.resolve_output("plan"))
    assert not first.data["ready"]
    n.set(window_confirmed=True, window_low=650, window_high=850)
    second = asyncio.run(n.resolve_output("plan"))
    assert second.data["ready"]
    n.set(window_low=720)
    third = asyncio.run(n.resolve_output("plan"))
    assert third.data["parameters"]["peak_window"] == [720, 850]


@pytest.mark.parametrize("case", ["spectra", "mechanics", "contrast"])
def test_portable_skill_graphs_execute_after_json_roundtrip(case, tmp_path):
    from scripts.build_skill_examples import build_examples

    payload = build_examples(tmp_path)[case]
    assert len(payload["data"]["nodes"]) == 3
    graph = Graph.from_payload(json.loads(json.dumps(payload)))
    for step in graph.start():
        if hasattr(step, "valid"):
            assert step.valid, step
    r = graph.get_vertex("ResearchSkillExecutor-" + case).results
    assert r["report"].data["status"] == "completed"
    if case == "spectra":
        assert len(r["features"]) == 16
        assert r["groups"]["mean"].tolist() == pytest.approx([715, 755])
    if case == "mechanics":
        assert len(r["table"]) == 20
        assert r["table"].iloc[0]["elastic_modulus_MPa"] == pytest.approx(200000)
    assert r["artifacts"]

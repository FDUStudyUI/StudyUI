"""Behavioral checks for bounded, authenticated pure-science DAG execution."""

import importlib

import pandas as pd
import pytest

from materials_quality.science.contracts import NodeResult


def api():
    return importlib.import_module("materials_quality.science.analysis_plan")


def diamond():
    return [
        {"id": "root", "operation": "preprocess.filter"},
        {"id": "left", "operation": "preprocess.filter", "dependencies": ["root"]},
        {"id": "right", "operation": "preprocess.filter", "dependencies": ["root"]},
        {"id": "join", "operation": "preprocess.filter", "dependencies": ["left", "right"]},
    ]


def inputs():
    return {"input": pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})}


def test_diamond_reuses_success_and_invalidates_only_changed_branch():
    runner = api().AnalysisPlanRunner()
    steps, source = diamond(), inputs()
    first = runner.run(steps, source)
    assert first.execution_count == 4
    again = runner.run(steps, source, previous=first)
    assert again.execution_count == 0 and again.reuse_count == 4
    steps[1]["config"] = {"conditions": [{"column": "x", "op": "ge", "value": 2}]}
    changed = runner.run(steps, source, previous=again)
    assert changed.execution_count == 2 and changed.reuse_count == 2
    assert changed.records["right"].status == "reused"
    assert changed.records["join"].result.table.x.tolist() == [2, 3]
    assert source["input"].x.tolist() == [1, 2, 3]


def test_failure_blocks_only_descendants_and_explicit_repair_reuses_other_branches():
    runner = api().AnalysisPlanRunner()
    steps = diamond()
    steps[1]["config"] = {"columns": ["missing"]}
    failed = runner.run(steps, inputs())
    assert failed.records["left"].status == "failed"
    assert failed.records["join"].status == "blocked"
    assert failed.records["right"].status == "success"
    assert failed.execution_count == 3
    assert "missing" in failed.records["left"].diagnostics["error"]
    steps[1]["config"] = {"columns": ["x"]}
    fixed = runner.run(steps, inputs(), previous=failed)
    assert fixed.execution_count == 2 and fixed.reuse_count == 2
    assert fixed.status == "success"


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda s: s[0].update(dependencies=["join"]), "cycle"),
        (lambda s: s[1].update(dependencies=["absent"]), "unknown dependency"),
        (lambda s: s[1].update(operation="does.not.exist"), "pure operation"),
        (lambda s: s[1].update(operation="export.table"), "pure operation"),
        (lambda s: s[1].update(operation="lit.extract", config={"method": "llm"}), "pure operation"),
        (lambda s: s[1].update(operation="io.table_import"), "pure operation"),
        (lambda s: s[1].update(id="root"), "duplicate"),
        (lambda s: s[1].update(input="absent"), "unknown input"),
    ],
)
def test_invalid_graph_rejected_before_execution(change, match):
    steps = diamond()
    change(steps)
    with pytest.raises(ValueError, match=match):
        api().AnalysisPlanRunner().run(steps, inputs())


def test_result_tamper_invalidates_cache_even_when_attacker_updates_plain_digest():
    runner = api().AnalysisPlanRunner()
    first = runner.run(diamond(), inputs())
    first.records["left"].result.table.loc[0, "x"] = 900
    first.records["left"].result_fingerprint = api().fingerprint(first.records["left"].result)
    after = runner.run(diamond(), inputs(), previous=first)
    assert after.records["left"].reason == "cache_integrity_mismatch"
    assert after.records["left"].result.table.x.tolist() == [1, 2, 3]
    assert after.records["join"].status == "success"
    assert after.records["right"].status == "reused"
    with pytest.raises(ValueError, match="process-local"):
        runner.run(diamond(), inputs(), previous={"records": first.records})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.table.__setitem__("x", [3, 2, 1]),
        lambda r: r.table.attrs.update(units={"x": "MPa"}),
        lambda r: r.data.update(experiment="changed"),
        lambda r: r.table.index.rename("sample_id", inplace=True),
    ],
)
def test_data_metadata_and_units_mutations_invalidate_results(mutation):
    runner = api().AnalysisPlanRunner()
    source = {"input": NodeResult(table=inputs()["input"], data={"experiment": "initial"})}
    old = runner.run(diamond(), source)
    mutation(source["input"])
    new = runner.run(diamond(), source, previous=old)
    assert new.execution_count == 4 and new.reuse_count == 0


def test_equal_results_from_changed_parameters_still_invalidate_descendants():
    steps = diamond()
    runner = api().AnalysisPlanRunner()
    first = runner.run(steps, inputs())
    steps[1]["config"] = {"columns": ["x", "y"]}
    second = runner.run(steps, inputs(), previous=first)
    assert second.records["join"].status == "success"
    assert second.execution_count == 2


def test_budget_stops_new_calls_and_can_resume_explicitly():
    runner = api().AnalysisPlanRunner(max_executions=2)
    first = runner.run(diamond(), inputs())
    assert first.execution_count == 2
    assert first.records["right"].status == "budget_exceeded"
    assert first.records["join"].status == "blocked"
    second = runner.run(diamond(), inputs(), previous=first)
    assert second.execution_count == 2 and second.status == "success"
    with pytest.raises(ValueError, match="max_steps"):
        api().AnalysisPlanRunner(max_steps=3).run(diamond(), inputs())


def test_input_and_cached_results_are_isolated_copies():
    runner = api().AnalysisPlanRunner()
    first = runner.run(diamond(), inputs())
    second = runner.run(diamond(), inputs(), previous=first)
    second.records["root"].result.table.iloc[0, 0] = 100
    assert first.records["root"].result.table.iloc[0, 0] == 1
    assert second.records["left"].result.table.iloc[0, 0] == 1


def test_wrapper_returns_serializable_audit_and_terminal_output():
    module = api()
    first = module.analysis_plan(inputs()["input"], config={"steps": diamond()})
    assert first.data["execution_count"] == 4
    assert first.table.status.tolist() == ["success"] * 4
    assert first.features.x.tolist() == [1, 2, 3]
    assert first.data["results"]["join"]["table"] == [{"x": 1, "y": 4}, {"x": 2, "y": 5}, {"x": 3, "y": 6}]
    import json

    json.dumps(first.data, allow_nan=False)


def test_method_implementation_version_invalidates_previous_success(monkeypatch):
    module = api()
    runner = module.AnalysisPlanRunner()
    first = runner.run(diamond(), inputs())
    monkeypatch.setattr(module, "IMPLEMENTATION_VERSION", "test-new-implementation")
    after = runner.run(diamond(), inputs(), previous=first)
    assert after.execution_count == 4 and after.reuse_count == 0


def test_batch_features_can_feed_downstream_table_without_confusing_curve_rows():
    frame = pd.DataFrame(
        {
            "curve_id": ["a"] * 5,
            "group": ["g"] * 5,
            "x": [1.0, 2.0, 3.0, 4.0, 5.0],
            "y": [0.0, 1.0, 4.0, 1.0, 0.0],
        }
    )
    steps = [
        {
            "id": "batch",
            "operation": "materials.batch_spectra",
            "config": {"x_unit": "nm", "intensity_unit": "a.u."},
        },
        {
            "id": "features",
            "operation": "preprocess.filter",
            "dependencies": ["batch"],
            "source_output": "features",
        },
    ]
    result = api().AnalysisPlanRunner().run(steps, {"input": frame})
    assert result.status == "success"
    assert result.records["features"].result.table.peak_position.tolist() == [3.0]
    assert len(result.records["batch"].result.table) == 5
    assert result.records["features"].result.table.attrs["units"]["peak_position"] == "nm"


def test_missing_selected_features_fails_step_and_blocks_descendants():
    steps = diamond()
    steps[1]["source_output"] = "features"
    result = api().AnalysisPlanRunner().run(steps, inputs())
    assert result.records["left"].status == "failed"
    assert "features" in result.records["left"].diagnostics["error"]
    assert result.records["join"].status == "blocked"


def test_batch_scientific_failure_blocks_downstream_and_retains_diagnostics():
    frame = pd.DataFrame({"curve_id": ["a"] * 3, "x": [1.0, 1.0, 2.0], "y": [0.0, 1.0, 0.0]})
    steps = [
        {
            "id": "batch",
            "operation": "materials.batch_spectra",
            "config": {"x_unit": "nm", "intensity_unit": "a.u."},
        },
        {
            "id": "features",
            "operation": "preprocess.filter",
            "dependencies": ["batch"],
            "source_output": "features",
        },
    ]
    result = api().AnalysisPlanRunner().run(steps, {"input": frame})
    assert result.records["batch"].status == "failed"
    assert result.records["batch"].diagnostics["scientific"]["execution_status"] == "failed"
    assert result.records["features"].status == "blocked"


def test_native_lfx_dataframe_preserves_units_and_allows_reuse():
    from lfx.schema import DataFrame

    frame = DataFrame(pd.DataFrame({"x": [1.0, 2.0, 3.0]}))
    frame.attrs["units"] = {"x": "MPa"}
    runner = api().AnalysisPlanRunner()
    first = runner.run(diamond(), {"input": frame})
    second = runner.run(diamond(), {"input": frame}, previous=first)
    assert first.status == "success" and second.reuse_count == 4
    assert first.records["join"].result.table.attrs["units"] == {"x": "MPa"}


def test_unsupported_config_is_rejected_without_invoking_custom_copy_code():
    touched = []

    class ExecutableObject:
        def __deepcopy__(self, memo):
            touched.append(True)
            return self

    steps = diamond()
    steps[0]["config"] = {"unexpected": ExecutableObject()}
    with pytest.raises(ValueError, match="unsupported fingerprint"):
        api().AnalysisPlanRunner().run(steps, inputs())
    assert touched == []


def test_null_root_input_rejected_as_a_graph_error():
    steps = diamond()
    steps[0]["input"] = None
    with pytest.raises(ValueError, match="input"):
        api().AnalysisPlanRunner().run(steps, inputs())


def test_malformed_cached_status_is_recomputed_without_crashing():
    runner = api().AnalysisPlanRunner()
    first = runner.run(diamond(), inputs())
    first.records["left"].status = []
    after = runner.run(diamond(), inputs(), previous=first)
    assert after.status == "success"
    assert after.records["left"].status == "success"
    assert after.records["join"].status == "success"
    assert after.reuse_count == 2


def test_contract_units_and_roles_follow_each_transform_inside_the_plan():
    from materials_quality.science.table_contract import attach_contract, make_contract, read_contract

    table = pd.DataFrame({"sample_id": ["a", "b", "c"], "x": [1.0, 2.0, 3.0]})
    table.attrs["units"] = {"x": "MPa"}
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="sample",
            roles={"sample_id": "sample_id", "response": "x"},
            units_state={"units": {"x": "MPa"}},
        ),
    )
    steps = [
        {"id": "normalize", "operation": "preprocess.normalize", "config": {"columns": ["x"]}},
        {
            "id": "filter",
            "operation": "preprocess.filter",
            "dependencies": ["normalize"],
            "config": {"columns": ["x"]},
        },
        {"id": "units", "operation": "preprocess.units", "config": {"target_units": {"x": "kPa"}}},
    ]
    result = api().AnalysisPlanRunner().run(steps, {"input": table})
    assert result.status == "success"
    normalized = result.records["normalize"].result.table
    assert read_contract(normalized)["units_state"]["units"]["x"] == "dimensionless"
    filtered = result.records["filter"].result.table
    assert read_contract(filtered)["roles"] == {"response": "x"}
    converted = result.records["units"].result.table
    assert read_contract(converted)["units_state"]["units"]["x"] == "kPa"
    assert converted.x.tolist() == [1000.0, 2000.0, 3000.0]
    assert read_contract(table)["units_state"]["units"]["x"] == "MPa"


def test_declared_contract_units_are_restored_before_a_direct_plan_call():
    from materials_quality.science.table_contract import attach_contract, make_contract

    table = pd.DataFrame({"sample_id": ["a", "b"], "x": [1.0, 2.0]})
    table = attach_contract(
        table,
        make_contract(
            table,
            granularity="sample",
            roles={"sample_id": "sample_id", "response": "x"},
            units_state={"units": {"x": "MPa"}},
        ),
    )
    table.attrs.pop("units", None)
    steps = [{"id": "units", "operation": "preprocess.units", "config": {"target_units": {"x": "kPa"}}}]
    result = api().AnalysisPlanRunner().run(steps, {"input": table})
    assert result.status == "success"
    assert result.records["units"].result.table.x.tolist() == [1000.0, 2000.0]


def test_native_plan_ports_verify_cache_integrity_metadata_and_implementation(monkeypatch):
    from lfx.schema import DataFrame

    from materials_quality.science.catalog import component_class
    from materials_quality.science.langflow_adapter import execute

    node = component_class("materials.analysis_plan")().set(
        input_table=DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 2.0, 5.0, 8.0]})
    )
    first, _ = execute(node, "materials.analysis_plan")
    assert first.data["execution_count"] == 3
    second, _ = execute(node, "materials.analysis_plan")
    assert second.data["execution_count"] == 0 and second.data["reuse_count"] == 3
    second.table.loc[0, "mean"] = 999
    repaired, _ = execute(node, "materials.analysis_plan")
    assert repaired.table["mean"].iloc[0] == pytest.approx(-0.9128709291752768)
    node.input_table.attrs["experiment"] = "new-metadata"
    metadata, _ = execute(node, "materials.analysis_plan")
    assert metadata.data["execution_count"] == 3
    monkeypatch.setattr(api(), "IMPLEMENTATION_VERSION", "native-test-implementation")
    implementation, _ = execute(node, "materials.analysis_plan")
    assert implementation.data["execution_count"] == 3

"""Focused usability contracts, without fitting models or contacting services."""

import importlib
import json

import pytest

STATS_KEYS = {
    "stats.grouped",
    "stats.distribution",
    "stats.correlation",
    "stats.significance",
    "stats.multiple",
    "stats.regression",
    "stats.predict",
    "stats.evaluate",
}
LIT_KEYS = {"lit.search", "lit.metadata", "lit.extract", "lit.compare", "lit.sources", "lit.summary"}


def domain(name):
    return importlib.import_module(f"materials_quality.science.ui_specs_{name}")


def fields(name, key):
    return {item["path"]: item for item in domain(name).SPECS[key]}


@pytest.mark.parametrize("name,keys", [("statistics", STATS_KEYS), ("literature", LIT_KEYS)])
def test_every_catalog_operation_has_serializable_controls_and_contract(name, keys):
    module = domain(name)
    catalog = importlib.import_module(f"materials_quality.science.{name}").CATALOG
    assert set(module.SPECS) == set(module.CONTRACTS) == keys == {x["key"] for x in catalog}
    json.dumps(module.SPECS, ensure_ascii=False, allow_nan=False)
    for key in keys:
        descriptors = module.SPECS[key]
        paths = [f["path"] for f in descriptors]
        assert paths and len(paths) == len(set(paths))
        assert all(f["label"] and f.get("info") for f in descriptors)
        assert all(f["kind"] != "json" or f["advanced"] for f in descriptors)
        by_path = {f["path"]: f for f in descriptors}
        for descriptor in descriptors:
            if descriptor["kind"] == "choice":
                assert descriptor["default"] in descriptor["choices"]
            for controller, allowed in descriptor.get("when", {}).items():
                assert controller in by_path
                if by_path[controller]["kind"] == "choice":
                    assert set(allowed).issubset(by_path[controller]["choices"])
        contract = module.CONTRACTS[key]
        assert isinstance(contract["table_output"], bool)
        assert isinstance(contract["artifacts_output"], bool)
        assert contract["upload_types"] == []
        assert contract["icon"]


@pytest.mark.parametrize(
    "key,required",
    [
        ("stats.grouped", {"group": "str", "columns": "list", "units": "dict"}),
        ("stats.correlation", {"columns": "list", "method": "choice", "alpha": "float"}),
        ("stats.significance", {"group": "str", "column": "str", "groups": "list", "pair_id": "str"}),
        ("stats.regression", {"features": "list", "target": "str", "seed": "int", "test_size": "float"}),
        ("stats.predict", {"features": "list", "target": "str", "model_path": "str", "manifest_path": "str"}),
        (
            "stats.evaluate",
            {
                "features": "list",
                "target": "str",
                "model_method": "choice",
                "folds": "int",
                "group_column": "str",
                "id_column": "str",
                "y_true": "str",
                "y_pred": "str",
            },
        ),
    ],
)
def test_statistics_ordinary_controls_use_actual_parameter_names(key, required):
    actual = fields("statistics", key)
    for path, kind in required.items():
        assert actual[path]["kind"] == kind
        assert actual[path].get("advanced", False) is False


def test_statistical_methods_and_dependent_fields():
    significance = fields("statistics", "stats.significance")
    assert set(significance["method"]["choices"]) == {
        "independent_t",
        "paired_t",
        "welch",
        "mannwhitney",
        "anova",
        "kruskal",
    }
    assert significance["pair_id"]["when"] == {"method": ["paired_t"]}
    assert significance["incomplete_pairs"]["when"] == {"method": ["paired_t"]}
    multiple = fields("statistics", "stats.multiple")
    # Both p-value adjustment and grouped comparisons use the same source key.
    assert not multiple["column"].get("when")
    assert multiple["group"]["when"] == {"method": ["tukey", "dunn"]}
    assert multiple["correction"]["when"] == {"method": ["dunn"]}
    regression = fields("statistics", "stats.regression")
    assert regression["degree"]["when"] == {"method": ["polynomial"]}
    assert regression["alpha"]["when"] == {"method": ["ridge", "lasso"]}
    evaluation = fields("statistics", "stats.evaluate")
    assert evaluation["degree"]["when"] == {"model_method": ["polynomial"], "evaluation_task": ["train"]}
    assert evaluation["folds"]["when"] == {"method": ["cv"], "evaluation_task": ["train"]}
    assert evaluation["test_size"]["when"] == {"method": ["holdout"], "evaluation_task": ["train"]}


def test_no_fake_distribution_table_or_upload_ports():
    contracts = domain("statistics").CONTRACTS
    assert contracts["stats.distribution"]["table_output"] is False
    assert contracts["stats.distribution"]["artifacts_output"] is True
    assert all(contracts[key]["table_output"] for key in STATS_KEYS - {"stats.distribution"})
    assert contracts["stats.regression"]["artifacts_output"] is True
    assert contracts["stats.predict"]["artifacts_output"] is True
    assert contracts["stats.evaluate"]["artifacts_output"] is True
    assert all(
        not contracts[key]["artifacts_output"]
        for key in {
            "stats.grouped",
            "stats.correlation",
            "stats.significance",
            "stats.multiple",
        }
    )


def test_simple_rules_use_the_coordinated_native_converters():
    bins = fields("statistics", "stats.distribution")["bins"]
    assert bins["kind"] == "str"
    assert bins["converter"] == "histogram_bins"
    assert not bins["advanced"]
    lexicon = fields("literature", "lit.extract")["lexicon"]
    assert lexicon["converter"] == "list_mapping"


@pytest.mark.parametrize(
    "key,controller,choices",
    [
        ("stats.predict", "prediction_task", {"train", "saved"}),
        ("stats.evaluate", "evaluation_task", {"train", "saved", "predictions"}),
    ],
)
def test_saved_model_task_uses_manifest_without_training_defaults(key, controller, choices):
    actual = fields("statistics", key)
    selector = actual[controller]
    assert selector["kind"] == "choice"
    assert selector["default"] == "train"
    assert set(selector["choices"]) == choices
    assert selector["ui_only"] is True

    # Existing hidden method values must not re-enable any training overrides.
    settings = {controller: "saved", "method": "holdout", "model_method": "polynomial"}
    active = {
        path
        for path, spec in actual.items()
        if all(settings.get(name) in allowed for name, allowed in spec.get("when", {}).items())
    }
    assert {controller, "model_path", "manifest_path"}.issubset(active)
    assert {"model_path", "manifest_path"}.isdisjoint(
        path for path, spec in actual.items() if spec.get("required")
    )  # Upstream Data may provide the generated manifest.
    assert active.isdisjoint(
        {
            "method",
            "model_method",
            "features",
            "target",
            "test_size",
            "seed",
            "folds",
            "id_column",
            "group_column",
            "degree",
            "alpha",
            "max_iter",
            "n_estimators",
            "max_depth",
            "C",
            "epsilon",
            "kernel",
            "output_dir",
            "overwrite",
            "y_true",
            "y_pred",
        }
    )
    for path in ("features", "target", "seed", "test_size", "method"):
        assert actual[path]["when"][controller] == ["train"]
    for path in ("model_path", "manifest_path"):
        assert actual[path]["when"] == {controller: ["saved"]}


def test_evaluation_existing_predictions_task_hides_model_and_training_fields():
    actual = fields("statistics", "stats.evaluate")
    settings = {"evaluation_task": "predictions", "method": "cv", "model_method": "linear"}
    active = {
        path
        for path, spec in actual.items()
        if all(settings.get(name) in allowed for name, allowed in spec.get("when", {}).items())
    }
    assert active == {"evaluation_task", "y_true", "y_pred"}


def test_literature_endpoints_and_environment_names_are_native_controls():
    search = fields("literature", "lit.search")
    assert search["query"]["kind"] == "str"
    assert set(search["method"]["choices"]) == {"keyword", "boolean", "author", "doi"}
    assert search["base_url"]["when"] == {"provider": ["crossref"]}
    assert search["rows"]["kind"] == "int"
    for key in ("lit.extract", "lit.summary"):
        actual = fields("literature", key)
        for path in ("llm.url", "llm.model", "llm.api_key_env"):
            assert actual[path]["kind"] == "str"
            assert actual[path]["when"] == {"method": ["llm"]}
            assert actual[path].get("advanced", False) is False
        assert actual["llm.timeout"]["kind"] == "float"
        assert not {"llm.api_key", "llm.authorization", "llm.headers"}.intersection(actual)


def test_literature_rules_and_units_do_not_require_json():
    extract = fields("literature", "lit.extract")
    for path, method in (("patterns", "regex"), ("lexicon", "lexicon")):
        assert extract[path]["kind"] in {"dict", "table"}
        assert extract[path].get("advanced", False) is False
        assert extract[path]["when"] == {"method": [method]}
    assert extract["delimiter"]["when"] == {"method": ["table"]}
    compare = fields("literature", "lit.compare")
    assert compare["target_units"]["kind"] == "dict"
    assert compare["relative_tolerance"]["kind"] == "float"
    assert fields("literature", "lit.sources")["save"]["kind"] == "bool"
    contracts = domain("literature").CONTRACTS
    assert all(c["table_output"] for c in contracts.values())
    assert {k for k, c in contracts.items() if c["artifacts_output"]} == {"lit.sources"}

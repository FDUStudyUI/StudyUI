"""Legacy flow upgrades preserve behavior and refuse unsupported/custom rewrites."""

import copy
import importlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FIXTURE = ROOT / "testfixtures/legacy_ui_0262f0d.zip"


def old_payload(path):
    # Captured once from git 0262f0d; CI shallow clones need no historical objects.
    with zipfile.ZipFile(LEGACY_FIXTURE) as archive:
        return json.loads(archive.read(path))


def migrate(payload):
    return importlib.import_module("materials_quality.science.flow_migration").migrate(payload)


def node_of(payload, class_name):
    return next(n for n in payload["data"]["nodes"] if n["data"]["type"] == class_name)


def template(node):
    return node["data"]["node"]["template"]


@pytest.mark.parametrize("name", ["03-images", "05-mechanics-thermal"])
def test_actual_old_flow_upgrade_keeps_ids_positions_all_json_options_and_input_immutable(name):
    original = old_payload(f"examples/science_flows/{name}.json")
    source = node_of(original, "ScienceIoImageImport" if name == "03-images" else "ScienceMaterialsMechanics")
    options = json.loads(template(source)["config_json"]["value"])
    options.update({"future_plugin_option": {"zero": 0, "disabled": False, "items": []}})
    template(source)["config_json"]["value"] = json.dumps(options)
    source["selected"] = True
    snapshot = copy.deepcopy(original)
    updated, report = migrate(original)
    assert original == snapshot and updated is not original
    assert len(report["upgraded"]) == len(original["data"]["nodes"]) - 1
    assert len(updated["data"]["edges"]) == len(original["data"]["edges"])
    for old, new in zip(original["data"]["nodes"], updated["data"]["nodes"], strict=True):
        assert (old["id"], old["position"]) == (new["id"], new["position"])
        if old["data"]["type"].startswith("Science") and old["data"]["type"] != "ScienceFixtureBundle":
            assert template(new)["ui_mode"]["value"] == "json"
            assert template(new)["config_json"]["value"] == template(old)["config_json"]["value"]
            assert template(new)["config_json"]["advanced"] and template(new)["config_json"]["show"]
    replaced = node_of(updated, source["data"]["type"])
    assert replaced["selected"] is True
    if name == "03-images":
        assert "table" not in {o["name"] for o in replaced["data"]["node"]["outputs"]}
    assert report["edges_validated"] == len(updated["data"]["edges"])


def test_unsupported_old_image_table_edge_raises_without_changing_original():
    module = importlib.import_module("materials_quality.science.flow_migration")
    original = old_payload("examples/science_flows/03-images.json")
    image = node_of(original, "ScienceIoImageImport")
    target = node_of(original, "ScienceExportTable")
    edge = copy.deepcopy(
        next(e for e in original["data"]["edges"] if e["data"]["sourceHandle"]["name"] == "table")
    )
    edge["source"] = image["id"]
    edge["target"] = target["id"]
    edge["data"]["sourceHandle"].update(id=image["id"], name="table", dataType="ScienceIoImageImport")
    edge["data"]["targetHandle"].update(id=target["id"], fieldName="input_table")
    original["data"]["edges"].append(edge)
    snapshot = copy.deepcopy(original)
    with pytest.raises(module.MigrationError, match=r"ScienceIoImageImport.*table"):
        module.migrate(original)
    assert original == snapshot


def test_custom_code_same_class_is_preserved_and_reported():
    original = old_payload("examples/science_flows/03-images.json")
    custom = node_of(original, "ScienceIoImageImport")
    template(custom)["code"]["value"] += "\n# A user's local custom implementation.\n"
    custom["data"]["node"]["edited"] = True
    snapshot = copy.deepcopy(custom)
    updated, report = migrate(original)
    assert node_of(updated, "ScienceIoImageImport") == snapshot
    skipped = next(item for item in report["skipped"] if item["id"] == custom["id"])
    assert skipped["reason"] == "custom_code"
    fixture = node_of(original, "ScienceFixtureBundle")
    assert node_of(updated, "ScienceFixtureBundle") == fixture


def test_unknown_nonempty_parameter_is_kept_by_skipping_unsafe_node_upgrade():
    original = old_payload("examples/science_flows/03-images.json")
    custom = node_of(original, "ScienceIoImageImport")
    template(custom)["new_vendor_option"] = {"value": {"unrecognized": 0}, "type": "dict"}
    updated, report = migrate(original)
    assert node_of(updated, "ScienceIoImageImport") == custom
    assert any(item["reason"] == "unsupported_parameter" for item in report["skipped"])


def test_invalid_target_input_is_rejected_instead_of_silently_losing_edge():
    module = importlib.import_module("materials_quality.science.flow_migration")
    original = old_payload("examples/science_flows/03-images.json")
    original["data"]["edges"][0]["data"]["targetHandle"]["fieldName"] = "removed_input"
    with pytest.raises(module.MigrationError, match="removed_input"):
        module.migrate(original)


def test_original_quality_nodes_preserve_parameters_and_native_graph_executes():
    from lfx.graph import Graph

    original = old_payload("examples/clean_quality_flow.json")
    updated, report = migrate(original)
    assert len(report["upgraded"]) == 7
    for class_name in ("MaterialTypeCheck", "MaterialSchemaCheck", "MaterialUnitCheck"):
        node = node_of(updated, class_name)
        assert template(node)["ui_mode"]["value"] == "json"
    old_type = node_of(original, "MaterialTypeCheck")
    new_type = node_of(updated, "MaterialTypeCheck")
    assert (
        template(new_type)["expectations_json"]["value"] == template(old_type)["expectations_json"]["value"]
    )
    graph = Graph.from_payload(updated)
    for step in graph.start():
        assert not hasattr(step, "valid") or step.valid, step
    result = graph.get_vertex("MaterialQualitySummary-demo").results["report"].data
    assert result["passed"] and result["metrics"]["completed_checks"] == 6


def test_second_upgrade_is_idempotent_and_does_not_reset_explicit_form_choice():
    updated, _ = migrate(old_payload("examples/science_flows/03-images.json"))
    image = node_of(updated, "ScienceIoImageImport")
    template(image)["ui_mode"]["value"] = "form"
    template(image)["cfg_path"]["value"] = "chosen-after-migration.png"
    again, report = migrate(updated)
    assert again == updated
    assert not report["upgraded"]


def test_cli_keeps_original_and_refuses_existing_output(tmp_path):
    source = tmp_path / "03-images.json"
    source.write_text(json.dumps(old_payload("examples/science_flows/03-images.json")), encoding="utf-8")
    original = source.read_bytes()
    command = [sys.executable, str(ROOT / "scripts/migrate_flow_ui.py"), str(source)]
    done = subprocess.run(command, cwd=ROOT, encoding="utf-8", capture_output=True)
    assert done.returncode == 0, done.stderr
    destination = source.with_name(source.stem + ".ui-v2.json")
    assert source.read_bytes() == original and destination.is_file()
    saved = destination.read_bytes()
    retry = subprocess.run(command, cwd=ROOT, encoding="utf-8", capture_output=True)
    assert retry.returncode != 0 and "exist" in retry.stderr.lower()
    assert source.read_bytes() == original and destination.read_bytes() == saved


def test_hash_registry_covers_every_science_and_original_quality_class():
    from materials_quality.science.catalog import entries

    module = importlib.import_module("materials_quality.science.flow_migration")
    registry = json.loads(
        Path(module.__file__).with_name("legacy_component_hashes.json").read_text(encoding="utf-8")
    )
    expected = {entry["class_name"] for entry in entries()} | {
        "MaterialQualityContext",
        "MaterialQualitySummary",
        "MaterialSchemaCheck",
        "MaterialMissingCheck",
        "MaterialTypeCheck",
        "MaterialUnitCheck",
        "MaterialDuplicateCheck",
        "MaterialOutlierCheck",
    }
    assert set(registry["classes"]) == expected
    assert all(
        hashes and all(len(value) == 64 for value in hashes) for hashes in registry["classes"].values()
    )


def test_source_normalization_preserves_whitespace_inside_python_literals():
    module = importlib.import_module("materials_quality.science.flow_migration")
    assert module.source_hash('x = """a  \n"""\n') != module.source_hash('x = """a\n"""\n')
    assert module.source_hash("x = 1\r\n") == module.source_hash("x = 1\n")


def test_shared_quality_context_legacy_rules_are_not_reset_to_form_defaults():
    original = old_payload("examples/mechanics/clean_flow.json")
    updated, report = migrate(original)
    assert len(report["upgraded"]) == 8
    old = node_of(original, "MaterialQualityContext")
    new = node_of(updated, "MaterialQualityContext")
    assert template(new)["ui_mode"]["value"] == "json"
    assert template(new)["rules_json"]["value"] == template(old)["rules_json"]["value"]
    assert template(new)["rule_set_id"]["value"] == template(old)["rule_set_id"]["value"]


def test_all_nine_old_science_examples_upgrade_all_forty_four_operations_and_keep_edges():
    from materials_quality.science.catalog import entries

    covered = set()
    for name in (
        "01-tables",
        "02-documents",
        "03-images",
        "04-spectra",
        "05-mechanics-thermal",
        "06-morphology",
        "07-statistics",
        "08-model",
        "09-literature",
    ):
        original = old_payload(f"examples/science_flows/{name}.json")
        updated, report = migrate(original)
        assert not report["skipped"], (name, report["skipped"])
        assert len(report["upgraded"]) == len(original["data"]["nodes"]) - 1
        assert len(updated["data"]["edges"]) == len(original["data"]["edges"])
        covered.update(node["class_name"] for node in report["upgraded"])
    assert covered == {entry["class_name"] for entry in entries()}


def test_connected_advanced_provenance_ports_stay_visible_and_handle_labels_refresh():
    original = old_payload("examples/science_flows/05-mechanics-thermal.json")
    old_plot = node_of(original, "ScienceVizMechanics")
    edge = next(
        e
        for e in original["data"]["edges"]
        if e["target"] == old_plot["id"] and e["data"]["targetHandle"]["fieldName"] == "input_data"
    )
    edge["data"]["targetHandle"]["display_name"] = "Outdated provenance label"
    updated, _ = migrate(original)
    plot = node_of(updated, "ScienceVizMechanics")
    descriptor = template(plot)["input_data"]
    assert descriptor["advanced"] is False
    new_edge = next(
        e
        for e in updated["data"]["edges"]
        if e["target"] == plot["id"] and e["data"]["targetHandle"]["fieldName"] == "input_data"
    )
    assert new_edge["data"]["targetHandle"]["display_name"] == descriptor["display_name"]
    merged, _ = migrate(old_payload("examples/science_flows/01-tables.json"))
    assert template(node_of(merged, "SciencePreprocessMerge"))["reports"]["advanced"] is False


def test_pinned_legacy_fixtures_require_no_git_history(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy fixture reads must not invoke Git or another subprocess")

    monkeypatch.setattr(subprocess, "check_output", forbidden)
    with zipfile.ZipFile(LEGACY_FIXTURE) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 11
    for path in (
        "examples/science_flows/03-images.json",
        "examples/clean_quality_flow.json",
        "examples/mechanics/clean_flow.json",
    ):
        assert old_payload(path)["data"]["nodes"]

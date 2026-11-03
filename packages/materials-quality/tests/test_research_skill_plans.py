"""Plans are explicit scientific contracts rather than executable model text."""

from copy import deepcopy

import pandas as pd
import pytest


def api():
    from materials_quality.skills.planning import make_plan, validate_plan

    return make_plan, validate_plan


def spectra():
    return pd.DataFrame({"curve_id": ["a"] * 3, "wavelength_nm": [650, 700, 750], "intensity": [1, 3, 1]})


def options():
    return {"x_unit": "nm", "y_unit": "counts", "peak_window": [650, 850], "data_kind": "synthetic"}


def test_registry_bundles_three_real_skills_and_rejects_resource_escape(tmp_path, monkeypatch):
    from materials_quality.skills.registry import inspect_skill, list_skills, load_skill

    rows = list_skills()
    assert {r["task"] for r in rows} == {"spectra", "mechanics", "contrast"}
    skill = load_skill("spectra")
    assert "SKILL.md" in skill["resources"]
    assert len(skill["sha256"]) == 64
    assert "窗口" in skill["instructions"]
    with pytest.raises(ValueError):
        load_skill("../../other")
    external = tmp_path / "external"
    external.mkdir()
    (external / "SKILL.md").write_text("---\nname: external\ndescription: External analysis\n---\nDo work", "utf-8")
    preview = inspect_skill(external)
    assert preview["executable"] is False
    assert preview["name"] == "external"
    # Exercise the symlink guard without requiring Windows administrator privilege.
    from pathlib import Path

    (external / "escape").write_text("resource", "utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p.name == "escape" or original(p))
    with pytest.raises(ValueError, match="symlink|符号"):
        inspect_skill(external)


def test_plan_requires_declared_units_and_window_instead_of_guessing_from_header():
    make, _ = api()
    p = make(spectra(), task="spectra")
    assert not p["ready"]
    assert {i["field"] for i in p["issues"]} >= {"x_unit", "y_unit", "peak_window"}
    p = make(spectra(), task="spectra", parameters=options())
    assert p["ready"], p["issues"]
    assert p["parameters"]["x"] == "wavelength_nm"
    assert p["parameters"]["curve_id"] == "curve_id"
    assert p["input"]["rows"] == 3


def test_ambiguous_columns_are_not_silently_selected():
    make, _ = api()
    f = spectra().assign(wavelength=[650, 700, 750])
    p = make(f, task="spectra", parameters=options())
    assert not p["ready"]
    assert "x" in {i["field"] for i in p["issues"]}
    assert make(f, task="spectra", parameters={**options(), "x": "wavelength_nm"})["ready"]


def test_stale_data_metadata_plan_and_unknown_parameters_cannot_execute():
    make, validate = api()
    f = spectra()
    p = make(f, task="spectra", parameters=options())
    validate(f, p)
    changed = f.copy()
    changed.loc[0, "intensity"] = 9
    with pytest.raises(ValueError, match="数据|input|stale"):
        validate(changed, p)
    changed = f.copy()
    changed.attrs["units"] = {"wavelength_nm": "um"}
    with pytest.raises(ValueError):
        validate(changed, p)
    altered = deepcopy(p)
    altered["parameters"]["peak_window"] = [0, 1]
    with pytest.raises(ValueError, match="计划|plan"):
        validate(f, altered)
    with pytest.raises(ValueError, match="参数|parameter"):
        make(f, task="spectra", parameters={**options(), "shell": "echo unsafe"})


@pytest.mark.parametrize("bounds", [[1, 1], [850, 650], [True, 850], [float("nan"), 850]])
def test_invalid_windows_block_before_execution(bounds):
    make, _ = api()
    assert not make(spectra(), task="spectra", parameters={**options(), "peak_window": bounds})["ready"]


def test_mechanics_needs_units_fit_interval_and_explicit_sample_identity():
    make, _ = api()
    f = pd.DataFrame({"strain": [0, .0004, .0008], "stress": [0, 80, 160]})
    p = make(f, task="mechanics")
    assert not p["ready"]
    assert {i["field"] for i in p["issues"]} >= {"strain_unit", "stress_unit", "fit_range", "sample_id"}
    p = make(f, task="mechanics", parameters={
        "single_sample": True, "strain_unit": "fraction", "stress_unit": "MPa", "fit_range": [0, .0008]
    })
    assert p["ready"], p["issues"]


def test_contrast_requires_design_and_unit_not_guessed_from_sample_id():
    make, _ = api()
    f = pd.DataFrame({"group": ["A", "A", "B", "B"], "value": [1., 2., 3., 4.],
                      "sample_id": ["a", "b", "c", "d"], "variable": ["peak"] * 4})
    p = make(f, task="contrast")
    assert not p["ready"]
    assert {i["field"] for i in p["issues"]} >= {"design", "experimental_unit", "value_unit"}


def test_schema_auto_routing_and_model_proposals_share_validation():
    make, _ = api()
    assert make(spectra(), request="比较各组光谱候选峰", parameters=options())["task"] == "spectra"
    p = make(spectra(), request="帮我处理这些数据")
    assert not p["ready"]
    proposal = {"task": "spectra", "parameters": options()}
    assert make(spectra(), proposal=proposal)["ready"]
    with pytest.raises(ValueError):
        make(spectra(), proposal={**proposal, "code": "import os"})
    with pytest.raises(ValueError):
        make(spectra(), proposal={"task": "shell", "parameters": {}})


def test_conflicting_unit_metadata_blocks_plan():
    make, _ = api()
    f = spectra()
    f.attrs["units"] = {"wavelength_nm": "um"}
    assert not make(f, task="spectra", parameters=options())["ready"]

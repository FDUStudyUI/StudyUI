"""Lazy, versioned registry shared by node generation and runtime dispatch."""

import json
import sys
from functools import lru_cache
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PAPER_OPERATIONS = frozenset(
    {
        "lit.method_recommend",
        "lit.result_evidence",
        "materials.chemometrics",
        "materials.analysis_plan",
    }
)

_NATIVE_PLUGIN_ENTRIES = {
    "materials.xrd_cif_screening": {
        "key": "materials.xrd_cif_screening",
        "title": "CIF 理论 XRD 候选筛查 (pymatgen)",
        "function": "materials_quality.science.langflow_adapter:xrd_cif_screening",
        "directory": "materials_analysis",
        "filename": "pymatgen_xrd_screening",
        "class_name": "PymatgenXrdScreening",
    },
    "materials.pybamm_battery_sim": {
        "key": "materials.pybamm_battery_sim",
        "title": "单电芯放电曲线仿真 (PyBaMM)",
        "function": "materials_quality.science.langflow_adapter:pybamm_battery_sim",
        "directory": "materials_batch",
        "filename": "pybamm_battery_sim",
        "class_name": "PybammBatterySim",
    },
}


def entries():
    return json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))


def _lookup_entry(key):
    item = next((x for x in entries() if x["key"] == key), None)
    if item is None and key in _NATIVE_PLUGIN_ENTRIES:
        item = dict(_NATIVE_PLUGIN_ENTRIES[key])
    if item is None:
        raise ValueError(f"Unknown science operation: {key}")
    return item


def get(key):
    item = _lookup_entry(key)
    module, function = item["function"].split(":")
    item["callable"] = getattr(import_module(module), function)
    return item


@lru_cache(maxsize=48)
def component_class(key):
    item = _lookup_entry(key)
    # Also works from a regular wheel; source files are packaged with the nodes.
    root = Path(__file__).resolve().parents[1] / "component_sources"
    if not root.is_dir():
        root = Path(__file__).resolve().parents[3] / "components"
    path = root / item["directory"] / (item["filename"] + ".py")
    name = "materials_quality._native_" + item["filename"]
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return getattr(module, item["class_name"])

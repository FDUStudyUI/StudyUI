"""Lazy, versioned registry shared by node generation and runtime dispatch."""

import json
import sys
from functools import lru_cache
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def entries():
    return json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))


def get(key):
    item = next((x for x in entries() if x["key"] == key), None)
    if item is None:
        raise ValueError(f"Unknown science operation: {key}")
    module, function = item["function"].split(":")
    item["callable"] = getattr(import_module(module), function)
    return item


@lru_cache(maxsize=44)
def component_class(key):
    item = next((x for x in entries() if x["key"] == key), None)
    if item is None:
        raise ValueError(f"Unknown science operation: {key}")
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

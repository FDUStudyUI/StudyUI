"""Compare native discovery with the shipped component class declarations."""

import ast
from pathlib import Path

from .science.catalog import entries


def component_manifest(root):
    expected = {}
    for source in sorted(Path(root).glob("materials_*/*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id == "Component" for base in node.bases
            ):
                expected.setdefault(source.parent.name, set()).add(node.name)
    for item in entries():
        if item["class_name"] not in expected.get(item["directory"], set()):
            raise ValueError(f"Missing source for catalog component: {item['key']}")
    if len(expected.get("materials_quality", set())) != 8:
        raise ValueError("The eight core quality components must be present")
    return expected


def verify_discovery(discovered, root):
    expected = component_manifest(root)
    actual = {key: set(value) for key, value in discovered.items() if key in expected}
    if actual != expected:
        missing = {key: sorted(names - actual.get(key, set())) for key, names in expected.items()}
        extra = {key: sorted(names - expected[key]) for key, names in actual.items()}
        raise ValueError(f"Component discovery mismatch: missing={missing}, extra={extra}")
    return sum(map(len, expected.values()))

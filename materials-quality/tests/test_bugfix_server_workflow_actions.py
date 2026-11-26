"""Regression test: graph actions must reject non-finite node positions."""

import pytest

from materials_quality.agent.workflow import apply_actions

CATALOG = {"materials_analysis": {"SafeNode": {"template": {}, "outputs": []}}}


def _flow():
    return {"id": "flow", "data": {"nodes": [], "edges": []}}


def test_add_node_rejects_nan_position():
    action = {"op": "add_node", "component_type": "SafeNode", "node_id": "n1", "x": float("nan"), "y": 10}
    with pytest.raises(ValueError):
        apply_actions(_flow(), [action], CATALOG)


def test_add_node_rejects_infinite_position():
    action = {
        "op": "add_node",
        "component_type": "SafeNode",
        "node_id": "n1",
        "x": 10,
        "y": float("inf"),
    }
    with pytest.raises(ValueError):
        apply_actions(_flow(), [action], CATALOG)

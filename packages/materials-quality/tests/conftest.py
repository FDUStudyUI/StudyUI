"""Prevent default-client tests from modifying the developer's active workspace."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_default_workflow_storage(tmp_path, monkeypatch):
    from materials_quality.agent import harness
    from materials_quality.agent.file_workflow_client import FileWorkflowClient

    original = FileWorkflowClient.__init__
    default_root = Path(harness.__file__).resolve().parents[5] / "workflows"

    def isolated_init(client, root, components, **kwargs):
        if Path(root).resolve() == default_root.resolve():
            root = tmp_path / "default-workflows"
        original(client, root, components, **kwargs)

    monkeypatch.setattr(FileWorkflowClient, "__init__", isolated_init)

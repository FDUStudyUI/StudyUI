"""Agent access to workflows and installed nodes without a Langflow account."""

from __future__ import annotations

import copy
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .workflow_executor import FileWorkflowExecutor
from .workflow_files import WorkflowFileStore


class FileWorkflowClient:
    def __init__(self, root: str | Path, components: str | Path, *, catalog_loader: Callable | None = None):
        self.store = WorkflowFileStore(root)
        self.components = Path(components).resolve()
        self._catalog_loader = catalog_loader or self._load_catalog
        self._catalog = None
        self._catalog_lock = threading.Lock()
        self._reads = threading.local()
        self.executor = FileWorkflowExecutor(self.store, validator=self._validate_flow)

    def _validate_flow(self, flow):
        from .workflow import sanitize_installed_components

        return sanitize_installed_components(flow, self.component_catalog())

    def _load_catalog(self):
        from lfx.custom.utils import build_custom_components

        if not self.components.is_dir():
            raise ValueError("StudyUI component directory does not exist")
        paths = [str(path) for path in sorted(self.components.iterdir()) if path.is_dir()]
        return build_custom_components(paths)

    def component_catalog(self):
        with self._catalog_lock:
            if self._catalog is None:
                value = self._catalog_loader()
                if not isinstance(value, dict):
                    raise ValueError("Unexpected component catalog")
                self._catalog = value
            return copy.deepcopy(self._catalog)

    def list_flows(self):
        return self.store.list()

    def create_flow(self, name, description="", project_id=None):
        now = datetime.now(timezone.utc).isoformat()
        flow = {
            "id": str(uuid.uuid4()),
            "name": str(name).strip()[:160] or "新建科研工作流",
            "description": str(description).strip()[:2000],
            "data": {"nodes": [], "edges": []},
            "folder_id": project_id,
            "is_component": False,
            "created_at": now,
            "updated_at": now,
        }
        self.store.save(flow, create_only=True)
        return flow

    def get_flow(self, flow_id):
        flow, revision = self.store.read(str(flow_id))
        sanitized = self._validate_flow(flow)
        if sanitized != flow:
            revision = self.store.save(sanitized, expected_revision=revision)
            flow = sanitized
        if not hasattr(self._reads, "revisions"):
            self._reads.revisions = {}
        self._reads.revisions[str(flow_id)] = revision
        return flow

    def update_flow(self, flow_id, flow):
        revisions = getattr(self._reads, "revisions", {})
        revision = revisions.get(str(flow_id))
        if revision is None:
            raise ValueError("Read the workflow before updating it")
        if str(flow.get("id")) != str(flow_id):
            raise ValueError("Workflow ID cannot be changed")
        flow = self._validate_flow(flow)
        revisions.pop(str(flow_id), None)
        self.store.save(flow, expected_revision=revision)
        return flow

    def run_flow(
        self,
        flow_id,
        *,
        tweaks=None,
        input_value="",
        include_all_nodes=False,
        external_data_approved=False,
        expected_digest=None,
        expected_project_id=None,
    ):
        return self.executor.run(
            str(flow_id),
            tweaks=tweaks,
            input_value=input_value,
            output_type="debug",
            include_all_nodes=include_all_nodes,
            external_data_approved=external_data_approved,
            expected_digest=expected_digest,
            expected_project_id=expected_project_id,
        )

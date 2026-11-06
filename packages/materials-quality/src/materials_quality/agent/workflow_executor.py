"""Execute StudyUI workflow files directly using the LFX graph runtime."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .workflow_files import WorkflowFileStore


def _serialize_output(value):
    import numpy as np
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        return json.loads(value.to_json(orient="records", date_format="iso"))
    if isinstance(value, (np.ndarray, np.generic)):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported workflow output type: {type(value).__name__}")


class FileWorkflowExecutor:
    def __init__(self, store: WorkflowFileStore, validator=None):
        self.store = store
        self.validator = validator

    def run(
        self,
        flow_id: str,
        *,
        input_value: str = "",
        tweaks: dict | None = None,
        output_type: str = "any",
        external_data_approved: bool = False,
        expected_digest: str | None = None,
        expected_project_id: str | None = None,
    ):
        from lfx.load import run_flow_from_json

        if not isinstance(input_value, str):
            raise ValueError("input_value must be a string")
        if tweaks is not None and not isinstance(tweaks, dict):
            raise ValueError("tweaks must be an object")
        flow, revision = self.store.read(flow_id)
        if self.validator:
            flow = self.validator(flow) or flow
        if expected_digest is not None or external_data_approved:
            from .workflow import flow_digest

            if not expected_digest or (
                flow_digest(flow) != expected_digest or flow.get("folder_id") != expected_project_id
            ):
                raise ValueError("运行授权后工作流内容或所属项目已变化；请重新确认运行或数据传输审批。")
        from .execution_context import (
            begin_upstream_image_scope,
            external_data_approval,
            reset_external_data_approval,
            reset_upstream_image_scope,
        )

        token = external_data_approval(external_data_approved)
        image_scope = begin_upstream_image_scope()
        try:
            outputs = run_flow_from_json(
                flow,
                input_value=input_value,
                input_type="text",
                output_type=output_type,
                tweaks=copy.deepcopy(tweaks or {}),
            )
        finally:
            reset_external_data_approval(token)
            reset_upstream_image_scope(image_scope)
        return {
            "flow_id": flow_id,
            "revision": revision,
            "outputs": [
                value.model_dump(mode="json", fallback=_serialize_output)
                if hasattr(value, "model_dump")
                else value
                for value in outputs
            ],
        }

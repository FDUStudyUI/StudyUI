"""StudyUI's application-level research agent.

LFX is one of StudyUI's internal tools: it supplies the workflow canvas and
execution engine while StudyUI owns dialogue, tools, policy, approval, and memory.
"""

from __future__ import annotations

from .file_workflow_client import FileWorkflowClient
from .harness import StudyUIAgent

__all__ = ["FileWorkflowClient", "StudyUIAgent"]

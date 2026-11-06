"""Create packaged reference workflows through the regular local workflow store."""

from urllib.parse import urlencode

from materials_quality.demos.catalog import get_dataset
from materials_quality.demos.reference import load_reference_flow

from .file_workflow_client import FileWorkflowClient
from .workflow import sanitize_installed_components


def create_reference_workflow(harness, dataset_id, session_id):
    """Called under the session mutex; opening never invokes an Agent or executor."""
    if not harness.store.has_session(session_id):
        raise LookupError("研究会话不存在。")
    context = harness.store.session_context(session_id)
    project_id = context.get("project_id")
    if not project_id or not harness.store.has_project(project_id):
        raise ValueError("请先在项目中打开研究会话，再创建参考工作流。")
    decision = harness.permissions.authorize(
        project_id=project_id,
        action="workflow.create",
        task_authorized=True,
    )
    if not decision["allowed"]:
        raise PermissionError("当前项目权限不允许创建参考工作流；请在设置中选择项目协作。")
    client = harness.langflow
    if not isinstance(client, FileWorkflowClient):
        raise ValueError("参考工作流需要本地工作流存储。")
    item = get_dataset(dataset_id)
    reference = sanitize_installed_components(load_reference_flow(dataset_id), client.component_catalog())
    created = client.create_flow(
        reference.get("name") or item["title"] + " · 参考工作流",
        reference.get("description") or item["desc"],
        project_id=project_id,
    )
    try:
        flow = client.get_flow(created["id"])
        flow["data"] = reference["data"]
        flow["studyui_demo"] = {"dataset_id": dataset_id, "source_sha256": item["sha256"]}
        client.update_flow(flow["id"], flow)
    except Exception:
        # Only recover this request's untouched empty draft; preserve any external edit.
        try:
            current, _ = client.store.read(created["id"])
            if current == created:
                client.store.delete(created["id"])
        except OSError:
            pass
        raise
    harness.store.append_event(
        session_id,
        "workflow_created",
        {
            "flow_id": flow["id"],
            "name": flow["name"],
            "dataset_id": dataset_id,
            "source_sha256": item["sha256"],
            "reference": True,
        },
    )
    return {
        "status": "created",
        "id": dataset_id,
        "flow_id": flow["id"],
        "title": flow["name"],
        "url": "/canvas/flow/" + flow["id"] + "?" + urlencode({"studyui_session_id": session_id}),
        "expected_summary": item["expected_summary"],
        "instructions": (
            "参考流程已打开，尚未运行。先查看节点表单中的参数，再点击画布右下角“运行工作流”；"
            "完成后查看图表与 HTML 报告。演示参数可在表单中修改。"
        ),
    }

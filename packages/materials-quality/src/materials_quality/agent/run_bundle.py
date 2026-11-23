"""Portable replay packages for material protocols, using installed native nodes."""

import argparse
import hashlib
import json
import platform
import shutil
import tempfile
import uuid
import zipfile
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

import pandas as pd


def _json(path, value):
    from materials_quality.common import json_value

    path.write_text(json.dumps(json_value(value), ensure_ascii=False, indent=2), encoding="utf-8")


def create_bundle(flow, outputs, root, checkpoints):
    from materials_quality.science.langflow_adapter import SECRET, _redact

    from .harness import _artifact_candidates
    from .workflow_executor import _serialize_run_outputs

    directory = Path(root) / uuid.uuid4().hex[:16]
    directory.mkdir(parents=True)
    for name in ("inputs", "results", "figures"):
        (directory / name).mkdir()
    frozen = deepcopy(flow)
    references = []
    for node in frozen["data"]["nodes"]:
        template = node["data"]["node"]["template"]
        for field_name, field in template.items():
            if isinstance(field, dict) and (field.get("password") or SECRET.search(field_name)):
                field["value"] = ""
        if "import" not in node["data"]["type"].lower() or "cfg_path" not in template:
            continue
        path = Path(template["cfg_path"]["value"]).resolve()
        if not path.is_file():
            continue
        raw = path.read_bytes()
        name = "inputs/" + node["id"] + path.suffix
        (directory / name).write_bytes(raw)
        template["cfg_path"]["value"] = "@bundle:" + name
        references.append(
            {
                "node_id": node["id"],
                "file": name,
                "original_name": path.name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        )
    serial = [_serialize_run_outputs(run) for run in outputs]
    seen = set()
    for raw_path in _artifact_candidates({"outputs": serial}):
        path = Path(raw_path)
        if path.is_file() and path not in seen:
            seen.add(path)
            # Exporters declare only generated artifacts. Distinct names survive collisions.
            prefix = "figures" if path.suffix.lower() in {".png", ".svg", ".tif", ".tiff"} else "results"
            target = directory / prefix / (str(len(seen)) + "_" + path.name)
            shutil.copyfile(path, target)
    for run in outputs:
        for entry in getattr(run, "outputs", []) or []:
            ports = getattr(entry, "outputs", {}) or getattr(entry, "results", {}) or {}
            for port, value in ports.items():
                if hasattr(value, "model_dump"):
                    value = value.model_dump()
                if (
                    isinstance(value, dict)
                    and value.get("type") in {"table", "array"}
                    and port in {"table", "features"}
                    and isinstance(value.get("message"), list)
                ):
                    value = pd.DataFrame(value["message"])
                if isinstance(value, pd.DataFrame):
                    name = str(entry.component_id) + "_" + str(port)
                    # Native protocol aliases are simple IDs; do not turn a title into a path.
                    if Path(name).name == name:
                        value.to_csv(directory / "results" / (name + ".csv"), index=False)
    protocol = frozen.get("studyui_protocol", {})
    _json(directory / "workflow.json", frozen)
    _json(
        directory / "input_references.json", {"schema_version": "measurement-bundle/1", "inputs": references}
    )
    _json(
        directory / "method_decision.json",
        {
            "schema_version": "method-decision/1",
            "stage": "flow_generation_snapshot",
            "decision": protocol.get("assessment"),
            "parameters": protocol.get("parameters"),
        },
    )
    _json(directory / "protocol.json", protocol)
    _json(directory / "checks.json", _redact({"checkpoints": checkpoints, "runtime_results": serial}))
    _json(
        directory / "environment.json",
        {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "libraries": {name: version(name) for name in ("lfx", "numpy", "pandas", "scipy", "pyarrow")},
        },
    )
    (directory / "reproduce.md").write_text(
        "# 复现材料分析\n\n解压后，在已安装 StudyUI 的环境中运行：\n\n"
        "```sh\npython -m materials_quality.agent.run_bundle ./解压目录\n```\n\n"
        "入口先核对包内文件哈希，将原始数据绑定到本机路径，并使用已安装节点代码运行。"
        "不调用模型。流程配置是本次实际运行的配置；方法决策文件记录建流时的选择，后续手工改参以流程为准。\n",
        encoding="utf-8",
    )
    files = {
        str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    _json(
        directory / "manifest.json",
        {"schema_version": "research-run-bundle/1", "flow_id": flow["id"], "files": files},
    )
    archive = directory.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in directory.rglob("*"):
            if path.is_file():
                zipped.write(path, str(path.relative_to(directory)))
    return archive


def replay_bundle(directory):
    from materials_quality.science.catalog import component_class, entries

    from .file_workflow_client import FileWorkflowClient

    root = Path(directory).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("复现包文件不匹配：" + relative)
    flow = json.loads((root / "workflow.json").read_text(encoding="utf-8"))
    types = {item["class_name"]: item["key"] for item in entries()}
    installed = {}
    for node in flow["data"]["nodes"]:
        type_name = node["data"]["type"]
        if type_name not in types:
            raise ValueError("复现包包含未安装的科学节点：" + type_name)
        installed[type_name] = component_class(types[type_name])().to_frontend_node()["data"]["node"]
        for field in node["data"]["node"]["template"].values():
            value = field.get("value") if isinstance(field, dict) else None
            if isinstance(value, str) and value.startswith("@bundle:"):
                relative = value.removeprefix("@bundle:")
                if relative not in manifest["files"]:
                    raise ValueError("复现数据未在清单中登记")
                field["value"] = str(root / relative)
    # Keep replay products outside the frozen package; original evidence remains intact.
    runtime = Path(tempfile.mkdtemp(prefix=".studyui-replay-", dir=root.parent))
    client = FileWorkflowClient(
        runtime / "flows", runtime / "components", catalog_loader=lambda: {"materials_replay": installed}
    )
    client.store.save(flow, create_only=True)
    return client.executor.run(flow["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    args = parser.parse_args()
    result = replay_bundle(args.directory)
    print(json.dumps(result, ensure_ascii=False))

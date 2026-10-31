"""Source code is embedded in each exported flow, including its imports."""

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from lfx.custom import Component
from lfx.io import MultilineInput, Output
from lfx.schema import Data, DataFrame


class ScienceFixtureBundle(Component):
    display_name = "合成样例数据包"
    description = "读取流程内嵌的人工表格、文本和文件，核对 SHA-256 后写入本次运行的临时目录。"
    name = "ScienceFixtureBundle"
    icon = "FlaskConical"
    inputs = [MultilineInput(name="bundle_base64", display_name="内嵌合成样例（Base64 JSON）", value="e30=")]
    outputs = [
        Output(name="table", display_name="样例表格", method="build_table", group_outputs=True),
        Output(name="data", display_name="文件与证据", method="build_data", group_outputs=True),
    ]

    def build_table(self) -> DataFrame:
        return DataFrame(json.loads(base64.b64decode(self.bundle_base64, validate=True)).get("records", []))

    def build_data(self) -> Data:
        bundle = json.loads(base64.b64decode(self.bundle_base64, validate=True))
        root = Path(tempfile.mkdtemp(prefix="studyui-science-"))
        outputs = root / "results"
        outputs.mkdir()
        paths = {"output": str(outputs)}
        for name, blob in bundle.get("assets", {}).items():
            if Path(name).name != name or name in {"", ".", "..", "output", "results"}:
                raise ValueError("Asset names must be simple unique filenames")
            raw = base64.b64decode(blob["base64"], validate=True)
            if hashlib.sha256(raw).hexdigest() != blob["sha256"]:
                raise ValueError(f"Embedded asset checksum mismatch: {name}")
            path = root / name
            path.write_bytes(raw)
            paths[name] = str(path)
        return Data(data={**bundle.get("data", {}), "asset_paths": paths, "synthetic": True})

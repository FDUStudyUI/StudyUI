"""Native multi-file threshold image segmentation and calibration forms."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
from lfx.base.data.storage_utils import parse_storage_path
from lfx.custom import Component
from lfx.io import BoolInput, DropdownInput, FileInput, FloatInput, IntInput, Output, TableInput
from lfx.schema import Data, DataFrame, Message
from lfx.utils.file_path_security import component_file_access_scopes, enforce_local_file_access

from materials_quality.batch.native import native_frame
from materials_quality.science.image_batch import analyze_images
from materials_quality.science.langflow_adapter import _file_hashes


class BatchImageAnalyzer(Component):
    display_name = "材料批量·显微图像分析"
    description = "多图逐项阈值分割与连通区域尺寸分布；物理尺寸需要显式标定，未标定时使用 px。"
    name = "BatchImageAnalyzer"
    icon = "Images"
    inputs = [
        FileInput(
            name="image_files",
            display_name="多张显微图像",
            file_types=["png", "jpg", "jpeg", "tif", "tiff", "bmp"],
            is_list=True,
            required=True,
        ),
        DropdownInput(
            name="threshold_method", display_name="阈值方法", options=["otsu", "manual"], value="otsu"
        ),
        FloatInput(name="threshold", display_name="手动强度阈值", value=128.0),
        DropdownInput(name="foreground", display_name="目标区域", options=["bright", "dark"], value="bright"),
        DropdownInput(
            name="feature",
            display_name="区域解释（实验者声明）",
            options=["particle", "pore", "grain"],
            value="particle",
        ),
        IntInput(name="min_area_pixels", display_name="最小区域像素数", value=1),
        DropdownInput(
            name="connectivity",
            display_name="连通邻域",
            options=["4-neighbour", "8-neighbour"],
            value="4-neighbour",
        ),
        BoolInput(name="physical_calibration", display_name="使用全局物理标定", value=False),
        FloatInput(name="pixel_size", display_name="每像素物理长度", value=1.0),
        DropdownInput(
            name="spatial_unit",
            display_name="物理长度单位",
            options=["nm", "um", "mm", "cm", "m"],
            value="um",
        ),
        TableInput(
            name="calibrations",
            display_name="逐图标定与分组（覆盖全局）",
            value=[],
            trigger_text="编辑标定表",
            info="path 使用完整绝对路径；或填写报告中的 image_id。文件基本名不作为匹配键。",
            table_schema=[
                {"name": n, "display_name": d, "type": t, "edit_mode": "inline"}
                for n, d, t in [
                    ("path", "完整路径", "str"),
                    ("image_id", "图像 ID（可选）", "str"),
                    ("pixel_size", "每像素长度", "float"),
                    ("spatial_unit", "长度单位", "str"),
                    ("group", "实验分组", "str"),
                ]
            ],
        ),
        DropdownInput(name="on_error", display_name="单图出错时", options=["stop", "continue"], value="stop"),
    ]
    outputs = [
        Output(name=n, display_name=d, method=m, group_outputs=True)
        for n, d, m in [
            ("features", "逐区域真实尺寸特征", "build_features"),
            ("images", "逐图统计与状态", "build_images"),
            ("groups", "分组尺寸分布", "build_groups"),
            ("report", "结果与标定追溯", "build_report"),
            ("summary", "运行摘要", "build_summary"),
        ]
    ]

    def _paths(self):
        raw = self.image_files
        values = raw if isinstance(raw, list) else [raw]
        paths = []
        for v in values:
            if not v:
                continue
            resolved = self.get_full_path(str(v)) if parse_storage_path(str(v)) else self.resolve_path(str(v))
            paths.append(
                str(enforce_local_file_access(Path(resolved), scope_ids=component_file_access_scopes(self)))
            )
        return paths

    def _config(self):
        rows = self.calibrations
        if isinstance(rows, pd.DataFrame):
            rows = rows.to_dict("records")
        c = {
            "threshold": self.threshold if self.threshold_method == "manual" else "otsu",
            "foreground": self.foreground,
            "feature": self.feature,
            "min_area_pixels": self.min_area_pixels,
            "connectivity": 1 if self.connectivity == "4-neighbour" else 2,
            "calibrations": rows or [],
            "on_error": self.on_error,
        }
        if self.physical_calibration:
            c.update(pixel_size=self.pixel_size, spatial_unit=self.spatial_unit)
        return c

    def _result(self):
        paths = self._paths()
        c = self._config()
        sources = []
        for path in paths:
            try:
                content = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError as error:
                content = f"{type(error).__name__}:{error}"
            sources.append((path, content))
        signature = hashlib.sha256(json.dumps([sources, c], sort_keys=True).encode()).hexdigest()
        cached = self._ctx.get("batch_images")
        if (
            cached is None
            or cached[0] != signature
            or _file_hashes(cached[1].artifacts, paths=True) != self._ctx.get("batch_image_artifact_hashes")
        ):
            cached = (signature, analyze_images(paths, c))
            self._ctx["batch_images"] = cached
            self._ctx["batch_image_artifact_hashes"] = _file_hashes(cached[1].artifacts, paths=True)
        return cached

    def build_features(self) -> DataFrame:
        return native_frame(self._result()[1].features)

    def build_images(self) -> DataFrame:
        return native_frame(self._result()[1].table)

    def build_groups(self) -> DataFrame:
        return DataFrame(deepcopy(self._result()[1].data["group_summary"]))

    def build_report(self) -> Data:
        signature, r = self._result()
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": "materials.batch_images",
                "data": deepcopy(r.data),
                "warnings": list(r.warnings),
                "artifacts": list(r.artifacts),
                "provenance": {
                    "input_sha256": signature,
                    "parameters": self._config(),
                    "raw_preserved": True,
                },
            }
        )

    def build_summary(self) -> Message:
        r = self._result()[1]
        counts = r.data["counts"]
        return Message(
            text=f"图像 {counts['total']} 张，完成 {counts['completed']}，失败 {counts['failed']}；"
            f"检测区域 {len(r.features)} 个；状态 {r.data['execution_status']}。"
        )

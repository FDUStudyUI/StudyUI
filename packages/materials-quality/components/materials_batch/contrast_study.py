"""Native unit-aware study forms."""

import hashlib
import json
from copy import deepcopy

import pandas as pd
from lfx.custom import Component
from lfx.io import DataFrameInput, DropdownInput, FloatInput, Output
from lfx.schema import Data, DataFrame, Message

from materials_quality.batch.native import native_frame, prepare_form
from materials_quality.context import table_fingerprint
from materials_quality.science.contrast_study import contrast_study


class ContrastStudy(Component):
    display_name = "材料批量·实验组对照研究"
    description = "先按实验单位平均技术重复，再输出描述统计、总体检验、两两比较、效应量及 Holm/FDR。"
    name = "ContrastStudy"
    icon = "ChartColumnIncreasing"
    inputs = (
        [DataFrameInput(name="input_table", display_name="长格式实验表", required=True)]
        + [
            DropdownInput(name=f"{key}_column", display_name=label, options=[key], value=key, combobox=True)
            for key, label in [
                ("group", "分组列"),
                ("variable", "变量标识列"),
                ("value", "测量值列"),
                ("sample_id", "技术样本 ID 列"),
                ("experimental_unit", "独立实验单位/配对 ID 列"),
            ]
        ]
        + [
            DropdownInput(
                name="design",
                display_name="实验设计",
                options=["independent", "paired"],
                value="independent",
                info="配对仅支持两组，要求实验单位完整匹配；独立设计不允许跨组重复单位。",
            ),
            DropdownInput(
                name="strategy",
                display_name="统计策略",
                options=["parametric", "nonparametric"],
                value="parametric",
                info="参数法：Welch t/ANOVA 或配对 t；非参数：Mann–Whitney/Kruskal 或 Wilcoxon。",
            ),
            DropdownInput(
                name="correction", display_name="两两比较多重校正", options=["holm", "fdr_bh"], value="holm"
            ),
            FloatInput(name="alpha", display_name="显著性 α", value=0.05),
        ]
    )
    outputs = [
        Output(name=n, display_name=d, method=m, group_outputs=True)
        for n, d, m in [
            ("features", "两两检验与效应量", "build_features"),
            ("descriptives", "各组实验单位描述统计", "build_descriptives"),
            ("units", "实验单位均值表", "build_units"),
            ("report", "总体检验与追溯", "build_report"),
            ("summary", "运行摘要", "build_summary"),
        ]
    ]

    def _config(self):
        c = {
            key: getattr(self, f"{key}_column")
            for key in ("group", "variable", "value", "sample_id", "experimental_unit")
        }
        c.update(design=self.design, strategy=self.strategy, correction=self.correction, alpha=self.alpha)
        return c

    def _result(self):
        c = self._config()
        signature = hashlib.sha256(
            (table_fingerprint(self.input_table) + json.dumps(c, sort_keys=True)).encode()
        ).hexdigest()
        cached = self._ctx.get("contrast_study")
        if cached is None or cached[0] != signature:
            cached = (signature, contrast_study(self.input_table, config=c))
            self._ctx["contrast_study"] = cached
        return cached

    def build_features(self) -> DataFrame:
        return native_frame(self._result()[1].features)

    def build_descriptives(self) -> DataFrame:
        return DataFrame(deepcopy(self._result()[1].data["descriptives"]))

    def build_units(self) -> DataFrame:
        return native_frame(self._result()[1].table)

    def to_frontend_node(self, *args, **kwargs):
        return prepare_form(super().to_frontend_node(*args, **kwargs))

    def build_report(self) -> Data:
        signature, r = self._result()
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": "materials.contrast_study",
                "data": deepcopy(r.data),
                "warnings": list(r.warnings),
                "artifacts": [],
                "provenance": {
                    "input_sha256": signature,
                    "parameters": self._config(),
                    "raw_preserved": True,
                },
            }
        )

    def build_summary(self) -> Message:
        r = self._result()[1]
        return Message(
            text=f"实验单位均值 {len(r.table)} 条，两两比较 {len(r.features)} 项；"
            f"{self.design} / {self.strategy}，{self.correction} 校正。"
        )

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name == "input_table" and isinstance(field_value, pd.DataFrame):
            for key in ("group", "variable", "value", "sample_id", "experimental_unit"):
                build_config[f"{key}_column"]["options"] = list(field_value.columns)
        return build_config

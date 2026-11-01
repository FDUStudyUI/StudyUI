"""Native overall-table model comparison using one shared evaluation plan."""

import json

from lfx.custom import Component
from lfx.io import BoolInput, DataFrameInput, DropdownInput, FloatInput, IntInput, MultiselectInput, Output
from lfx.schema import Data, DataFrame

from materials_quality.batch.native import native_frame, prepare_form
from materials_quality.context import table_fingerprint
from materials_quality.science.model_comparison import MODEL_NAMES, compare_models


class MaterialModelComparison(Component):
    display_name = "材料统计·多模型评估"
    description = "将输入表作为整体，用相同训练/测试划分比较多个模型；时间验证只使用过去训练。"
    name = "MaterialModelComparison"
    icon = "ChartNoAxesCombined"
    inputs = [
        DataFrameInput(name="input_table", display_name="整体输入表", required=True),
        MultiselectInput(
            name="models",
            display_name="候选模型",
            options=list(MODEL_NAMES),
            value=["linear", "ridge", "random_forest"],
        ),
        MultiselectInput(
            name="features", display_name="特征列（按顺序）", options=["x"], combobox=True, value=["x"]
        ),
        DropdownInput(name="target", display_name="目标列", options=["y"], combobox=True, value="y"),
        DropdownInput(
            name="method",
            display_name="评估方式",
            options=["holdout", "cv"],
            value="holdout",
            real_time_refresh=True,
        ),
        DropdownInput(
            name="validation_split",
            display_name="拆分策略",
            options=["random", "chronological_split", "blocked_cv"],
            value="random",
            real_time_refresh=True,
            info="chronological_split 使用 holdout；blocked_cv 使用 cv。跨时间边界的重复试样会报错。",
        ),
        DropdownInput(
            name="time_column", display_name="时间列", options=[], combobox=True, value="", show=False
        ),
        DropdownInput(
            name="id_column",
            display_name="唯一观测 ID 列（可选）",
            options=[],
            combobox=True,
            value="",
            advanced=True,
        ),
        DropdownInput(
            name="group_column",
            display_name="独立试样分组列（可选）",
            options=[],
            combobox=True,
            value="",
            advanced=True,
        ),
        FloatInput(name="test_size", display_name="测试集比例", value=0.2),
        IntInput(name="folds", display_name="验证折数", value=5, show=False),
        IntInput(name="seed", display_name="随机种子", value=42, advanced=True),
        BoolInput(name="residual_diagnostics", display_name="报告残差诊断", value=False),
        BoolInput(
            name="linear_trend_ci",
            display_name="单变量 OLS 均值置信带",
            value=False,
            advanced=True,
            info="只在训练特征范围内报告均值区间，不是个体预测或未来外推区间；异方差时不输出经典置信带。",
        ),
        FloatInput(name="confidence_level", display_name="均值置信水平", value=0.95, advanced=True),
    ]
    outputs = [
        Output(name="scores", display_name="模型评分表", method="build_scores", group_outputs=True),
        Output(name="report", display_name="拆分与评估追溯", method="build_report", group_outputs=True),
    ]

    def _process_connection_or_parameters(self, key, value):
        if isinstance(value, list) and not value and key in self._inputs:
            return self._process_connection_or_parameter(key, value)
        return super()._process_connection_or_parameters(key, value)

    def to_frontend_node(self, *args, **kwargs):
        result = super().to_frontend_node(*args, **kwargs)
        template = result["data"]["node"]["template"]
        self.update_build_config(template, self.validation_split, "validation_split")
        prepare_form(result)
        return result

    def update_build_config(self, build_config, field_value, field_name=None):
        if field_name in build_config:
            build_config[field_name]["value"] = field_value
        mode = build_config.get("validation_split", {}).get("value", "random")
        method = build_config.get("method", {}).get("value", "holdout")
        build_config["time_column"]["show"] = mode != "random"
        build_config["folds"]["show"] = method == "cv"
        build_config["test_size"]["show"] = method == "holdout"
        frame = getattr(self, "input_table", None)
        if frame is not None and hasattr(frame, "columns"):
            columns = [str(column) for column in frame.columns]
            for name in ("features", "target", "time_column", "id_column", "group_column"):
                build_config[name]["options"] = columns
        return build_config

    def _result(self):
        config = {
            name: getattr(self, name)
            for name in (
                "models",
                "features",
                "target",
                "method",
                "validation_split",
                "test_size",
                "folds",
                "seed",
                "residual_diagnostics",
                "linear_trend_ci",
                "confidence_level",
            )
        }
        config.update(
            {
                name: getattr(self, name)
                for name in ("time_column", "id_column", "group_column")
                if getattr(self, name)
            }
        )
        signature = json.dumps(
            [table_fingerprint(self.input_table), config], ensure_ascii=False, sort_keys=True
        )
        cached = self._ctx.get("model_comparison")
        if cached and cached["signature"] == signature:
            return cached["result"]
        result = compare_models(self.input_table, config)
        self._ctx["model_comparison"] = {"signature": signature, "result": result}
        self.status = f"完成 {len(result.table)} 个模型的相同拆分比较"
        return result

    def build_scores(self) -> DataFrame:
        result = self._result()
        return native_frame(result.table)

    def build_report(self) -> Data:
        result = self._result()
        return Data(
            data={
                "schema_version": "science-result/1",
                "operation": "stats.model_comparison",
                "execution_status": "completed",
                "data": result.data,
                "warnings": result.warnings,
                "artifacts": [],
                "table_available": True,
                "provenance": {
                    "input_table_fingerprint": table_fingerprint(self.input_table),
                    "scope": "Explicit overall input table; positions refer to its original row order.",
                },
            }
        )

from lfx.custom import Component
from lfx.io import DropdownInput, Output
from lfx.schema import Data, DataFrame

from materials_quality.langflow_support import (
    check_inputs,
    check_outputs,
    findings_table,
    original_table,
    report_data,
)
from materials_quality.quality_ui import (
    JSON,
    QualityFormMixin,
    config_mode,
    form_inputs,
    legacy_inputs,
    quality_parameters,
)
from materials_quality.units import check_units


def unit_outputs(mode, enabled):
    outputs = check_outputs()
    if mode == JSON or enabled is True:
        outputs.append(
            Output(
                name="converted_table",
                display_name="换算表格（仅成功时）",
                method="build_converted_table",
                group_outputs=True,
            )
        )
    return outputs


def conversion_enabled(value):
    if type(value) is bool:
        return value
    if value in ("是", "true", "True"):
        return True
    if value in ("否", "false", "False"):
        return False
    raise ValueError("convert_values: 请选择是或否")


class MaterialUnitCheck(QualityFormMixin, Component):
    display_name = "材料数据·单位检查"
    description = "检查声明/单元格单位、量纲兼容及混合单位；不猜测单位或自动换算。"
    icon = "Ruler"
    name = "MaterialUnitCheck"
    quality_check = "units"
    inputs = check_inputs(
        [
            DropdownInput(
                name=field.name,
                display_name=field.display_name,
                options=["否", "是"],
                value="否",
                real_time_refresh=True,
                input_types=[],
                info="显式启用后显示换算端口；表单模式换算受阻时会报错，请先查看检查报告。",
            )
            if field.name == "convert_values"
            else field
            for field in [*form_inputs("units"), *legacy_inputs("units")]
        ]
    )
    outputs = check_outputs()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._sync_conversion_outputs()

    def _sync_conversion_outputs(self):
        outputs = unit_outputs(config_mode(self), conversion_enabled(self.convert_values))
        self._set_output_types(outputs)
        self.outputs = outputs
        self._outputs_map = {output.name: output for output in outputs}

    def _pre_run_setup(self):
        # Graph imports apply saved attributes after construction, bypassing set().
        self._sync_conversion_outputs()

    def set(self, *args, **kwargs):
        if "convert_values" in kwargs:
            kwargs["convert_values"] = "是" if conversion_enabled(kwargs["convert_values"]) else "否"
        result = super().set(*args, **kwargs)
        self._sync_conversion_outputs()
        return result

    def to_frontend_node(self, *args, **kwargs):
        self._sync_conversion_outputs()
        result = super().to_frontend_node(*args, **kwargs)
        result["data"]["node"]["template"]["convert_values"]["value"] = (
            "是" if conversion_enabled(self.convert_values) else "否"
        )
        return result

    def update_outputs(self, frontend_node, field_name, field_value):
        template = frontend_node.get("template", {})
        mode = (
            field_value
            if field_name == "ui_mode"
            else template.get("ui_mode", {}).get("value", config_mode(self))
        )
        enabled = (
            field_value
            if field_name == "convert_values"
            else template.get("convert_values", {}).get("value", self.convert_values)
        )
        outputs = unit_outputs(mode, conversion_enabled(enabled))
        self._set_output_types(outputs)
        frontend_node["outputs"] = outputs
        return frontend_node

    def build_report(self) -> Data:
        if self.quality_context is not None:
            return report_data(self, check_units)
        parameters = quality_parameters(self, "units")
        parameters["convert_values"] = conversion_enabled(parameters["convert_values"])
        return report_data(self, check_units, **parameters)

    def pass_table(self) -> DataFrame:
        return original_table(self)

    def build_findings(self) -> DataFrame:
        return findings_table(self.build_report().data)

    def build_converted_table(self) -> DataFrame:
        from materials_quality.science.preprocessing import convert_units

        report = self.build_report().data
        if not report["metrics"]["converted"]:
            reason = report["metrics"].get("conversion_blocked", "Enable conversion for this output.")
            self.status = f"Unit conversion unavailable: {reason}; see diagnostic report."
            if config_mode(self) != JSON:
                raise ValueError(f"换算表格不可用：{reason}；请查看检查报告并确认已启用换算。")
            legacy = DataFrame(columns=list(self.input_table.columns))
            legacy.attrs["table_available"] = False
            legacy.attrs["absence_reason"] = str(reason)
            return legacy
        parameters = report["parameters"]
        selected = parameters.get("columns") or list(parameters["expected_units"])
        converted = convert_units(
            self.input_table,
            config={
                "source_units": parameters["source_units"],
                "target_units": {c: parameters["expected_units"][c] for c in selected},
                "missing_tokens": parameters.get("missing_tokens"),
            },
        )
        from copy import deepcopy

        table = DataFrame(converted.table)
        table.attrs = deepcopy(converted.table.attrs)
        return table

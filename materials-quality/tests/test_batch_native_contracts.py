import pandas as pd


def test_custom_selected_column_survives_frontend_dropdown_options():
    from components.materials_batch.batch_source import MaterialBatchInput
    from materials_quality.science.catalog import component_class

    source = MaterialBatchInput().set(source_mode="grouped", sample_column="custom_specimen")
    template = source.to_frontend_node()["data"]["node"]["template"]
    assert "custom_specimen" in template["sample_column"]["options"]
    refreshed = source.update_build_config(template, "grouped", "source_mode")
    assert "custom_specimen" in refreshed["sample_column"]["options"]
    plot = component_class("viz.mechanics")().set(ui_mode="form", cfg_x="strain_fraction", cfg_y="stress_MPa")
    template = plot.to_frontend_node()["data"]["node"]["template"]
    assert "strain_fraction" in template["cfg_x"]["options"]
    assert "stress_MPa" in template["cfg_y"]["options"]


def test_native_frame_preserves_units_and_is_independent():
    from materials_quality.batch.native import native_frame

    source = pd.DataFrame({"x": [1.0, 2.0]})
    source.attrs = {"units": {"x": "nm"}}
    result = native_frame(source)
    assert result.attrs == source.attrs
    result.attrs["units"]["x"] = "um"
    assert source.attrs["units"]["x"] == "nm"


def test_spectrum_card_shows_only_active_controls():
    from components.materials_batch.batch_spectrum_analyzer import BatchSpectrumAnalyzer

    node = BatchSpectrumAnalyzer()
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert not template["lambda10_min_nm"]["show"]
    assert not template["smooth_window"]["show"]
    template = node.update_build_config(template, True, "lambda10_enabled")
    assert template["lambda10_min_nm"]["show"]

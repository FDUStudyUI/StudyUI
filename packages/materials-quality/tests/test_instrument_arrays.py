import importlib
import json

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def hdf_file(tmp_path):
    h5py = pytest.importorskip("h5py")
    path = tmp_path / "synthetic.h5"
    with h5py.File(path, "w") as root:
        root.attrs["experiment"] = "synthetic"
        group = root.create_group("measurement")
        group.create_dataset("intensity", data=[[2.0, 4.0, 6.0], [3.0, 6.0, 9.0]]).attrs["units"] = "counts"
        group.create_dataset("wavelength", data=[500.0, 600.0, 700.0]).attrs["units"] = "nm"
        group.create_dataset("id", data=np.array([b"001", b"002"], dtype="S3"))
    return path


def selection(path, **extra):
    return {
        "path": str(path),
        "dataset_path": "/measurement/intensity",
        "x_axis_path": "/measurement/wavelength",
        "group_axis_path": "/measurement/id",
        "spectrum_axis": 1,
        **extra,
    }


def test_hdf_tree_lists_real_shapes_dtypes_and_attributes_without_reading_data(hdf_file):
    from materials_quality.science.instrument_arrays import inspect_array_tree

    result = inspect_array_tree(hdf_file)
    dataset = result.table.set_index("path").loc["/measurement/intensity"]
    assert dataset["shape"] == [2, 3] and dataset["dtype"] == "float64"
    assert dataset["attrs"] == {"units": "counts"}
    assert result.data["root_attrs"]["experiment"] == "synthetic"
    assert result.data["mode"] == "browse"
    json.dumps(result.data, allow_nan=False)


def test_explicit_hdf_axes_produce_complete_long_curves_preserving_ids_units_and_source(hdf_file):
    from materials_quality.science.io_nodes import instrument_import

    before = hdf_file.read_bytes()
    result = instrument_import(config=selection(hdf_file))
    assert result.table.to_dict("list") == {
        "curve_id": ["001", "001", "001", "002", "002", "002"],
        "x": [500.0, 600.0, 700.0, 500.0, 600.0, 700.0],
        "y": [2.0, 4.0, 6.0, 3.0, 6.0, 9.0],
    }
    assert result.table.attrs["units"] == {"x": "nm", "y": "counts"}
    assert result.data["selected_dataset"]["shape"] == [2, 3]
    assert hdf_file.read_bytes() == before


def test_array_dimensions_and_axes_are_never_guessed(hdf_file):
    from materials_quality.science.io_nodes import instrument_import

    config = selection(hdf_file)
    config.pop("spectrum_axis")
    with pytest.raises(ValueError, match="spectrum_axis"):
        instrument_import(config=config)
    with pytest.raises(ValueError, match="axis|length|shape"):
        instrument_import(config=selection(hdf_file, spectrum_axis=0))
    with pytest.raises(ValueError, match="dataset|path"):
        instrument_import(config=selection(hdf_file, dataset_path="/missing"))
    with pytest.raises(ValueError, match="path"):
        instrument_import(config=selection(hdf_file, dataset_path="/measurement/../intensity"))


def test_large_sparse_hdf_is_rejected_from_metadata_before_allocation(tmp_path):
    h5py = pytest.importorskip("h5py")
    from materials_quality.science.io_nodes import instrument_import

    path = tmp_path / "huge.h5"
    with h5py.File(path, "w") as root:
        root.create_dataset("signal", shape=(1_000_000_000,), dtype="f8", chunks=(1000,))
        root.create_dataset("axis", shape=(1_000_000_000,), dtype="f8", chunks=(1000,))
    with pytest.raises(ValueError, match="limit|max_.*|large"):
        instrument_import(config={"path": str(path), "dataset_path": "/signal", "x_axis_path": "/axis"})


def test_hdf_external_soft_virtual_and_object_datasets_are_not_loaded(tmp_path):
    h5py = pytest.importorskip("h5py")
    from materials_quality.science.instrument_arrays import inspect_array_tree
    from materials_quality.science.io_nodes import instrument_import

    outside = tmp_path / "outside.h5"
    with h5py.File(outside, "w") as root:
        root["signal"] = [1.0, 2.0, 3.0]
    path = tmp_path / "links.h5"
    with h5py.File(path, "w") as root:
        root["axis"] = [500.0, 600.0, 700.0]
        root["external"] = h5py.ExternalLink(str(outside), "/signal")
        root["soft"] = h5py.SoftLink("/axis")
        root.create_dataset("objects", data=["one", "two"], dtype=h5py.string_dtype())
        layout = h5py.VirtualLayout(shape=(3,), dtype="f8")
        layout[:] = h5py.VirtualSource(str(outside), "signal", shape=(3,))
        root.create_virtual_dataset("virtual", layout)
        root.create_dataset(
            "external_storage", shape=(3,), dtype="f8", external=[("not-opened.raw", 0, h5py.h5f.UNLIMITED)]
        )
    tree = inspect_array_tree(path).table.set_index("path")
    assert not tree.loc["/external", "readable"]
    for dataset in ("/external", "/soft", "/objects", "/virtual", "/external_storage"):
        with pytest.raises(ValueError, match="link|dtype|object|safe|blocked"):
            instrument_import(config={"path": str(path), "dataset_path": dataset, "x_axis_path": "/axis"})


def test_optional_dependency_error_names_installable_library(tmp_path, monkeypatch):
    from materials_quality.science.instrument_arrays import inspect_array_tree

    path = tmp_path / "sample.h5"
    path.write_bytes(b"synthetic")
    original = importlib.import_module

    def unavailable(name, *args, **kwargs):
        if name == "h5py":
            raise ImportError("not installed")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", unavailable)
    with pytest.raises(ValueError, match="pip install.*h5py"):
        inspect_array_tree(path)


def test_netcdf_real_local_grouped_variables_and_units(tmp_path):
    netcdf = pytest.importorskip("netCDF4")
    from materials_quality.science.io_nodes import instrument_import

    path = tmp_path / "synthetic.nc"
    # Native netCDF-C on Windows cannot create files at this Unicode workspace
    # path. Its documented in-memory API builds a real file byte image instead.
    root = netcdf.Dataset("synthetic.nc", "w", memory=4096)
    try:
        group = root.createGroup("measurement")
        group.createDimension("particle", 2)
        group.createDimension("wavelength", 3)
        group.createVariable("intensity", "f8", ("particle", "wavelength"))[:] = [[2, 4, 6], [3, 6, 9]]
        group.createVariable("wavelength", "f8", ("wavelength",))[:] = [500, 600, 700]
        group.variables["wavelength"].units = "nm"
        group.createVariable("id", "i4", ("particle",))[:] = [10, 20]
    finally:
        path.write_bytes(root.close())
    result = instrument_import(config=selection(path))
    assert result.table["curve_id"].tolist() == [10, 10, 10, 20, 20, 20]
    assert result.table["y"].tolist() == [2, 4, 6, 3, 6, 9]
    assert result.table.attrs["units"]["x"] == "nm"


def test_zarr_real_local_store_and_pickle_metadata_rejection(tmp_path):
    zarr = pytest.importorskip("zarr")
    from materials_quality.science.io_nodes import instrument_import

    path = tmp_path / "synthetic.zarr"
    root = zarr.open_group(str(path), mode="w")
    group = root.create_group("measurement")
    group.create_dataset("intensity", data=np.array([[2.0, 4.0, 6.0], [3.0, 6.0, 9.0]]))
    group.create_dataset("wavelength", data=np.array([500.0, 600.0, 700.0]))
    group.create_dataset("id", data=np.array([b"001", b"002"], dtype="S3"))
    result = instrument_import(config=selection(path))
    assert result.table.curve_id.tolist() == ["001"] * 3 + ["002"] * 3
    metadata = path / "measurement" / "intensity" / ".zarray"
    content = json.loads(metadata.read_text(encoding="utf-8"))
    content["filters"] = [{"id": "pickle", "protocol": 5}]
    metadata.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="codec|pickle|safe"):
        instrument_import(config=selection(path))


def test_fixed_width_unicode_identifiers_are_not_truncated_or_coerced(tmp_path):
    zarr = pytest.importorskip("zarr")
    from materials_quality.science.io_nodes import instrument_import

    path = tmp_path / "long_ids.zarr"
    root = zarr.open_group(str(path), mode="w")
    ids = ["A" * 5000 + "first", "A" * 5000 + "second"]
    root.create_dataset("signal", data=np.array([[1.0, 2.0], [3.0, 4.0]]))
    root.create_dataset("axis", data=np.array([500.0, 600.0]))
    root.create_dataset("ids", data=np.array(ids))
    result = instrument_import(
        config={
            "path": str(path),
            "dataset_path": "/signal",
            "x_axis_path": "/axis",
            "group_axis_path": "/ids",
            "spectrum_axis": 1,
            "max_bytes": 100_000,
        }
    )
    assert result.table.curve_id.tolist() == [ids[0], ids[0], ids[1], ids[1]]


def test_reference_normalization_flags_invalid_channels_and_reports_defined_snr(hdf_file):
    h5py = pytest.importorskip("h5py")
    from materials_quality.science.io_nodes import instrument_import

    with h5py.File(hdf_file, "a") as root:
        root["background"] = [1.0, 1.0, 1.0]
        root["reference"] = [3.0, 1.0, 5.0]
    result = instrument_import(
        config=selection(
            hdf_file, background_path="/background", reference_path="/reference", noise_range=[500, 600]
        )
    )
    assert result.table.y.tolist()[0] == 0.5
    assert result.table.invalid_channel.tolist() == [False, True, False] * 2
    assert pd.isna(result.table.y.iloc[1])
    assert result.data["normalization"] == "(signal-background)/(reference-background)"
    assert "snr_definition" in result.data
    assert result.data["invalid_channel_count"] == 2


def test_reference_units_must_match_and_higher_dimensions_need_explicit_export(hdf_file):
    h5py = pytest.importorskip("h5py")
    from materials_quality.science.io_nodes import instrument_import

    with h5py.File(hdf_file, "a") as root:
        root.create_dataset("wrong_unit", data=[1.0, 2.0, 3.0]).attrs["units"] = "V"
        root.create_dataset("cube", shape=(2, 2, 3), dtype="f8")
    with pytest.raises(ValueError, match="unit"):
        instrument_import(config=selection(hdf_file, reference_path="/wrong_unit"))
    with pytest.raises(ValueError, match="1D|2D|dimensional"):
        instrument_import(config=selection(hdf_file, dataset_path="/cube"))


def test_table_import_report_lists_sheets_schema_and_twenty_row_preview(tmp_path):
    from materials_quality.science.io_nodes import table_import

    source = tmp_path / "sheets.xlsx"
    with pd.ExcelWriter(source) as writer:
        pd.DataFrame({"id": [f"{i:03d}" for i in range(25)], "y": range(25)}).to_excel(
            writer, sheet_name="Data", index=False
        )
        pd.DataFrame({"x": [1]}).to_excel(writer, sheet_name="Other", index=False)
    result = table_import(config={"path": str(source), "sheet": "Data"})
    assert result.data["sheet_names"] == ["Data", "Other"]
    assert len(result.data["preview"]) == 20 and result.data["preview"][0]["id"] == "000"
    assert result.data["schema"]["id"]["conversion"] == "preserved-leading-zero"


def test_native_instrument_controls_expose_array_paths_without_json():
    from materials_quality.science.catalog import component_class

    node = component_class("io.instrument_import")()
    template = node.to_frontend_node()["data"]["node"]["template"]
    assert template["cfg_mode"]["options"] == ["read", "browse"]
    assert "cfg_dataset_path" in template and "cfg_spectrum_axis" in template
    assert template["cfg_dataset_path"].get("combobox") is True
    assert {"h5", "hdf5", "nc", "netcdf"} <= set(template["source_file"]["fileTypes"])

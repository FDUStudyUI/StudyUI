import hashlib

import numpy as np
import pytest

from materials_quality.material_examples import compile_example, examples, prepared_input, read_source
from materials_quality.science.catalog import component_class


@pytest.mark.parametrize("item", examples(), ids=lambda i: i["id"])
def test_original_instrument_sources_compile_to_native_editable_graphs(item):
    from materials_quality.agent.workflow import apply_actions

    assert hashlib.sha256(read_source(item["id"])).hexdigest() == item["sha256"]
    assert item["source"]["license"] == "cc-by-4.0"
    spec, (table, _, _, _) = prepared_input(item["id"])
    assert len(table) > 500
    assert np.isfinite(table[[spec["x"], spec["y"]]].to_numpy(float)).all()
    compiled = compile_example(item["id"])
    keys = [
        "io.table_import",
        "io.instrument_import",
        "preprocess.filter",
        "materials.mechanics",
        "materials.spectra",
        "materials.xrd",
        "viz.spectra",
        "export.report",
        "export.table",
    ]
    catalog = {
        "materials_examples": {
            component_class(k)().name: component_class(k)().to_frontend_node()["data"]["node"] for k in keys
        }
    }
    graph, _ = apply_actions({"data": {"nodes": [], "edges": []}}, compiled["actions"], catalog)
    assert compiled["protocol"]["assessment"]["status"] == "ready"
    assert len(graph["data"]["nodes"]) in {5, 6}
    assert all(n["data"]["node"]["template"]["ui_mode"]["value"] == "form" for n in graph["data"]["nodes"])


def test_instrument_geometry_is_auditable_not_taken_from_filename():
    item = examples()[0]
    _, (table, _, _, _) = prepared_input(item["id"])
    assert np.allclose(table.stress, table.load_N / item["preparation"]["area_mm2"])
    assert np.allclose(table.strain, table.extension_mm / item["preparation"]["gauge_mm"])
    assert "Index" in table

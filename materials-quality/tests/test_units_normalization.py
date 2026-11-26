import pandas as pd
import pytest

from materials_quality.science import materials
from materials_quality.science.units import normalize_unit_label


def test_normalize_common_aliases():
    assert normalize_unit_label("°C", "temperature") == "degC"
    assert normalize_unit_label("celsius", "temperature") == "degC"
    assert normalize_unit_label("minute", "time") == "min"
    assert normalize_unit_label("pct", "strain") == "%"
    assert normalize_unit_label("mpa", "stress") == "MPa"
    assert normalize_unit_label("degrees", "angle") == "deg"
    assert normalize_unit_label("unknown", "stress") == "unknown"


def test_mechanics_accepts_unit_aliases():
    table = pd.DataFrame(
        {
            "strain": [i * 1e-5 for i in range(1, 61)],
            "stress": [i * 2.0 for i in range(1, 61)],
        }
    )
    result = materials.mechanics(
        table,
        config={
            "strain": "strain",
            "stress": "stress",
            "fit_range": [1e-5, 3e-4],
            "strain_unit": "fraction",
            "stress_unit": "mpa",
            "fracture_confirmed": True,
        },
    )
    assert result.data["elastic_modulus_MPa"] == pytest.approx(200000.0, rel=1e-3)


def test_thermal_accepts_temperature_alias():
    table = pd.DataFrame({"t": [0.0, 10.0, 20.0], "m": [100.0, 99.0, 98.0]})
    result = materials.thermal(
        table,
        config={"x": "t", "y": "m", "kind": "tg", "x_unit": "°C", "y_unit": "%"},
    )
    assert result.data["x_unit"] == "degC"

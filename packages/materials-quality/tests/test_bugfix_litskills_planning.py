"""Regressions: planning input validation and unit diagnostics must stay actionable."""

import pandas as pd
import pytest

from materials_quality.skills.planning import make_plan


def test_make_plan_rejects_non_object_parameters():
    table = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="parameters"):
        make_plan(table, parameters=[{"x_unit": "nm"}])


def test_unparseable_upstream_unit_is_named_in_the_issue():
    table = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [1.0, 2.0, 3.0]})
    table.attrs["units"] = {"x": "banana"}
    plan = make_plan(
        table,
        task="spectra",
        parameters={
            "curve_id": "x",
            "x": "x",
            "y": "y",
            "x_unit": "nm",
            "y_unit": "counts",
            "peak_window": [650, 850],
            "unit_mode": "descriptive",
            "unit_confirmed": False,
        },
    )
    messages = [item["message"] for item in plan["issues"]]
    assert any("banana" in message for message in messages), messages

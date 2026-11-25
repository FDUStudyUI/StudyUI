"""JCAMP XFACTOR scales every abscissa, including the reported spacing."""

import pytest

from materials_quality.science.io_nodes import instrument_import


def test_jcamp_xfactor_scales_delta_x(tmp_path):
    source = tmp_path / "factor.jdx"
    source.write_text(
        "##TITLE=factor\n##FIRSTX=4000\n##LASTX=4002\n##NPOINTS=3\n##XFACTOR=0.001\n"
        "##YFACTOR=1\n##XYDATA=(X++(Y..Y))\n4000 1 2 3\n##END=\n",
        encoding="utf-8",
    )

    result = instrument_import(config={"path": str(source)})

    assert result.table["x"].tolist() == pytest.approx([4.0, 4.001, 4.002])
    assert result.table["y"].tolist() == pytest.approx([1.0, 2.0, 3.0])


def test_jcamp_explicit_deltax_also_scales_with_xfactor(tmp_path):
    source = tmp_path / "delta.jdx"
    source.write_text(
        "##TITLE=delta\n##FIRSTX=10\n##LASTX=12\n##NPOINTS=3\n##DELTAX=1\n##XFACTOR=2\n"
        "##XYDATA=(X++(Y..Y))\n10 1 2 3\n##END=\n",
        encoding="utf-8",
    )

    result = instrument_import(config={"path": str(source)})

    assert result.table["x"].tolist() == pytest.approx([20.0, 22.0, 24.0])

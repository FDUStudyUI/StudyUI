import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "materials_quality.science_tools", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )


def test_list_operations():
    result = run_cli("list")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    keys = {item["key"] for item in payload["operations"]}
    assert "materials.xrd" in keys
    assert "materials.mechanics" in keys
    assert len(keys) >= 40


def test_show_operation():
    result = run_cli("show", "materials.xrd")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["key"] == "materials.xrd"
    assert payload["function"].startswith("materials_quality.science.")


def test_run_mechanics_on_demo_data(tmp_path):
    table = tmp_path / "tensile.csv"
    table.write_text(
        "strain,stress\n" + "\n".join(f"{i * 1e-5:.6f},{i * 2.0:.1f}" for i in range(1, 61)),
        encoding="utf-8",
    )
    config = {
        "strain": "strain",
        "stress": "stress",
        "fit_range": [1e-5, 0.0003],
        "strain_unit": "fraction",
        "stress_unit": "MPa",
        "fracture_confirmed": True,
    }
    result = run_cli("run", "materials.mechanics", "--table", str(table), "--config", json.dumps(config))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    data = payload["result"]["data"]
    assert data["elastic_modulus_MPa"] == pytest.approx(200000.0, rel=1e-3)
    assert "warnings" in payload["result"]


def test_run_reports_strict_errors(tmp_path):
    table = tmp_path / "tensile.csv"
    table.write_text("strain,stress\n0.0,0.0\n0.001,200.0\n", encoding="utf-8")
    result = run_cli(
        "run",
        "materials.mechanics",
        "--table",
        str(table),
        "--config",
        json.dumps({"strain": "strain", "stress": "stress"}),
    )
    assert result.returncode != 0
    assert "fit_range" in result.stderr or "strain_unit" in result.stderr

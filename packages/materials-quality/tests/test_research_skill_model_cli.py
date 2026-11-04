"""Real local HTTP transport and subprocess CLI; no paid model or API key needed."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pandas as pd
import pytest


@pytest.fixture
def server():
    calls = []
    state = {
        "content": json.dumps(
            {"task": "spectra", "parameters": {"x_unit": "nm", "y_unit": "counts", "peak_window": [650, 850]}}
        )
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(state.get("status", 200))
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": state["content"]}}]}).encode())

        def log_message(self, *args):
            pass

    http = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}/v1", calls, state
    http.shutdown()
    http.server_close()
    thread.join()


def test_model_uses_schema_not_raw_rows_and_shares_plan_validation(server):
    from materials_quality.skills.model import suggest_plan

    url, calls, state = server
    f = pd.DataFrame(
        {"curve_id": ["CONFIDENTIAL_PARTICLE"] * 3, "wavelength_nm": [650, 700, 750], "intensity": [1, 2, 1]}
    )
    parameters = {"x_unit": "nm", "y_unit": "counts", "peak_window": [650, 850]}
    pending = suggest_plan(f, "比较光谱候选峰", base_url=url, model="test", api_key="SECRET")
    assert not pending["ready"]  # Model-supplied scientific metadata requires form confirmation.
    p = suggest_plan(f, "比较光谱候选峰", base_url=url, model="test", api_key="SECRET", parameters=parameters)
    assert p["ready"]
    payload = json.dumps(calls, ensure_ascii=False)
    assert "CONFIDENTIAL_PARTICLE" not in payload and "SECRET" not in payload
    assert "wavelength_nm" in payload and "窗口" in payload
    assert p["model_assistance"]["raw_rows_sent"] is False
    from materials_quality.skills.planning import validate_plan

    validate_plan(f, p)
    state["content"] = json.dumps({"task": "spectra", "parameters": {"shell": "run something"}})
    with pytest.raises(ValueError, match="parameter|参数"):
        suggest_plan(f, "光谱", base_url=url, model="test")


@pytest.mark.parametrize(
    "content",
    [
        "```json\n{}\n```",
        '{"task":"spectra","task":"shell","parameters":{}}',
        '{"task":"spectra","parameters":{"prominence":NaN}}',
        "X" * 70000,
    ],
)
def test_invalid_model_output_is_rejected(server, content):
    from materials_quality.skills.model import suggest_plan

    url, _, state = server
    state["content"] = content
    with pytest.raises(ValueError):
        suggest_plan(pd.DataFrame({"x": [1]}), "光谱", base_url=url, model="test")


def test_missing_config_and_http_error_do_not_leak_secrets(server, monkeypatch):
    from materials_quality.skills.model import suggest_plan

    for key in ("STUDYUI_MODEL_BASE_URL", "STUDYUI_MODEL", "STUDYUI_MODEL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="模型|配置"):
        suggest_plan(pd.DataFrame({"x": [1]}), "光谱")
    url, _, state = server
    state["status"] = 401
    with pytest.raises(ValueError) as error:
        suggest_plan(pd.DataFrame({"x": [1]}), "光谱", base_url=url, model="test", api_key="SECRET")
    assert "SECRET" not in str(error.value)


def test_cli_lists_previews_and_runs_without_json(tmp_path):
    env = {**os.environ, "PYTHONUTF8": "1"}
    cmd = [sys.executable, "-m", "materials_quality.skills"]
    listed = subprocess.run([*cmd, "list"], capture_output=True, text=True, encoding="utf-8", env=env)
    assert listed.returncode == 0, listed.stderr
    assert len(json.loads(listed.stdout)) == 3
    source = tmp_path / "mechanics.csv"
    pd.DataFrame({"strain": [0, 0.0004, 0.0008, 0.004], "stress": [0, 80, 160, 203]}).to_csv(
        source, index=False
    )
    args = [
        *cmd,
        "run",
        str(source),
        "--task",
        "mechanics",
        "--single-sample",
        "--strain-unit",
        "fraction",
        "--stress-unit",
        "MPa",
        "--fit-range",
        "0",
        ".0008",
        "--output",
        str(tmp_path / "result"),
    ]
    ran = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env)
    assert ran.returncode == 0, ran.stderr
    assert "200000" in ran.stdout
    assert list((tmp_path / "result").rglob("report.html"))


def test_cli_preserves_leading_zero_independent_units_and_literal_na_ids(tmp_path):

    f = pd.DataFrame(
        [
            {"group": g, "variable": "strength", "experimental_unit": u, "sample_id": f"{g}-{u}", "value": v}
            for g, units, values in [
                ("A", ["001", "1", "2", "NA"], [0, 10, 11, 12]),
                ("B", ["004", "4", "5", "6"], [5, 6, 7, 8]),
            ]
            for u, v in zip(units, values, strict=True)
        ]
    )
    path = tmp_path / "study.csv"
    f.to_csv(path, index=False)
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "materials_quality.skills",
            "run",
            str(path),
            "--task",
            "contrast",
            "--design",
            "independent",
            "--value-unit",
            "MPa",
            "--output",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(next((tmp_path / "out").rglob("report.json")).read_text("utf-8"))
    assert [r["count"] for r in report["data"]["descriptives"]] == [4, 4]
    assert [r["mean"] for r in report["data"]["descriptives"]] == pytest.approx([8.25, 6.5])
    units = pd.read_csv(next((tmp_path / "out").rglob("table.csv")), dtype=str, keep_default_na=False)
    assert "001" in units.experimental_unit.tolist() and "NA" in units.experimental_unit.tolist()

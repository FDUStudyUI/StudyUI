"""Safety and operator behavior of the isolated, loopback-only demo launcher."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "scripts" / "start_demo.py"


def load_launcher():
    assert LAUNCHER.is_file(), "The project needs a runnable demo launcher"
    spec = importlib.util.spec_from_file_location("demo_launcher_under_test", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_with_missing_python_is_read_only_even_for_chinese_space_paths(tmp_path):
    demo = load_launcher()
    runtime = tmp_path / "评委 演示" / "runtime"
    before = set(tmp_path.rglob("*"))
    assert (
        demo.main(
            ["--check", "--setup", "--python", str(tmp_path / "missing python"), "--runtime", str(runtime)]
        )
        == 2
    )
    assert set(tmp_path.rglob("*")) == before


def test_check_never_invokes_setup_or_starts_server(tmp_path, monkeypatch):
    demo = load_launcher()
    monkeypatch.setattr(
        demo,
        "probe_environment",
        lambda *a: {"required_missing": [], "optional_missing": [], "python": "3.10.11"},
    )
    monkeypatch.setattr(demo, "setup_environment", lambda *a: pytest.fail("--check attempted setup"))
    monkeypatch.setattr(demo.subprocess, "Popen", lambda *a, **k: pytest.fail("--check started a server"))
    runtime = tmp_path / "不存在 目录"
    assert demo.main(["--check", "--setup", "--python", sys.executable, "--runtime", str(runtime)]) == 0
    assert not runtime.exists()


def test_missing_dependencies_stop_before_any_runtime_writes(tmp_path, monkeypatch, capsys):
    demo = load_launcher()
    monkeypatch.setattr(
        demo,
        "probe_environment",
        lambda *a: {
            "required_missing": ["langflow-base==1.13.0"],
            "optional_missing": [],
            "python": "3.10.11",
        },
    )
    runtime = tmp_path / "untouched"
    assert demo.main(["--python", sys.executable, "--runtime", str(runtime)]) == 2
    assert not runtime.exists()
    assert "langflow-base==1.13.0" in capsys.readouterr().out


def test_setup_with_external_python_never_installs_or_creates_runtime(tmp_path, monkeypatch):
    demo = load_launcher()
    monkeypatch.setattr(demo.subprocess, "run", lambda *a, **k: pytest.fail("external environment mutated"))
    runtime = tmp_path / "untouched"
    assert demo.main(["--setup", "--python", sys.executable, "--runtime", str(runtime)]) == 2
    assert not runtime.exists()


def test_managed_setup_installs_only_into_dedicated_venv(tmp_path, monkeypatch):
    demo = load_launcher()
    commands = []
    package = tmp_path / "中文 路径" / "packages" / "materials-quality"
    package.mkdir(parents=True)
    runtime = tmp_path / ".demo-runtime"
    runtime.mkdir()
    venv = tmp_path / ".demo-venv"
    python = demo.venv_python(venv)

    def run(command, **kwargs):
        commands.append((command, kwargs))
        if "venv" in command:
            python.parent.mkdir(parents=True)
            python.touch()
            (venv / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"prefix": str(venv), "base_prefix": str(tmp_path / "shared")})
        )

    monkeypatch.setattr(demo.subprocess, "run", run)
    demo.setup_environment(venv, package, demo.runtime_environment(runtime))
    assert len(commands) == 3
    assert commands[0][0][-3:] == ["-m", "venv", str(venv)]
    install, options = commands[2]
    assert install[0] == str(python)
    assert install[1:7] == ["-I", "-X", "utf8", "-B", "-m", "pip"]
    assert commands[1][0][1:5] == ["-I", "-X", "utf8", "-B"]
    assert "--no-user" in install
    assert install[install.index("--prefix") + 1] == str(venv)
    assert install[install.index("--cache-dir") + 1] == str(runtime / "pip-cache")
    assert str(package) + "[langflow,science,instruments]" in install
    assert "langflow-base==1.13.0" in install
    assert all(not options.get("shell", False) for _, options in commands)
    assert options["env"]["PIP_CACHE_DIR"] == str(runtime / "pip-cache")


def test_runtime_environment_overrides_inherited_shared_paths(tmp_path, monkeypatch):
    demo = load_launcher()
    monkeypatch.setenv("LANGFLOW_DATABASE_URL", "sqlite:///shared.db")
    monkeypatch.setenv("LANGFLOW_COMPONENTS_PATH", "shared-components")
    env = demo.runtime_environment(tmp_path / "独立 目录")
    runtime = tmp_path / "独立 目录"
    assert env["LANGFLOW_HOST"] == "127.0.0.1"
    assert env["LANGFLOW_OPEN_BROWSER"] == "false"
    assert env["LANGFLOW_CONFIG_DIR"] == str(runtime / "config")
    assert env["LANGFLOW_DATABASE_URL"].endswith("/langflow.db")
    assert str(runtime).replace("\\", "/") in env["LANGFLOW_DATABASE_URL"]
    assert env["TEMP"] == str(runtime / "tmp")
    assert env["TMPDIR"] == str(runtime / "tmp")
    assert env["LANGFLOW_COMPONENTS_PATH"] == str(runtime / "components")
    assert env["OMP_NUM_THREADS"] == "1"
    assert env["MKL_NUM_THREADS"] == "1"
    assert env["OPENBLAS_NUM_THREADS"] == "1"
    assert env["MPLBACKEND"] == "Agg"
    assert env["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
    assert env["DO_NOT_TRACK"] == "true"
    assert os.environ["LANGFLOW_DATABASE_URL"] == "sqlite:///shared.db"


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_invalid_port_is_rejected_without_mutation(tmp_path, port):
    demo = load_launcher()
    with pytest.raises(SystemExit):
        demo.main(["--check", "--port", str(port), "--runtime", str(tmp_path / "unused")])
    assert not (tmp_path / "unused").exists()


def test_busy_port_is_reported_before_launch(tmp_path, monkeypatch, capsys):
    demo = load_launcher()
    monkeypatch.setattr(
        demo,
        "probe_environment",
        lambda *a: {"required_missing": [], "optional_missing": [], "python": "3.10.11"},
    )
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        bound.listen()
        port = bound.getsockname()[1]
        assert (
            demo.main(
                ["--python", sys.executable, "--port", str(port), "--runtime", str(tmp_path / "untouched")]
            )
            == 2
        )
    assert "in use" in capsys.readouterr().out
    assert not (tmp_path / "untouched").exists()


def test_flow_seeding_preserves_same_name_and_posts_only_missing_flows(tmp_path):
    demo = load_launcher()
    for name in ["spectra", "mechanics", "contrast"]:
        (tmp_path / (name + ".json")).write_text(json.dumps({"name": name, "data": {"nodes": []}}))
    created = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            payload = (
                {"access_token": "demo-token"} if self.path.endswith("auto_login") else [{"name": "spectra"}]
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer demo-token"
            created.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(201)
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = demo.seed_flows("http://127.0.0.1:" + str(server.server_port), tmp_path)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert result == {"imported": ["mechanics", "contrast"], "preserved": ["spectra"]}
    assert [item["name"] for item in created] == ["mechanics", "contrast"]


def test_managed_setup_rejects_unrecognized_existing_interpreter(tmp_path, monkeypatch):
    demo = load_launcher()
    venv = tmp_path / ".demo-venv"
    python = demo.venv_python(venv)
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(demo.subprocess, "run", lambda *a, **k: pytest.fail("unverified interpreter invoked"))
    with pytest.raises(ValueError, match="pyvenv.cfg"):
        demo.setup_environment(venv, tmp_path / "package", {})


def test_managed_setup_rejects_shared_prefix_even_with_forged_config(tmp_path, monkeypatch):
    demo = load_launcher()
    venv = tmp_path / ".demo-venv"
    python = demo.venv_python(venv)
    python.parent.mkdir(parents=True)
    python.touch()
    (venv / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"prefix": str(tmp_path / "shared"), "base_prefix": str(tmp_path / "shared")}),
        )

    monkeypatch.setattr(demo.subprocess, "run", run)
    with pytest.raises(ValueError, match="prefix"):
        demo.setup_environment(venv, tmp_path / "package", {})
    assert all("pip" not in command for command in commands)


def test_optional_instrument_dependencies_do_not_block_core_demo_check(tmp_path, monkeypatch, capsys):
    demo = load_launcher()
    monkeypatch.setattr(
        demo,
        "probe_environment",
        lambda *a: {"required_missing": [], "optional_missing": ["h5py>=3.10,<4"], "python": "3.10.11"},
    )
    runtime = tmp_path / "untouched"
    assert demo.main(["--python", sys.executable, "--check", "--runtime", str(runtime)]) == 0
    output = capsys.readouterr().out
    assert "optional_missing" in output
    assert "h5py>=3.10,<4" in output
    assert not runtime.exists()


def test_setup_reuses_complete_managed_environment_without_network(tmp_path, monkeypatch):
    demo = load_launcher()
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    python = demo.venv_python(tmp_path / ".demo-venv")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(
        demo,
        "probe_environment",
        lambda *a: {"required_missing": [], "optional_missing": [], "python": "3.10.11"},
    )
    monkeypatch.setattr(demo, "setup_environment", lambda *a: pytest.fail("complete environment reinstalled"))
    monkeypatch.setattr(demo, "prepare_runtime", lambda *a: None)
    monkeypatch.setattr(demo, "start_server", lambda *a: 0)
    assert demo.main(["--setup", "--runtime", str(tmp_path / "runtime")]) == 0


def test_running_server_wait_remains_interruptible(tmp_path, monkeypatch):
    demo = load_launcher()
    (tmp_path / "logs").mkdir()

    class Process:
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def wait(self, timeout=None):
            assert self.stopped, "must poll rather than block indefinitely before handling Ctrl+C"
            return 0

        def send_signal(self, value):
            self.stopped = True

        def kill(self):
            self.stopped = True

    class Healthy:
        status = 200

        def open(self, *args, **kwargs):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    process = Process()
    monkeypatch.setattr(demo.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(demo, "build_opener", lambda *a: Healthy())
    monkeypatch.setattr(demo, "seed_flows", lambda *a: {"imported": [], "preserved": []})
    monkeypatch.setattr(demo.time, "sleep", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    if os.name != "nt":
        process.pid = 12345
        monkeypatch.setattr(demo.os, "killpg", lambda *a: process.kill())
    assert demo.start_server(Path(sys.executable), tmp_path, 7880, 10) == 0
    assert process.stopped


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree shutdown contract")
def test_windows_shutdown_timeout_targets_only_own_process_tree(monkeypatch):
    demo = load_launcher()
    commands = []

    class Process:
        pid = 12345
        stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def send_signal(self, value):
            pass

        def wait(self, timeout):
            if not self.stopped:
                raise subprocess.TimeoutExpired("demo-child", timeout)
            return 0

        def kill(self):
            self.stopped = True

    process = Process()

    def run(command, **kwargs):
        commands.append((command, kwargs))
        process.stopped = True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(demo.subprocess, "run", run)
    demo.stop_server(process)
    assert commands[0][0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    assert not commands[0][1].get("shell", False)
    assert process.stopped


def test_inherited_pip_and_python_redirects_cannot_escape_install_target(tmp_path, monkeypatch):
    demo = load_launcher()
    for key in [
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_USER",
        "PIP_ROOT",
        "PIP_PYTHON",
        "PIP_CONFIG_FILE",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
    ]:
        monkeypatch.setenv(key, str(tmp_path / "external-shared"))
    env = demo.runtime_environment(tmp_path / "runtime")
    for key in [
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_USER",
        "PIP_ROOT",
        "PIP_PYTHON",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "VIRTUAL_ENV",
    ]:
        assert key not in env, key
    assert env["PIP_CONFIG_FILE"] == os.devnull


def test_malicious_global_user_and_site_pip_configs_are_disabled(tmp_path):
    demo = load_launcher()
    configuration = tmp_path / "pip.ini"
    configuration.write_text("[install]\ntarget = external-shared\nprefix = external-prefix\nuser = true\n")
    code = """
import json, sys
from pip._internal import configuration
from pip._internal.commands import create_command
configuration.get_configuration_files = lambda: {
    configuration.Kind('global'): [sys.argv[1]],
    configuration.Kind('user'): [sys.argv[1]],
    configuration.Kind('site'): [sys.argv[1]],
}
options, args = create_command('install').parse_args(['example-package'])
print(json.dumps({'target': options.target_dir,
                  'prefix': options.prefix_path, 'user': options.use_user_site}))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", "-B", "-c", code, str(configuration)],
        env=demo.runtime_environment(tmp_path / "runtime"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"target": None, "prefix": None, "user": None}


def test_isolated_dependency_probe_forces_utf8_for_chinese_editable_paths(monkeypatch):
    demo = load_launcher()
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"required_missing": [], "optional_missing": [], "python": "3.10.11"}),
        )

    monkeypatch.setattr(demo.subprocess, "run", run)
    assert demo.probe_environment(Path(sys.executable))["required_missing"] == []
    assert commands[0][1:5] == ["-I", "-X", "utf8", "-B"]

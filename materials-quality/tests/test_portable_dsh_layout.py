import importlib.util
from pathlib import Path

from materials_quality.agent import dsh_engine

ROOT = Path(__file__).resolve().parents[2]


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def test_portable_dsh_root_is_resolved_outside_runtime_data(tmp_path):
    runtime_root = tmp_path / ".demo-runtime"
    runtime_root.mkdir()
    node = runtime_root.parent / "runtime" / "dsh" / "node" / "node.exe"
    bin_js = (
        runtime_root.parent / "runtime" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    )
    _touch(node)
    _touch(bin_js)
    settings = runtime_root / "agent.sqlite3"
    assert dsh_engine._bundled_node(runtime_root) == node
    assert dsh_engine._bundled_dsh_bin(runtime_root) == bin_js
    command = dsh_engine.resolve_command(settings)
    assert command is not None
    assert command.argv[0] == str(node)
    assert command.argv[1] == str(bin_js)


def test_runtime_data_dsh_root_still_wins(tmp_path):
    runtime_root = tmp_path / ".demo-runtime"
    _touch(runtime_root / "dsh" / "node" / "node.exe")
    _touch(runtime_root / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js")
    _touch(runtime_root.parent / "runtime" / "dsh" / "node" / "node.exe")
    _touch(
        runtime_root.parent / "runtime" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    )
    assert dsh_engine._bundled_node(runtime_root) == runtime_root / "dsh" / "node" / "node.exe"


def test_portable_build_includes_dsh_plugins():
    spec = importlib.util.spec_from_file_location("build_portable", ROOT / "scripts" / "build_portable.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "dsh-plugins" in module.INCLUDE_DIRS

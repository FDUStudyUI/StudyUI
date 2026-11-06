#!/usr/bin/env python3
"""Start the local StudyUI research-agent harness; --check is strictly read-only."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages" / "materials-quality"
FLOW_FILES = ("spectra.json", "mechanics.json", "contrast.json")
PAPER_FLOW_FILES = ("03-dna-origami-nanogaps.json",)


def venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def requirements(package: Path, *, optional: bool = False) -> list[str]:
    """Read the project's dependency arrays without importing project dependencies."""
    text = (package / "pyproject.toml").read_text(encoding="utf-8")
    result = [] if optional else ["langflow-base==1.13.0", "lfx==1.13.0"]
    keys = ("instruments",) if optional else ("dependencies", "langflow", "science")
    for key in keys:
        match = re.search(
            r"^" + key + r"\s*=\s*(\[.*?\])", text, re.MULTILINE | re.DOTALL
        )
        if match is None:
            raise ValueError(
                f"Missing dependency array {key} in {package / 'pyproject.toml'}"
            )
        result.extend(ast.literal_eval(match.group(1)))
    return list(dict.fromkeys(result))


def probe_environment(python: Path, package: Path = PACKAGE) -> dict:
    # Metadata inspection avoids importing Langflow, creating config, or initializing its database.
    code = r"""
import importlib.metadata as metadata
import json, platform, sys
report = {"required_missing": [], "optional_missing": [], "python": platform.python_version()}
try:
    from packaging.requirements import Requirement
except ImportError:
    report["required_missing"] = ["packaging (dependency validation unavailable)"]
    print(json.dumps(report))
    sys.exit(0)
for group, values in json.loads(sys.stdin.read()).items():
    for value in values:
        requirement = Requirement(value)
        try:
            installed = metadata.version(requirement.name)
            if requirement.specifier and installed not in requirement.specifier:
                report[group].append(value + " (installed " + installed + ")")
        except metadata.PackageNotFoundError:
            report[group].append(value)
print(json.dumps(report))
"""
    result = subprocess.run(
        [str(python), "-I", "-X", "utf8", "-B", "-c", code],
        input=json.dumps(
            {
                "required_missing": requirements(package),
                "optional_missing": requirements(package, optional=True),
            }
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=True,
    )
    report = json.loads(result.stdout)
    if not report["python"].startswith("3.10."):
        report["required_missing"].insert(
            0, "Python 3.10 required (found " + report["python"] + ")"
        )
    return report


def runtime_environment(runtime: Path) -> dict[str, str]:
    # Discard inherited Langflow settings so another workspace's DB/.env cannot leak into this demo.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("LANGFLOW_", "PIP_"))
        and key.upper() not in {"PYTHONHOME", "PYTHONUSERBASE", "VIRTUAL_ENV"}
    }
    paths = {
        "LANGFLOW_CONFIG_DIR": "config",
        "LANGFLOW_COMPONENTS_PATH": "components",
        "LANGFLOW_LOG_FILE": "logs/langflow.log",
        "PIP_CACHE_DIR": "pip-cache",
        "TEMP": "tmp",
        "TMP": "tmp",
        "TMPDIR": "tmp",
        "XDG_CACHE_HOME": "cache",
        "HF_HOME": "cache/huggingface",
        "MPLCONFIGDIR": "cache/matplotlib",
        "NUMBA_CACHE_DIR": "cache/numba",
        "TORCH_HOME": "cache/torch",
    }
    env.update({key: str(runtime / value) for key, value in paths.items()})
    env.update(
        {
            "LANGFLOW_HOST": "127.0.0.1",
            "LANGFLOW_OPEN_BROWSER": "false",
            "LANGFLOW_DO_NOT_TRACK": "true",
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(PACKAGE / "src"),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PYTHONNOUSERSITE": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MPLBACKEND": "Agg",
            "LITELLM_LOCAL_MODEL_COST_MAP": "True",
            "DO_NOT_TRACK": "true",
        }
    )
    return env


def setup_environment(venv: Path, package: Path, env: dict[str, str]) -> None:
    """Only this dedicated venv is ever an installation target."""
    if venv.is_symlink() or venv.resolve() != venv.absolute():
        raise ValueError(
            "Refusing a redirected .demo-venv; use a real project-local directory"
        )
    python = venv_python(venv)
    if not python.is_file():
        if sys.version_info[:2] != (3, 10):
            raise ValueError("Run setup using Python 3.10 (Windows: py -3.10)")
        subprocess.run(
            [sys.executable, "-B", "-m", "venv", str(venv)], env=env, check=True
        )
    config = venv / "pyvenv.cfg"
    if not config.is_file():
        raise ValueError(
            "Refusing an existing interpreter without .demo-venv/pyvenv.cfg"
        )
    if re.search(
        r"include-system-site-packages\s*=\s*true", config.read_text(), re.IGNORECASE
    ):
        raise ValueError("Refusing a .demo-venv that includes shared system packages")
    identity = subprocess.run(
        [
            str(python),
            "-I",
            "-X",
            "utf8",
            "-B",
            "-c",
            "import sys,json; print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix}))",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    prefixes = json.loads(identity.stdout)
    if (
        Path(prefixes["prefix"]).resolve() != venv.resolve()
        or prefixes["prefix"] == prefixes["base_prefix"]
    ):
        raise ValueError(
            "Refusing installation: interpreter prefix is not the dedicated .demo-venv"
        )
    subprocess.run(
        [
            str(python),
            "-I",
            "-X",
            "utf8",
            "-B",
            "-m",
            "pip",
            "install",
            "--no-user",
            "--prefix",
            str(venv),
            "--cache-dir",
            env["PIP_CACHE_DIR"],
            "-e",
            str(package) + "[langflow,science,instruments]",
            "langflow-base==1.13.0",
        ],
        env=env,
        check=True,
    )


def port_available(port: int) -> bool:
    with socket.socket() as candidate:
        try:
            candidate.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _flow_paths(flow_dir: Path, extra_flow_dir: Path | None = None) -> list[Path]:
    paths = [flow_dir / filename for filename in FLOW_FILES]
    if extra_flow_dir is not None:
        paths.extend(extra_flow_dir / filename for filename in PAPER_FLOW_FILES)
    return paths


def import_instructions(flow_dir: Path, extra_flow_dir: Path | None = None) -> None:
    print(
        "Manual import: Langflow -> New flow / Upload flow; choose these JSON files:",
        flush=True,
    )
    for path in _flow_paths(flow_dir, extra_flow_dir):
        print("  " + str(path), flush=True)


def prepare_runtime(runtime: Path) -> None:
    for subdirectory in ("config", "components", "logs", "tmp", "pip-cache", "cache"):
        (runtime / subdirectory).mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        PACKAGE / "components",
        runtime / "components",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def initialize_file_workflows(root: Path) -> None:
    """Seed a new installation once; never replace an existing research workflow."""
    directory = root / "workflows"
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("*.json")):
        return
    project_id = str(uuid.uuid4())
    for source in _flow_paths(PACKAGE / "examples" / "skill_flows", PACKAGE / "examples" / "research_flows"):
        if not source.is_file():
            continue
        flow = json.loads(source.read_text(encoding="utf-8"))
        flow.update(id=str(uuid.uuid4()), folder_id=project_id)
        flow.pop("user_id", None)
        with (directory / (flow["id"] + ".json")).open("x", encoding="utf-8") as target:
            json.dump(flow, target, ensure_ascii=False, indent=2)
            target.write("\n")


def apply_studyui_langflow_theme(python: Path, runtime: Path | None = None) -> None:
    """Rebuild the bundled Langflow UI entry points for StudyUI's workflow-only shell."""
    result = subprocess.run(
        [
            str(python),
            "-c",
            "from importlib.metadata import distribution; print(distribution('langflow-base').locate_file('langflow/frontend'))",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    vendor_frontend = Path(result.stdout.strip())
    frontend = (runtime or ROOT / ".demo-runtime") / "workbench-ui"
    shutil.copytree(vendor_frontend, frontend, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("studyui-*"))
    index_path = frontend / "index.html"
    if not index_path.is_file():
        raise RuntimeError(f"Langflow frontend entry was not found: {index_path}")
    index = index_path.read_text(encoding="utf-8").replace("<title>Langflow</title>", "<title>StudyUI Workbench</title>")
    if '<base href="/canvas/"' not in index:
        index, base_count = re.subn(
            r'<base href="/"\s*/?>', '<base href="/canvas/" />', index, count=1
        )
        if base_count != 1:
            raise RuntimeError(f"Unexpected workbench base URL in {index_path}")
    index = re.sub(
        r'\s*<script id="studyui-clean-chrome">.*?</script>\s*',
        "\n",
        index,
        count=1,
        flags=re.DOTALL,
    )
    if "studyui-theme-default" not in index:
        theme_bootstrap = """<script id="studyui-theme-default">
      try {
        if (!localStorage.getItem("themePreference")) {
          localStorage.setItem("themePreference", "light");
          localStorage.setItem("isDark", "false");
        }
      } catch (_) {}
    </script>
    <link rel="stylesheet" href="./studyui-theme.css" />"""
        if "</head>" not in index:
            raise RuntimeError(f"Unexpected Langflow frontend entry format: {index_path}")
        index = index.replace("</head>", theme_bootstrap + "\n  </head>", 1)
    if 'href="./studyui-theme.css"' not in index:
        if "</head>" not in index:
            raise RuntimeError(f"Unexpected Langflow frontend entry format: {index_path}")
        index = index.replace(
            "</head>", '    <link rel="stylesheet" href="./studyui-theme.css" />\n  </head>', 1
        )

    bundle_match = re.search(r'<script[^>]+src="([^"]+\.js(?:\?[^"]*)?)"', index)
    if bundle_match is None:
        raise RuntimeError(f"Langflow frontend bundle was not found in {index_path}")
    bundle_url = bundle_match.group(1)
    assets_root = (frontend / "assets").resolve()
    bundle_name = bundle_url.split("?", 1)[0].rsplit("/", 1)[-1]
    bundle_path = (assets_root / bundle_name).resolve()
    try:
        bundle_path.relative_to(assets_root)
    except ValueError as exc:
        raise RuntimeError("Langflow frontend bundle path escaped its package") from exc
    if not bundle_path.is_file():
        raise RuntimeError(f"Langflow frontend bundle was not found: {bundle_path}")

    if "studyui-agent-run-bridge" not in index:
        bridge = r'''<script id="studyui-agent-run-bridge">
      (() => {
        const pending = new Set();
        const panel = () => {
          let root = document.getElementById("studyui-agent-run-status");
          if (!root) {
            root = document.createElement("aside");
            root.id = "studyui-agent-run-status";
            root.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483647;max-width:min(520px,calc(100vw - 36px));max-height:45vh;overflow:auto;padding:14px 16px;border:1px solid #d8d1c5;border-radius:12px;background:#fffdf8;color:#263246;box-shadow:0 8px 28px #1f293322;font:13px/1.55 system-ui,sans-serif;white-space:pre-wrap";
            document.body.append(root);
          }
          return root;
        };
        const show = (text, meta) => {
          const root = panel();
          root.replaceChildren();
          const message = document.createElement("div");
          message.textContent = text;
          root.append(message);
          if (meta && meta.session_id) {
            const link = document.createElement("a");
            link.href = "/?session_id=" + encodeURIComponent(meta.session_id);
            link.textContent = "在 StudyUI 中查看完整报告与附件";
            link.style.cssText = "display:inline-block;margin-top:8px;color:#24466f;font-weight:600";
            root.append(link);
          }
        };
        const bodyWithSession = (body) => {
          if (typeof body !== "string") return body;
          try {
            const value = JSON.parse(body);
            const session = new URL(location.href).searchParams.get("studyui_session_id");
            if (session) value.studyui_session_id = session;
            return JSON.stringify(value);
          } catch (_) { return body; }
        };
        const complete = (value) => {
          const meta = value && value.studyui_run;
          if (!meta || !meta.session_id) return;
          const key = meta.session_id + ":" + meta.flow_id;
          if (pending.has(key)) return;
          pending.add(key);
          const summary = meta.status === "completed" ? "StudyUI Agent 已完成工作流运行。" : "StudyUI Agent 已处理本次运行请求。";
          show(summary + "\n\n" + (meta.message || "请打开研究会话查看 Agent 结果。"), meta);
          if (window.parent !== window) {
            window.parent.postMessage({type:"studyui-agent-run-complete",session_id:meta.session_id,flow_id:meta.flow_id},location.origin);
          }
        };
        const OriginalXHR = window.XMLHttpRequest;
        function StudyUIXHR() {
          const xhr = new OriginalXHR();
          let runRequest = false;
          const open = xhr.open;
          xhr.open = function(method, url, ...rest) {
            try { runRequest = String(method).toUpperCase() === "POST" && /\/api\/v1\/run\/[^/?]+/.test(new URL(url,location.href).pathname); } catch (_) { runRequest = false; }
            return open.call(xhr, method, url, ...rest);
          };
          const send = xhr.send;
          xhr.send = function(body) {
            if (runRequest) {
              show("StudyUI 主 Agent 正在检查流程、编排子代理并整理运行结果……");
              xhr.addEventListener("load", () => {
                try {
                  const value = typeof xhr.response === "string" ? JSON.parse(xhr.response) : (xhr.response || JSON.parse(xhr.responseText));
                  complete(value);
                } catch (_) { show("StudyUI Agent 返回结果无法读取，请查看当前会话或服务日志。"); }
              }, {once:true});
              body = bodyWithSession(body);
            }
            return send.call(xhr, body);
          };
          return xhr;
        }
        StudyUIXHR.prototype = OriginalXHR.prototype;
        Object.setPrototypeOf(StudyUIXHR, OriginalXHR);
        window.XMLHttpRequest = StudyUIXHR;

        if (window.fetch) {
          const originalFetch = window.fetch.bind(window);
          window.fetch = async (input, init = {}) => {
            let runRequest = false;
            try {
              const url = new URL(typeof input === "string" ? input : input.url, location.href);
              runRequest = String(init.method || (input && input.method) || "GET").toUpperCase() === "POST" && /\/api\/v1\/run\/[^/?]+/.test(url.pathname);
            } catch (_) {}
            if (!runRequest) return originalFetch(input, init);
            show("StudyUI 主 Agent 正在检查流程、编排子代理并整理运行结果……");
            init = {...init, body:bodyWithSession(init.body)};
            const response = await originalFetch(input, init);
            try { complete(await response.clone().json()); } catch (_) {}
            return response;
          };
        }
        const syncStudyUIChrome = () => {
          if (document.title.includes("Langflow")) document.title = document.title.replaceAll("Langflow", "StudyUI");
          if (!document.body) return;
          let bar = document.getElementById("studyui-canvas-bar");
          if (!bar) {
            bar = document.createElement("div");
            bar.id = "studyui-canvas-bar";
            bar.style.cssText = "position:fixed;bottom:24px;right:24px;z-index:99999;display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.96);backdrop-filter:blur(10px);border:1px solid #dcd7cc;box-shadow:0 8px 30px rgba(25,35,50,0.18);border-radius:10px;padding:6px 10px;";
            
            const runBtn = document.createElement("button");
            runBtn.id = "studyui-run-workflow";
            runBtn.textContent = "▶ 运行工作流";
            runBtn.style.cssText = "border:0;border-radius:7px;padding:7px 14px;background:#294b77;color:white;font:600 12.5px system-ui,sans-serif;cursor:pointer;display:inline-flex;align-items:center;gap:6px;";

            const cancelBtn = document.createElement("button");
            cancelBtn.id = "studyui-cancel-workflow";
            cancelBtn.textContent = "⏹ 取消运行";
            cancelBtn.style.cssText = "display:none;border:1px solid #e2aaaa;border-radius:7px;padding:6px 12px;background:#fff5f5;color:#c53030;font:600 12px system-ui,sans-serif;cursor:pointer;";

            const timerSpan = document.createElement("span");
            timerSpan.id = "studyui-run-timer";
            timerSpan.style.cssText = "display:none;font-size:11.5px;color:#556;font-family:ui-monospace,monospace;";

            let currentController = null;
            let runInterval = null;

            cancelBtn.onclick = () => {
              if (currentController) {
                currentController.abort();
                currentController = null;
              }
              clearInterval(runInterval);
              runBtn.disabled = false;
              runBtn.textContent = "▶ 运行工作流";
              cancelBtn.style.display = "none";
              timerSpan.style.display = "none";
              show("工作流运行已手动取消。");
            };

            runBtn.onclick = async () => {
              const match = location.pathname.match(/\/canvas\/flow\/([^/]+)/);
              if (!match || runBtn.disabled) return;
              runBtn.disabled = true;
              runBtn.textContent = "Agent 正在运行…";
              cancelBtn.style.display = "inline-flex";
              timerSpan.style.display = "inline";
              timerSpan.textContent = "⏱ 0.0s";
              const startT = Date.now();
              clearInterval(runInterval);
              runInterval = setInterval(() => {
                timerSpan.textContent = "⏱ " + ((Date.now() - startT) / 1000).toFixed(1) + "s";
              }, 200);

              currentController = new AbortController();
              try {
                show("StudyUI 主 Agent 正在检查流程、编排子代理并整理运行结果……");
                const response = await fetch('/canvas/api/v1/run/' + encodeURIComponent(match[1]), {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({input_value: '', tweaks: {}}),
                  signal: currentController.signal
                });
                const value = await response.json();
                if (!response.ok) throw new Error(value.detail || value.error || '运行失败');
                complete(value);
              } catch (error) {
                if (error.name === 'AbortError') {
                  show("工作流运行已中止。");
                } else {
                  show('工作流运行失败：' + String(error.message || error));
                }
              } finally {
                clearInterval(runInterval);
                currentController = null;
                runBtn.disabled = false;
                runBtn.textContent = "▶ 运行工作流";
                cancelBtn.style.display = "none";
                timerSpan.style.display = "none";
              }
            };

            bar.append(runBtn, cancelBtn, timerSpan);
            document.body.append(bar);
          }
          bar.hidden = !/\/canvas\/flow\/[^/]+/.test(location.pathname);
        };
        for (const name of ['pushState','replaceState']) {
          const original = history[name];
          history[name] = function(...args) { const result = original.apply(this,args); queueMicrotask(syncStudyUIChrome); return result; };
        }
        addEventListener('popstate', syncStudyUIChrome);
        addEventListener('DOMContentLoaded', () => {
          syncStudyUIChrome();
          const title = document.querySelector('title');
          if (title) new MutationObserver(syncStudyUIChrome).observe(title,{childList:true,subtree:true,characterData:true});
        });
      })();
    </script>'''
        bundle_tag = bundle_match.group(0)
        if bundle_tag not in index:
            raise RuntimeError("StudyUI could not locate the canvas entry script for its Agent run bridge")
        index = index.replace(bundle_tag, bridge + "\n" + bundle_tag, 1)

    backup_root = (runtime or ROOT / ".demo-runtime") / "backup"
    backup_root.mkdir(parents=True, exist_ok=True)
    original_bundle = backup_root / (bundle_path.name + ".studyui-original")
    if not original_bundle.exists():
        shutil.copy2(bundle_path, original_bundle)
    bundle = original_bundle.read_text(encoding="utf-8")

    def replace_region(source: str, start: str, end: str, replacement: str, label: str) -> str:
        if source.count(start) != 1 or source.count(end) != 1:
            raise RuntimeError(f"Langflow UI changed; cannot remove its {label} component safely")
        start_at = source.index(start)
        end_at = source.index(end, start_at + len(start))
        return source[:start_at] + replacement + source[end_at:]

    def replace_component(source: str, old: str, new: str, label: str) -> str:
        if source.count(old) != 1:
            raise RuntimeError(f"Langflow UI changed; cannot remove its {label} component safely")
        return source.replace(old, new, 1)

    def save_bundle() -> None:
        cache_tag = hashlib.sha256(bundle.encode("utf-8")).hexdigest()[:12]
        versioned_assets = assets_root / f"studyui-{cache_tag}"
        versioned_assets.mkdir(parents=True, exist_ok=True)
        try:
            versioned_assets.resolve().relative_to(assets_root)
        except ValueError as exc:
            raise RuntimeError("StudyUI frontend asset path escaped the Langflow package") from exc
        for source in assets_root.iterdir():
            if not source.is_file() or source.name == bundle_name:
                continue
            target = versioned_assets / source.name
            if target.exists():
                continue
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        (versioned_assets / bundle_name).write_text(bundle, encoding="utf-8")

        # Retire generated copies from previous builds, including old login assets.
        for previous in assets_root.glob("studyui-*"):
            if previous != versioned_assets and previous.is_dir() and previous.resolve().parent == assets_root:
                shutil.rmtree(previous)

        # Every code-split icon imports the entry module by its relative filename.
        # A query-only cache tag makes the browser load a second React app at the
        # untagged URL, so give the whole asset graph one versioned directory.
        versioned_url = f"./assets/{versioned_assets.name}/{bundle_name}"
        script_pattern = re.compile(
            rf'(<script[^>]+src=")[^"]*{re.escape(bundle_name)}(?:\?[^"]*)?"'
        )
        updated_index, replacements = script_pattern.subn(
            lambda match: match.group(1) + versioned_url + '"',
            index,
            count=1,
        )
        if replacements != 1:
            raise RuntimeError("Langflow frontend entry changed while saving the StudyUI bundle")
        index_path.write_text(updated_index, encoding="utf-8")

    # Remove account/profile renderers and their components from the compiled bundle.
    bundle = replace_region(
        bundle,
        ",wFi=()=>{",
        "function MFi(",
        ";",
        "account/profile menu",
    )
    bundle = replace_region(
        bundle,
        "const cFi=({children:e})=>",
        "({href:e",
        "const _Le=",
        "account menu primitives",
    )
    bundle = replace_region(
        bundle,
        ",hFi=()=>{",
        ";function gFi(",
        ";const pFi=e=>null",
        "community menu links",
    )
    bundle = replace_region(
        bundle,
        "const Xki=",
        "Zki=({children:e})=>",
        "const ",
        "interactive authentication guard",
    )
    bundle = replace_component(
        bundle,
        'b.jsx(Xki,{children:b.jsx(n$,{})})',
        'b.jsx(n$,{})',
        "interactive authentication route guard",
    )
    bundle = replace_component(
        bundle,
        ',b.jsx(pu,{path:"login",element:b.jsx(zdt,{children:b.jsx(jCo,{})})}),'
        'b.jsx(pu,{path:"signup",element:b.jsx(zdt,{children:b.jsx(kDo,{})})}),'
        'b.jsx(pu,{path:"login/admin",element:b.jsx(zdt,{children:b.jsx(RDo,{})})}),',
        ",",
        "login and sign-up routes",
    )
    bundle = replace_component(
        bundle,
        'const RDo=N.lazy(()=>te(()=>import("./index-CxoBrV6N.js"),[],import.meta.url)),TDo=',
        "const TDo=",
        "admin login module",
    )
    bundle = replace_component(
        bundle,
        ',kDo=N.lazy(()=>te(()=>import("./index-_FvlbSMC.js"),[],import.meta.url))',
        "",
        "sign-up module",
    )
    bundle = replace_region(bundle, "function jCo(){", "const qor=", "", "sign-in form")
    bundle = replace_region(
        bundle,
        ",AFi=()=>{",
        "function xFi(){return b.jsx(b.Fragment,{})}",
        ";",
        "GitHub and Discord header links",
    )
    bundle = replace_region(
        bundle,
        "function hqi(){",
        "function fqi(){",
        'function hqi(){const n=Vv(),{isFetched:t}=MKn();Lwe();h3t({get_all:!0,header_flows:!0},{enabled:t});return b.jsx("header",{className:"z-10 flex h-[48px] w-full items-center border-b pl-2.5 dark:bg-background","data-testid":"app-header",children:b.jsx(gt,{unstyled:!0,onClick:()=>n("/"),className:"mr-1 flex h-8 w-8 items-center justify-center rounded-md bg-primary font-semibold text-white","data-testid":"icon-ChevronLeft","aria-label":"StudyUI 首页",children:"S"})})}',
        "Langflow header",
    )
    bundle = replace_component(
        bundle,
        ',b.jsx(wqi,{})',
        '',
        "knowledge storage upgrade panel",
    )

    bundle = replace_region(
        bundle,
        'b.jsxs(UHn,{open:V,modal:!1,children:[',
        'b.jsx(kSo,{selectedNode:t})',
        '',
        "Langflow Assistant canvas control",
    )
    bundle = replace_region(
        bundle, "function kgo(){", "function Lnr(",
        'function kgo(){const e=SC(z=>z.isOpen),t=SC(z=>z.close);N.useEffect(()=>{e&&t()},[e,t]);return null}',
        "legacy assistant welcome overlay",
    )

    # The local workbench has one workspace and no user or token lifecycle.
    bundle = replace_region(bundle, "function Kei({children:e}){", "const Xei=", 'function Kei({children:e}){return b.jsx(OI.Provider,{value:Gei,children:e})}', "account provider")
    bundle = replace_region(bundle, "function g4i({children:e}){", "function Jxn(", 'function g4i({children:e}){return e}', "session guard")
    bundle = replace_region(bundle, "function qqi(){", "const Wqi=", 'function qqi(){const{isFetched:e}=Nqi(),{isFetched:t}=Dqi();MKn();T4({mirrorToStore:!0});return e&&t?b.jsx(n$,{}):b.jsx(kxt,{})}', "account initialization")
    bundle = replace_region(bundle, "function $ae({resourceType:", "class XFe ", 'function $ae({children:e}){return e}', "account permissions provider")
    bundle = replace_component(bundle, 'RNn(Bwt).then(()=>{', 'Aa.setState({isAuthenticated:!0,isAdmin:!0,autoLogin:!0});RNn(Bwt).then(()=>{', "workspace initialization")

    # This embedded canvas only exposes components; the old assistant,
    # memories, tracing and unsupported server-management panels are removed.
    bundle = replace_region(
        bundle,
        'const ATt=[{id:"components"',
        '],PTn=new Set(',
        'const ATt=[{id:"components",icon:"component",label:"sidebar.nav.components",tooltip:"sidebar.nav.components"}',
        "legacy canvas navigation",
    )
    bundle = replace_component(bundle, 'P=["flows","mcp",...D?["deployments"]:[]]', 'P=["flows"]', "unsupported project tabs")

    # Remove onboarding and non-workflow navigation, keeping project creation.
    bundle = replace_region(bundle, "const R_o=", "const k_o=", "", "onboarding card")
    bundle = replace_region(
        bundle,
        "const k_o=",
        "N_o=({onClick:e,disabled:t})=>",
        'const k_o=({onClick:e,disabled:t,loading:n})=>b.jsx(gt,{variant:"ghost",size:"icon",onClick:e,disabled:t,loading:n,"aria-label":"New project","data-testid":"add-project-button",children:b.jsx(Pe,{name:"Plus",className:"h-4 w-4"})}),',
        "project creation control",
    )
    bundle = replace_region(
        bundle,
        "D_o=({handleUploadFlowsToFolder:",
        ",L_o=({handleEditFolderName:",
        'D_o=({handleUploadFlowsToFolder:e,isUpdatingFolder:t,isPending:n,addNewFolder:i,containerClassName:s,titleClassName:a})=>{const{t:l}=ot();return b.jsxs("div",{className:He("flex shrink-0 items-center justify-between gap-2 pt-2",s),children:[b.jsx(MZ,{className:"lg:hidden",children:b.jsx(Pe,{name:"PanelLeftClose",className:"h-4 w-4"})}),b.jsx("div",{id:"project-sidebar-title",className:He("flex-1 text-sm font-medium",a),children:l("sidebar.projects")}),b.jsxs("div",{className:"flex items-center gap-1",children:[b.jsx(N_o,{onClick:e,disabled:t}),b.jsx(k_o,{onClick:i,disabled:t,loading:n})]})]})}',
        "project sidebar",
    )
    knowledge_link = 'b.jsxs(e3,{onClick:pn,size:"md",className:He("text-sm",u.footerItemClassName),children:[b.jsx(Pe,{name:"Library",className:"h-4 w-4"}),y("sidebar.knowledge")]})'
    my_files_link = 'b.jsxs(e3,{onClick:Zt,size:"md",className:He("text-sm",u.footerItemClassName),children:[b.jsx(Pe,{name:"File",className:"h-4 w-4"}),y("sidebar.myFiles")]})'
    bundle = replace_component(
        bundle,
        ',b.jsxs(b.Fragment,{children:[' + knowledge_link + "," + my_files_link + "]})",
        "",
        "Knowledge and My Files navigation",
    )
    bundle = replace_region(
        bundle,
        ',b.jsxs(pu,{path:"assets",children:[',
        ',b.jsx(pu,{path:"flows/"',
        "",
        "Knowledge and My Files routes",
    )
    bundle = replace_region(
        bundle,
        "$_o=({setOpenModal:e})=>",
        ";function V_o(",
        '$_o=()=>b.jsx("div",{className:"flex h-full w-full items-center justify-center text-sm text-muted-foreground",children:"此项目还没有工作流。"}),H_o=({setOpenModal:e})=>b.jsx($_o,{setOpenModal:e})',
        "empty-project onboarding",
    )

    # Remove the unused sign-in chunks before creating the versioned asset set.
    for chunk_name in ("index-CxoBrV6N.js", "index-_FvlbSMC.js"):
        chunk_path = assets_root / chunk_name
        if not chunk_path.is_file() or f'"./{chunk_name}"' in bundle:
            continue
        removed_copy = backup_root / (chunk_name + ".studyui-removed")
        if not removed_copy.exists():
            shutil.copy2(chunk_path, removed_copy)
        chunk_path.unlink()

    # Keep Langflow's package files pristine; StudyUI serves its own built asset tree.
    bundle_path.write_text(bundle, encoding="utf-8")
    save_bundle()
    (frontend / "studyui-theme.css").write_text(
        "#body{--accent-amber:217 48% 34%!important;"
        "--accent-amber-foreground:217 52% 38%!important}\n"
        "#body:not(.dark){--background:42 33% 96%!important;"
        "--foreground:220 18% 18%!important;--card:42 45% 99%!important;"
        "--card-foreground:220 18% 18%!important;--popover:42 45% 99%!important;"
        "--popover-foreground:220 18% 18%!important;--muted:39 24% 92%!important;"
        "--muted-foreground:220 9% 45%!important;--border:38 20% 87%!important;"
        "--input:38 20% 87%!important;--canvas:42 30% 97%!important;"
        "--canvas-dot:220 10% 73%!important;--primary:217 48% 34%!important;"
        "--primary-foreground:0 0% 100%!important;--primary-hover:217 50% 28%!important;"
        "--ring:217 48% 34%!important}\n"
        "#body.dark{--primary:217 48% 34%!important;"
        "--primary-foreground:0 0% 100%!important;--primary-hover:217 50% 28%!important;"
        "--ring:217 48% 44%!important}\n",
        encoding="utf-8",
    )


def start_studyui_service(python: Path, runtime: Path, port: int, ready_timeout: float = 240):
    url = f"http://127.0.0.1:{port}"
    env = runtime_environment(runtime)
    env["STUDYUI_PORT"] = str(port)
    env["STUDYUI_DATABASE"] = str(runtime / "agent.sqlite3")
    command = [
        str(python),
        "-B",
        "-m",
        "materials_quality.agent.server",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--database",
        str(runtime / "agent.sqlite3"),
        "--workflows",
        str(ROOT / "workflows"),
        "--components",
        str(runtime / "components"),
        "--frontend",
        str(runtime / "workbench-ui"),
    ]
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with (runtime / "logs" / "studyui-server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=runtime,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            **options,
        )
    deadline = time.monotonic() + ready_timeout
    while process.poll() is None and time.monotonic() < deadline:
        try:
            with build_opener(ProxyHandler({})).open(url + "/api/health", timeout=3) as response:
                if response.status == 200:
                    return process
        except (URLError, OSError):
            pass
        time.sleep(0.25)
    stop_studyui_service(process)
    raise RuntimeError("StudyUI did not start on the shared port; read .demo-runtime/logs/studyui-server.log")


def stop_studyui_service(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def start_system(python: Path, runtime: Path, port: int, ready_timeout: float) -> int:
    url = f"http://127.0.0.1:{port}"
    log_path = runtime / "logs" / "studyui-server.log"
    print(
        f"Starting StudyUI: {url}\nWorkflow canvas: {url}/canvas/\n"
        f"Logs: {log_path}\nPress Ctrl+C here to stop this demo.",
        flush=True,
    )
    process = None
    try:
        process = start_studyui_service(python, runtime, port, ready_timeout)
        print(f"StudyUI and workflow canvas ready: {url}", flush=True)
        while process.poll() is None:
            time.sleep(0.5)
        if process.returncode:
            print("StudyUI stopped unexpectedly; check logs/studyui-server.log", flush=True)
        return process.returncode or 0
    except KeyboardInterrupt:
        print("Stopping this demo...", flush=True)
        return 0
    finally:
        if process is not None:
            stop_server(process)


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=15)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    if os.name == "nt":
        # A venv executable may launch the real interpreter as a descendant.
        # Restrict fallback termination to the process tree we just created.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            timeout=20,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def valid_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create/update ONLY this project's .demo-venv (network required)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Inspect prerequisites only; never create/install/start/import",
    )
    parser.add_argument(
        "--python",
        type=Path,
        help="Use an existing Python 3.10 environment read-only; incompatible with --setup",
    )
    parser.add_argument("--port", type=valid_port, default=7880, help="StudyUI main application port")
    parser.add_argument("--runtime", type=Path, default=ROOT / ".demo-runtime")
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=240,
        help="Startup deadline in seconds (default: 240)",
    )
    args = parser.parse_args(argv)
    runtime = args.runtime.expanduser().resolve()
    python = (
        args.python.expanduser().resolve()
        if args.python
        else venv_python(ROOT / ".demo-venv")
    )
    print(
        f"Python: {python}\nRuntime: {runtime}\nStudyUI URL: http://127.0.0.1:{args.port}",
        flush=True,
    )
    if args.setup and args.python and not args.check:
        print(
            "--setup cannot be combined with --python: external environments are never installation targets."
        )
        return 2
    if args.ready_timeout <= 0:
        print("--ready-timeout must be positive.")
        return 2
    try:
        if args.setup and not args.check:
            existing = probe_environment(python) if python.is_file() else None
            if (
                existing
                and not existing["required_missing"]
                and not existing["optional_missing"]
            ):
                print(
                    "Existing dedicated environment is complete; reusing it without network installation."
                )
            else:
                print(
                    "SETUP: installing the current package [langflow,science,instruments] "
                    "+ langflow-base==1.13.0"
                )
                print("Installation target: " + str(ROOT / ".demo-venv"), flush=True)
                prepare_runtime(runtime)
                setup_environment(
                    ROOT / ".demo-venv", PACKAGE, runtime_environment(runtime)
                )
        if not python.is_file():
            print(
                "Python environment missing. First run: start_demo.bat --setup (or ./start_demo.sh --setup)."
            )
            return 2
        report = probe_environment(python)
        print("Detected Python " + report["python"])
        print("required_missing: " + json.dumps(report["required_missing"]))
        print("optional_missing: " + json.dumps(report["optional_missing"]))
        if report["optional_missing"]:
            print(
                "Optional instrument-array support is incomplete; the three core demo flows remain available."
            )
        if report["required_missing"]:
            print(
                "Use --setup for the dedicated .demo-venv, or provide a complete Python 3.10 with --python."
            )
            return 2
        if not port_available(args.port):
            print(
                f"Port {args.port} is in use. Choose --port with a free port; "
                "no existing service will be reused."
            )
            return 2
        print("Prerequisites OK. Loopback port is available.")
        if args.check:
            print(
                "Read-only check complete; no runtime directories, dependencies, "
                "services or flows were changed."
            )
            return 0
        prepare_runtime(runtime)
        initialize_file_workflows(ROOT)
        apply_studyui_langflow_theme(python, runtime)
        return start_system(python, runtime, args.port, args.ready_timeout)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Demo launcher failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

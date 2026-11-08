from __future__ import annotations

import importlib.util
from pathlib import Path


def test_strip_langflow_branding(tmp_path):
    module_path = Path(__file__).resolve().parents[3] / "scripts" / "branding.py"
    spec = importlib.util.spec_from_file_location("studyui_branding", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    frontend = tmp_path / "frontend"
    assets = frontend / "assets"
    assets.mkdir(parents=True)
    (assets / "logo_dark-abc.png").write_bytes(b"old logo")
    (assets / "langflow_assistant-abc.svg").write_text("<svg>Langflow</svg>", encoding="utf-8")
    (assets / "index.js").write_text(
        'const a="logo_dark-abc.png", b="langflow_assistant-abc.svg";', encoding="utf-8"
    )
    (frontend / "index.html").write_text(
        '<html><head><link rel="icon" href="./favicon.ico" />'
        '<link rel="manifest" href="./manifest.json" /></head></html>',
        encoding="utf-8",
    )
    (frontend / "manifest.json").write_text('{"name":"Langflow"}', encoding="utf-8")
    (frontend / "favicon.ico").write_bytes(b"old icon")
    (frontend / "icons").mkdir()
    (frontend / "icons" / "32x32.png").write_bytes(b"old icon")

    module.strip_langflow_branding(frontend)

    assert not (frontend / "manifest.json").exists()
    assert not (frontend / "favicon.ico").exists()
    assert not (frontend / "icons").exists()
    assert (assets / "studyui_logo_dark.png").is_file()
    assert (assets / "studyui_assistant.svg").is_file()
    script = (assets / "index.js").read_text(encoding="utf-8")
    assert "studyui_logo_dark.png" in script
    assert "studyui_assistant.svg" in script
    html = (frontend / "index.html").read_text(encoding="utf-8")
    assert "favicon.ico" not in html
    assert "manifest.json" not in html
    assert 'rel="icon"' in html
    assert "data:image/svg+xml" in html

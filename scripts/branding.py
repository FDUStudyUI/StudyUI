"""Remove Langflow brand assets from the bundled workflow canvas."""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path
from urllib.parse import quote

# A transparent pixel is enough for image slots that are no longer rendered.
_BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_STUDYUI_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="#29476f"/>'
    '<text x="32" y="44" text-anchor="middle" font-family="Georgia,serif" '
    'font-size="38" font-weight="700" fill="#fff">S</text></svg>'
)
_ASSET_REPLACEMENTS = (
    ("logo_dark-*.png", "studyui_logo_dark.png", _BLANK_PNG),
    ("logo_light-*.png", "studyui_logo_light.png", _BLANK_PNG),
    ("MCPLangflow-*.png", "studyui_mcp.png", _BLANK_PNG),
    ("langflow_assistant-*.svg", "studyui_assistant.svg", _STUDYUI_SVG.encode("utf-8")),
    (
        "langflow_assistant_idle-*.svg",
        "studyui_assistant_idle.svg",
        _STUDYUI_SVG.encode("utf-8"),
    ),
)


def _replace_references(frontend: Path, replacements: dict[str, str]) -> None:
    if not replacements:
        return
    for path in frontend.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {
            ".js",
            ".css",
            ".html",
            ".json",
            ".svg",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        updated = text
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def _strip_index_branding(frontend: Path) -> None:
    index_path = frontend / "index.html"
    if not index_path.is_file():
        return
    index = index_path.read_text(encoding="utf-8")
    index = re.sub(
        r'<link\b[^>]*\brel=["\'](?:icon|manifest|apple-touch-icon)["\'][^>]*>',
        "",
        index,
        flags=re.I,
    )
    favicon = f'<link rel="icon" href="data:image/svg+xml,{quote(_STUDYUI_SVG)}" />'
    if 'rel="icon"' not in index:
        index = index.replace("</head>", f"    {favicon}\n  </head>", 1)
    index_path.write_text(index, encoding="utf-8")


def strip_langflow_branding(frontend: str | Path) -> None:
    """Rename branded assets, remove icon/manifest files, and install StudyUI marks."""
    frontend = Path(frontend)
    assets = frontend / "assets"
    replacements: dict[str, str] = {}
    if assets.is_dir():
        for pattern, replacement, payload in _ASSET_REPLACEMENTS:
            for old in assets.rglob(pattern):
                replacements[old.name] = replacement
                old.unlink(missing_ok=True)
                old.with_name(replacement).write_bytes(payload)
            (assets / replacement).write_bytes(payload)
    _replace_references(frontend, replacements)
    for path in (frontend / "favicon.ico", frontend / "manifest.json"):
        path.unlink(missing_ok=True)
    shutil.rmtree(frontend / "icons", ignore_errors=True)
    _strip_index_branding(frontend)

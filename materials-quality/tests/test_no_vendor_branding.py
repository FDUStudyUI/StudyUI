"""Guard: product sources and docs must not carry vendor branding.

Third-party package names, runtime env vars and CLI invocations required for
compatibility are allow-listed; legal attribution lives in THIRD_PARTY_NOTICES.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
TARGETS = [
    ROOT / "src",
    ROOT / "components",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs",
    ROOT / "README.md",
    ROOT / "docs",
]
ALLOWED_SUBSTRINGS = (
    "langflow-base",
    "langflow-sdk",
    "LANGFLOW_",
    "python -m langflow",
    "langflow/frontend",
    "langflow_assistant",
    "MCPLangflow",
)


def _files():
    for target in TARGETS:
        if target.is_file():
            yield target
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".yml", ".toml", ".txt"}:
                    yield path


def test_product_sources_have_no_vendor_branding():
    violations = []
    for path in _files():
        if "THIRD_PARTY_NOTICES" in path.name:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            lowered = line.lower()
            if "langflow" in lowered and not any(item.lower() in lowered for item in ALLOWED_SUBSTRINGS):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:120]}")
    assert not violations, "Vendor branding found:\n" + "\n".join(violations)

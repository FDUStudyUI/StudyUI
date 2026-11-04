"""Read-only, bounded skill discovery. Instructions never grant code execution."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).with_name("resources")
SKILLS = {
    "spectra": ("studyui-spectrum-analysis", "批量光谱分析"),
    "mechanics": ("studyui-mechanics-analysis", "材料力学分析"),
    "contrast": ("studyui-statistics-and-figures", "组间研究与绘图"),
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    ).hexdigest()


def inspect_skill(path):
    """Preview a local candidate without importing scripts or granting execution."""
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("skill must be a directory, not a symlink / 符号链接")
    root = root.resolve()
    files, size = {}, 0
    for entry in root.rglob("*"):
        if entry.is_symlink():
            raise ValueError("skill symlink / 符号链接 is not allowed")
        if not entry.is_file():
            continue
        if entry.name == "studyui-skill.json":
            continue
        if not entry.resolve().is_relative_to(root):
            raise ValueError("skill resource escapes its directory")
        size += entry.stat().st_size
        if size > 2_000_000 or len(files) >= 128:
            raise ValueError("skill exceeds 128 files or 2 MB preview limit")
        files[entry.relative_to(root).as_posix()] = hashlib.sha256(entry.read_bytes()).hexdigest()
    entrypoint = root / "SKILL.md"
    if "SKILL.md" not in files:
        raise ValueError("SKILL.md is required")
    text = entrypoint.read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise ValueError("SKILL.md requires YAML frontmatter")
    fields = dict(re.findall(r"^([a-z-]+):[ \t]*(.+)$", match[1], re.M))
    name, description = fields.get("name", ""), fields.get("description", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise ValueError("invalid skill name")
    if not description.strip() or len(description) > 1024:
        raise ValueError("skill description must contain 1–1024 characters")
    version = re.search(r"^  version: (\S+)$", match[1], re.M)
    return {
        "name": name,
        "description": description,
        "instructions": text,
        "resources": files,
        "sha256": digest(files),
        "executable": False,
        "review_required": True,
        "version": version[1] if version else "unversioned",
    }


def load_skill(task):
    if task not in SKILLS:
        raise ValueError("unknown registered research task")
    name, title = SKILLS[task]
    result = inspect_skill(ROOT / name)
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    result.update(task=task, title=title, sources=sources, sha256=digest([result["sha256"], sources]))
    return result


def list_skills():
    return [
        {k: skill[k] for k in ("task", "name", "title", "description", "sha256", "version")}
        for skill in map(load_skill, SKILLS)
    ]

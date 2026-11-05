"""Read-only, bounded skill discovery. Instructions never grant code execution."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).with_name("resources")
SKILL_CATALOG = {
    "workflow": ("studyui-research-workflow", "研究任务规划与建流"),
    "harness": ("studyui-harness-operations", "Harness 操作与权限流程"),
    "literature": ("studyui-literature-evidence", "科研文献证据检索"),
    "data_quality": ("studyui-raw-data-integrity", "原始数据与质量审查"),
    "spectra": ("studyui-spectrum-analysis", "批量光谱分析"),
    "mechanics": ("studyui-mechanics-analysis", "材料力学分析"),
    "contrast": ("studyui-statistics-and-figures", "组间研究与绘图"),
    "xrd": ("studyui-powder-xrd", "粉末 X 射线衍射"),
    "battery": ("studyui-battery-cycling", "电池循环与老化数据"),
    "thermal": ("studyui-thermal-analysis", "热分析数据"),
    "compression": ("studyui-compressive-strength", "压缩与混凝土强度"),
    "plasmonic": ("studyui-dna-origami-plasmonics", "DNA Origami 等离激元单染料数据"),
    "experimental_design": ("studyui-experimental-design", "材料实验设计"),
    "uncertainty": ("studyui-units-and-uncertainty", "单位与测量不确定度"),
}
SKILLS = {key: SKILL_CATALOG[key] for key in ("spectra", "mechanics", "contrast")}


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
    metadata = {}
    metadata_block = re.search(r"^metadata:[ \t]*\r?\n((?:^[ \t]+[^\r\n]+\r?\n?)*)", match[1], re.M)
    if metadata_block:
        for line in metadata_block[1].splitlines():
            item = re.match(r"^[ \t]+([a-z0-9_-]+):[ \t]*(.*?)\s*$", line)
            if not item:
                continue
            key, value = item.groups()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            metadata[key] = value
    version = metadata.get("version") or "unversioned"
    triggers = [x.strip() for x in metadata.get("triggers", "").split("|") if x.strip()]
    always = str(metadata.get("always", "false")).casefold() == "true"
    return {
        "name": name,
        "description": description,
        "instructions": text,
        "resources": files,
        "sha256": digest(files),
        "executable": False,
        "review_required": True,
        "version": version,
        "metadata": metadata,
        "domain": metadata.get("domain", "materials-science"),
        "triggers": triggers,
        "always": always,
    }


def load_skill(task):
    if task not in SKILL_CATALOG:
        raise ValueError("unknown registered research task")
    name, title = SKILL_CATALOG[task]
    result = inspect_skill(ROOT / name)
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    result.update(task=task, title=title, sources=sources, sha256=digest([result["sha256"], sources]))
    return result


def list_skills():
    return [
        {
            k: skill[k]
            for k in ("task", "name", "title", "description", "sha256", "version", "domain", "triggers", "always")
        }
        for skill in map(load_skill, SKILLS)
    ]

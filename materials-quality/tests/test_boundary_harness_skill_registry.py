"""Boundary tests: Skill ZIP container and sandbox input limits fail cleanly."""

import io
import zipfile

import pytest

from materials_quality.agent.skill_registry import SkillRegistry
from materials_quality.agent.skill_sandbox import SkillSandbox

SKILL_MD = b"---\nname: boundary-skill\ndescription: d\nmetadata:\n  version: 1.0.0\n---\nbody\n"


def _zip(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return out.getvalue()


@pytest.fixture
def registry(tmp_path):
    return SkillRegistry(tmp_path / "skills")


def test_corrupt_zip_raises_actionable_value_error(registry):
    with pytest.raises(ValueError, match="ZIP"):
        registry.import_zip("broken.zip", b"this is not a zip archive")


def test_zip_size_limit_boundary(registry):
    payload = b"x" * 2_000_000
    with pytest.raises(ValueError, match="2 MB"):
        registry.import_zip("large.zip", payload + b"x")


def test_zip_file_count_limit_boundary(registry):
    entries = [("SKILL.md", SKILL_MD)] + [(f"f{index}.txt", b"x") for index in range(127)]
    assert len(entries) == 128
    result = registry.import_zip("ok.zip", _zip(entries))
    assert result["name"] == "boundary-skill"

    entries = [("SKILL.md", SKILL_MD)] + [(f"f{index}.txt", b"x") for index in range(128)]
    with pytest.raises(ValueError, match="128 files"):
        registry.import_zip("too-many.zip", _zip(entries))


def test_skill_sandbox_input_size_limit(registry):
    class FakeRegistry:
        root = registry.root

        def get(self, name):
            return {
                "name": "demo",
                "builtin": False,
                "enabled": True,
                "trusted": True,
                "scripts": ["run.py"],
                "sha256": "0" * 64,
            }

    skill_root = registry.root / "demo"
    skill_root.mkdir(parents=True)
    (skill_root / "run.py").write_text("print(1)", encoding="utf-8")
    sandbox = SkillSandbox(FakeRegistry())

    import json

    prefix = len(json.dumps({"v": ""}, ensure_ascii=False).encode())
    over = {"v": "x" * (1_000_001 - prefix)}
    with pytest.raises(ValueError, match="1 MB"):
        sandbox.run("demo", "run.py", over)

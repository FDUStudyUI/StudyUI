"""Managed research Skills with bounded ZIP import, version hashes and review state."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from materials_quality.skills.registry import SKILL_CATALOG as BUILTIN_SKILLS
from materials_quality.skills.registry import inspect_skill, load_skill

MAX_SKILL_BYTES = 2_000_000
MAX_SKILL_FILES = 128
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _trigger_matches(query, trigger):
    term = str(trigger).casefold().strip()
    if not term:
        return False
    if re.search(r"[a-z0-9]", term):
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", query) is not None
    return term in query


class SkillRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self):
        rows = []
        for task, (_folder, title) in BUILTIN_SKILLS.items():
            item = load_skill(task)
            rows.append(
                {
                    "name": item["name"],
                    "title": title,
                    "description": item["description"],
                    "domain": item.get("domain", "materials-science"),
                    "triggers": item.get("triggers", []),
                    "always": item.get("always", False),
                    "sha256": item["sha256"],
                    "version": item["version"],
                    "builtin": True,
                    "enabled": True,
                    "scripts": [],
                    "trusted": False,
                }
            )
        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            try:
                item = inspect_skill(directory)
                manifest = self._manifest(directory)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            scripts = [
                name
                for name in item["resources"]
                if name.lower().endswith((".py", ".wasm", ".js", ".sh", ".ps1"))
            ]
            rows.append(
                {
                    "name": item["name"],
                    "title": item["name"],
                    "description": item["description"],
                    "domain": item.get("domain", "materials-science"),
                    "triggers": item.get("triggers", []),
                    "always": item.get("always", False),
                    "sha256": item["sha256"],
                    "version": item["version"],
                    "builtin": False,
                    "enabled": bool(manifest.get("enabled", False)),
                    "scripts": scripts,
                    "trusted": manifest.get("trusted_sha256") == item["sha256"],
                    "version_history": list(manifest.get("versions", [])),
                    "review_required": bool(scripts) and manifest.get("trusted_sha256") != item["sha256"],
                }
            )
        return rows

    def select_for_task(self, task_text, *, limit=5):
        """Select bounded, enabled Skills deterministically and explain every match."""
        if not isinstance(task_text, str):
            raise ValueError("Research task must be text")
        if type(limit) is not int or not 1 <= limit <= 8:
            raise ValueError("Skill selection limit must be between 1 and 8")
        query = " ".join(task_text.casefold().split())
        rows = [
            row for row in self.list()
            if row.get("enabled")
            and (row.get("builtin") or not row.get("scripts") or row.get("trusted"))
        ]
        baseline = [row for row in rows if row.get("builtin") and row.get("always")]
        scored = []
        for row in rows:
            if row in baseline:
                continue
            matches = sorted(
                {trigger for trigger in row.get("triggers", []) if _trigger_matches(query, trigger)},
                key=lambda value: (-len(value), value.casefold()),
            )
            if matches:
                score = sum(10 + min(len(value), 48) for value in matches)
                scored.append((score, row, matches))
        scored.sort(key=lambda item: (-item[0], item[1]["name"]))
        selected = []
        for row in baseline:
            selected.append({**row, "reason": "每项科研任务都检查通用建流与原始数据规则。", "matched_triggers": []})
        selected_names = {row["name"] for row in selected}
        for _score, row, matches in scored:
            if row["name"] in selected_names or len(selected) >= limit:
                continue
            selected.append(
                {
                    **row,
                    "reason": "任务文本命中领域触发词：" + "、".join(matches[:6]),
                    "matched_triggers": matches[:12],
                }
            )
            selected_names.add(row["name"])
        digest = hashlib.sha256(task_text.encode("utf-8")).hexdigest()
        return {
            "selector_version": "studyui-skill-router-1.0.0",
            "task_sha256": digest,
            "status": "matched" if any(item["matched_triggers"] for item in selected) else "baseline_only",
            "selected": selected,
        }
    def get(self, name):
        if not isinstance(name, str):
            raise ValueError("Skill name is required")
        for task, (_folder, _title) in BUILTIN_SKILLS.items():
            item = load_skill(task)
            if name in {task, item["name"]}:
                item.update(builtin=True, enabled=True, scripts=[], trusted=False)
                return item
        if not SLUG.fullmatch(name):
            raise ValueError("Invalid Skill name")
        directory = self.root / name
        item = inspect_skill(directory)
        manifest = self._manifest(directory)
        item.update(
            builtin=False,
            enabled=bool(manifest.get("enabled", False)),
            scripts=[
                key
                for key in item["resources"]
                if key.lower().endswith((".py", ".wasm", ".js", ".sh", ".ps1"))
            ],
            trusted=manifest.get("trusted_sha256") == item["sha256"],
            version_history=list(manifest.get("versions", [])),
        )
        return item

    def import_zip(self, filename: str, raw: bytes):
        if not filename.lower().endswith(".zip") or not raw or len(raw) > MAX_SKILL_BYTES:
            raise ValueError("Skill ZIP must be at most 2 MB")
        temp_root = Path(tempfile.mkdtemp(prefix="studyui-skill-", dir=self.root))
        try:
            upload = temp_root / "upload.zip"
            upload.write_bytes(raw)
            with zipfile.ZipFile(upload) as archive:
                entries = [x for x in archive.infolist() if not x.is_dir()]
                if len(entries) > MAX_SKILL_FILES:
                    raise ValueError("Skill ZIP exceeds 128 files")
                total = sum(x.file_size for x in entries)
                if total > MAX_SKILL_BYTES:
                    raise ValueError("Expanded Skill exceeds 2 MB")
                for entry in entries:
                    posix = PurePosixPath(entry.filename)
                    mode = entry.external_attr >> 16
                    if (
                        not posix.parts
                        or posix.is_absolute()
                        or ".." in posix.parts
                        or "\\" in entry.filename
                        or ":" in posix.parts[0]
                    ):
                        raise ValueError("Skill ZIP contains an unsafe path")
                    if stat.S_ISLNK(mode):
                        raise ValueError("Skill ZIP symlinks are not allowed")
                    target = temp_root.joinpath(*posix.parts)
                    if not target.resolve().is_relative_to(temp_root.resolve()):
                        raise ValueError("Skill ZIP path escaped the import directory")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(entry))
            # The uploaded archive itself is not part of the extracted Skill tree.
            upload.unlink(missing_ok=True)
            candidates = [p.parent for p in temp_root.rglob("SKILL.md")]
            if len(candidates) != 1:
                raise ValueError("Skill ZIP must contain exactly one SKILL.md")
            source = candidates[0]
            info = inspect_skill(source)
            if info["name"] in BUILTIN_SKILLS or any(
                info["name"] == load_skill(task)["name"] for task in BUILTIN_SKILLS
            ):
                raise ValueError("Imported Skill cannot replace a built-in Skill")
            destination = self.root / info["name"]
            if destination.exists():
                raise FileExistsError("A Skill with this name already exists; explicitly approve an update")
            shutil.copytree(source, destination)
            self._save_manifest(
                destination,
                {
                    "enabled": False,
                    "trusted_sha256": None,
                    "source_file": Path(filename).name,
                    "sha256": info["sha256"],
                    "versions": [],
                },
            )
            return self.get(info["name"])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def stage_zip(self, filename: str, raw: bytes):
        """Validate and hold a Skill ZIP until a one-shot approval is decided."""
        stage_id = str(uuid.uuid4())
        stage_root = self.root / ".pending-imports"
        stage_root.mkdir(exist_ok=True)
        probe_root = Path(tempfile.mkdtemp(prefix="studyui-skill-probe-", dir=self.root))
        try:
            probe = SkillRegistry(probe_root / "registry")
            info = probe.import_zip(filename, raw)
            current = self.root / info["name"]
            action = "skill.update" if current.exists() else "skill.install"
            current_hash = self.get(info["name"])["sha256"] if current.exists() else None
            stage_path = stage_root / (stage_id + ".zip")
            stage_path.write_bytes(raw)
            return {
                "stage_id": stage_id,
                "name": info["name"],
                "sha256": info["sha256"],
                "scripts": info.get("scripts", []),
                "action": action,
                "title": info["title"],
                "source_file": Path(filename).name,
                "current_sha256": current_hash,
            }
        except Exception:
            (stage_root / (stage_id + ".zip")).unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(probe_root, ignore_errors=True)

    def install_staged(
        self, stage_id, filename, *, replace=False, expected_name=None, expected_current_sha256=None
    ):
        try:
            stage_id = str(uuid.UUID(str(stage_id)))
        except ValueError:
            raise ValueError("Invalid Skill review id") from None
        path = (self.root / ".pending-imports" / (stage_id + ".zip")).resolve()
        if path.parent != (self.root / ".pending-imports").resolve() or not path.is_file():
            raise FileNotFoundError("Skill review package has expired")
        raw = path.read_bytes()
        try:
            if replace:
                if not expected_name:
                    raise ValueError("Skill update requires the reviewed Skill name")
                return self.update_zip(filename, raw, expected_name, expected_current_sha256)
            return self.import_zip(filename, raw)
        finally:
            path.unlink(missing_ok=True)

    def discard_staged(self, stage_id):
        try:
            stage_id = str(uuid.UUID(str(stage_id)))
        except ValueError:
            return False
        path = (self.root / ".pending-imports" / (stage_id + ".zip")).resolve()
        if path.parent != (self.root / ".pending-imports").resolve():
            return False
        path.unlink(missing_ok=True)
        return True

    def update_zip(self, filename: str, raw: bytes, expected_name: str, expected_current_sha256=None):
        """Install a reviewed replacement while retaining the previous version locally."""
        current = self.get(expected_name)
        if current["builtin"]:
            raise ValueError("Built-in Skills cannot be replaced")
        if expected_current_sha256 and current["sha256"] != expected_current_sha256:
            raise ValueError("当前 Skill 版本已变化；请重新预览并审批更新")
        # Extract and validate first through the exact same bounded import path.
        temp_root = Path(tempfile.mkdtemp(prefix="studyui-skill-update-", dir=self.root))
        candidate = None
        try:
            probe = SkillRegistry(temp_root / "probe")
            candidate = probe.import_zip(filename, raw)
            if candidate["name"] != current["name"]:
                raise ValueError("更新包中的 Skill 名称必须与当前版本一致")
            source = temp_root / "probe" / candidate["name"]
            destination = self.root / current["name"]
            manifest = self._manifest(destination)
            version_root = self.root / ".versions" / current["name"]
            version_root.mkdir(parents=True, exist_ok=True)
            previous = version_root / current["sha256"]
            if not previous.exists():
                shutil.copytree(destination, previous)
            history = list(manifest.get("versions", []))
            if current["sha256"] not in history:
                history.append(current["sha256"])
            replacement = self.root / ("." + current["name"] + "-" + uuid.uuid4().hex)
            shutil.copytree(source, replacement)
            self._save_manifest(
                replacement,
                {
                    "enabled": False,
                    "trusted_sha256": None,
                    "source_file": Path(filename).name,
                    "sha256": candidate["sha256"],
                    "versions": history,
                },
            )
            old = self.root / ("." + current["name"] + "-old-" + uuid.uuid4().hex)
            os.replace(destination, old)
            try:
                os.replace(replacement, destination)
            except Exception:
                os.replace(old, destination)
                raise
            shutil.rmtree(old, ignore_errors=True)
            return self.get(current["name"])
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def set_enabled(self, name, enabled):
        item = self.get(name)
        if item["builtin"]:
            raise ValueError("Built-in Skills cannot be disabled here")
        if enabled and item["scripts"] and not item["trusted"]:
            raise ValueError("含脚本的 Skill 必须先审核并信任当前版本")
        directory = self.root / item["name"]
        manifest = self._manifest(directory)
        manifest["enabled"] = bool(enabled)
        self._save_manifest(directory, manifest)
        return self.get(item["name"])

    def trust(self, name, expected_sha256):
        item = self.get(name)
        if item["builtin"]:
            raise ValueError("Built-in Skill trust cannot be changed")
        if item["sha256"] != expected_sha256:
            raise ValueError("Skill changed since it was reviewed")
        directory = self.root / item["name"]
        manifest = self._manifest(directory)
        manifest["trusted_sha256"] = expected_sha256
        manifest["enabled"] = True
        manifest["reviewed_files"] = item["resources"]
        self._save_manifest(directory, manifest)
        return self.get(item["name"])

    def remove(self, name):
        item = self.get(name)
        if item["builtin"]:
            raise ValueError("Built-in Skills cannot be removed")
        directory = (self.root / item["name"]).resolve()
        if directory.parent != self.root:
            raise ValueError("Skill path escaped its registry")
        shutil.rmtree(directory)
        return {"removed": item["name"]}

    def _manifest(self, directory):
        path = directory / "studyui-skill.json"
        if not path.exists():
            return {"enabled": False, "trusted_sha256": None}
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Skill manifest must be an object")
        return value

    def _save_manifest(self, directory, value):
        path = directory / "studyui-skill.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

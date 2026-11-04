"""File-backed workflow repository for StudyUI.

Each workflow is a JSON object named by its UUID. Writes use an atomic replace;
callers can supply the revision obtained during read to prevent lost updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock


class WorkflowConflictError(ValueError):
    """The workflow was changed after the caller read it."""


class WorkflowFileStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._file_lock = FileLock(str(self.root / ".workflows.lock"), timeout=30)

    def _path(self, flow_id: str) -> Path:
        try:
            canonical = str(uuid.UUID(str(flow_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid workflow ID") from exc
        return self.root / (canonical + ".json")

    @staticmethod
    def _revision(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def read(self, flow_id: str) -> tuple[dict, str]:
        with self._lock:
            raw = self._path(flow_id).read_bytes()
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict) or str(value.get("id")) != str(uuid.UUID(str(flow_id))):
                raise ValueError("Workflow file does not match its ID")
            return value, self._revision(raw)

    def list(self) -> list[dict]:
        with self._lock:
            return [self.read(path.stem)[0] for path in sorted(self.root.glob("*.json"))]

    def save(self, flow: dict, *, expected_revision: str | None = None, create_only: bool = False) -> str:
        if not isinstance(flow, dict) or not isinstance(flow.get("data"), dict):
            raise ValueError("Workflow must contain a data object")
        path = self._path(flow.get("id"))
        if str(flow["id"]) != path.stem:
            raise ValueError("Workflow ID must be a canonical UUID")
        raw = (json.dumps(flow, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        with self._lock, self._file_lock:
            exists = path.exists()
            if create_only and exists:
                raise FileExistsError(path)
            if expected_revision is not None:
                if not exists or self._revision(path.read_bytes()) != expected_revision:
                    raise WorkflowConflictError("Workflow was changed by another editor")
            if exists:
                previous = path.read_bytes()
                if previous != raw:
                    self._save_history(path.stem, previous)
            temp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    dir=self.root, prefix=".workflow-", suffix=".tmp", delete=False
                ) as output:
                    temp_name = output.name
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp_name, path)
            finally:
                if temp_name and os.path.exists(temp_name):
                    os.unlink(temp_name)
        return self._revision(raw)

    def _save_history(self, flow_id: str, raw: bytes):
        revision = self._revision(raw)
        directory = self.root / ".history" / flow_id
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.glob(revision + "-*.json")):
            return
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = directory / f"{revision}-{stamp}.json"
        with target.open("xb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())

    def history(self, flow_id: str):
        directory = self.root / ".history" / str(uuid.UUID(str(flow_id)))
        if not directory.is_dir():
            return []
        rows = []
        for path in sorted(directory.glob("*.json"), reverse=True):
            raw = path.read_bytes()
            try:
                flow = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                continue
            rows.append(
                {
                    "revision": self._revision(raw),
                    "saved_at": path.stem.rsplit("-", 1)[-1],
                    "name": flow.get("name", ""),
                    "size": len(raw),
                }
            )
        return rows

    def restore(self, flow_id: str, revision: str):
        if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("Invalid workflow revision")
        flow_path = self._path(flow_id)
        directory = self.root / ".history" / flow_path.stem
        candidates = list(directory.glob(str(revision) + "-*.json")) if directory.is_dir() else []
        if len(candidates) != 1:
            raise FileNotFoundError("Workflow revision not found")
        current, expected = self.read(flow_id)
        restored = json.loads(candidates[0].read_text(encoding="utf-8"))
        restored["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save(restored, expected_revision=expected)
        return restored

    def import_snapshot(self, directory: str | Path) -> list[str]:
        """Import a snapshot without overwriting any existing workflow."""
        source = Path(directory)
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        imported = []
        for entry in manifest["flows"]:
            path = source / (str(uuid.UUID(str(entry["id"]))) + ".json")
            flow = json.loads(path.read_text(encoding="utf-8"))
            if str(flow.get("id")) != str(entry["id"]):
                raise ValueError("Snapshot entry ID does not match workflow")
            self.save(flow, create_only=True)
            imported.append(str(flow["id"]))
        return imported

    def delete(self, flow_id: str) -> Path:
        """Move a workflow to a local recovery folder rather than discarding it."""
        path = self._path(flow_id)
        trash = self.root / ".trash"
        with self._lock, self._file_lock:
            if not path.is_file():
                raise FileNotFoundError(path)
            trash.mkdir(exist_ok=True)
            target = trash / f"{path.stem}-{uuid.uuid4()}.json"
            if not target.resolve().is_relative_to(self.root):
                raise ValueError("Recovery path must stay in the workflow directory")
            os.replace(path, target)
            return target

"""Durable task status with cooperative cancellation and idempotent submission.

Cancellation never claims to interrupt an in-flight native or network call.
Checkpoints prevent subsequent operations; partial artifacts remain in the session.
"""

import json
import sqlite3
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

_cancel = ContextVar("studyui_task_cancel", default=None)
TERMINAL = {"completed", "cancelled", "failed", "interrupted", "waiting_approval"}


class SessionBusy(ValueError):
    """Another workflow or turn is already executing in this session."""


class TaskCancelled(Exception):
    """The user requested stopping before the next operation."""


def checkpoint():
    signal = _cancel.get()
    if signal is not None and signal.is_set():
        raise TaskCancelled("任务已取消；已完成的操作和产物保留。")


def _now():
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    """One manager per runtime database in a single StudyUI server process.

    SQLite retains task records across restarts. Active workers and session
    exclusion are process-local, so this runtime requires a single server worker.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.signals = {}
        self.legacy_sessions = set()
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, request_key TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                result TEXT, error TEXT, progress TEXT, fingerprint TEXT NOT NULL,
                UNIQUE(session_id, request_key))""")
            if "partial_content" not in {row[1] for row in db.execute("PRAGMA table_info(tasks)")}:
                db.execute("ALTER TABLE tasks ADD COLUMN partial_content TEXT NOT NULL DEFAULT ''")
            db.execute(
                "UPDATE tasks SET status='interrupted', error=?, updated_at=? "
                "WHERE status IN ('queued','running','cancelling')",
                ("服务已重启；任务未自动重放，请查看已有产物后决定是否重新运行。", _now()),
            )

    def _db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        return db

    def get(self, task_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        value = dict(row)
        for key in ("result", "progress"):
            value[key] = json.loads(value[key]) if value[key] else None
        value["terminal"] = value["status"] in TERMINAL
        return value

    def list(self, session_id):
        with self._db() as db:
            rows = db.execute(
                "SELECT id FROM tasks WHERE session_id=? ORDER BY created_at DESC LIMIT 30", (session_id,)
            ).fetchall()
        return [self.get(row["id"]) for row in rows]

    def _update(self, task_id, **values):
        values["updated_at"] = _now()
        for key in ("result", "progress"):
            if key in values:
                values[key] = json.dumps(values[key], ensure_ascii=False, allow_nan=False)
        with self._db() as db:
            db.execute(
                "UPDATE tasks SET " + ", ".join(k + "=?" for k in values) + " WHERE id=?",
                (*values.values(), task_id),
            )

    def _require_idle(self, db, session_id):
        if (
            session_id in self.legacy_sessions
            or db.execute(
                "SELECT 1 FROM tasks WHERE session_id=? AND status IN ('queued','running','cancelling')",
                (session_id,),
            ).fetchone()
        ):
            raise SessionBusy("该会话已有运行任务，请等待或取消后再试。")

    def run_legacy(self, session_id, work, /, *args, **kwargs):
        """Preserve synchronous and SSE clients under the shared session guard."""
        with self.lock, self._db() as db:
            self._require_idle(db, session_id)
            self.legacy_sessions.add(session_id)
        try:
            return work(*args, **kwargs)
        finally:
            with self.lock:
                self.legacy_sessions.remove(session_id)

    def submit(self, session_id, request_key, work, *, fingerprint=""):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 100:
            raise ValueError("任务请求标识无效。")
        with self.lock, self._db() as db:
            old = db.execute(
                "SELECT id,fingerprint FROM tasks WHERE session_id=? AND request_key=?",
                (session_id, request_key),
            ).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise ValueError("相同请求标识不能用于不同任务。")
                return self.get(old["id"])
            self._require_idle(db, session_id)
            if len(self.signals) >= 4:
                raise ValueError("运行任务已达上限，请稍后重试。")
            task_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO tasks(id,session_id,request_key,status,created_at,updated_at,fingerprint) "
                "VALUES(?,?,?,'queued',?,?,?)",
                (task_id, session_id, request_key, _now(), _now(), fingerprint),
            )
            db.commit()
            signal = threading.Event()
            self.signals[task_id] = signal
            threading.Thread(target=self._run, args=(task_id, signal, work), daemon=True).start()
        return self.get(task_id)

    def _run(self, task_id, signal, work):
        token = _cancel.set(signal)
        partial_content = ""
        last_flush = 0.0
        try:
            with self.lock:
                checkpoint()
                self._update(task_id, status="running")

            def progress(event):
                nonlocal partial_content, last_flush
                checkpoint()
                # Store bounded operational events, not model reasoning/token history.
                kind = event.get("type")
                if kind == "content_chunk":
                    partial_content = (partial_content + str(event.get("delta", "")))[:100_000]
                    if time.monotonic() - last_flush >= 0.2:
                        self._update(task_id, partial_content=partial_content)
                        last_flush = time.monotonic()
                if kind in {"tool_start", "tool_end", "step_end", "thinking_start"}:
                    safe = {k: v for k, v in event.items() if k in {"type", "step", "round", "model"}}
                    if len(json.dumps(safe, ensure_ascii=False)) <= 8000:
                        self._update(task_id, progress=safe)

            result = work(progress)
            with self.lock:
                status = (
                    "cancelled"
                    if signal.is_set()
                    else (
                        "waiting_approval"
                        if isinstance(result, dict)
                        and result.get("task_pending_approvals", result.get("pending_approvals"))
                        else "failed"
                        if isinstance(result, dict) and result.get("task_status") == "failed"
                        else "completed"
                    )
                )
                self._update(task_id, status=status, result=result, partial_content=partial_content)
        except TaskCancelled as exc:
            with self.lock:
                self._update(task_id, status="cancelled", error=str(exc), partial_content=partial_content)
        except Exception as exc:
            with self.lock:
                self._update(
                    task_id,
                    status="cancelled" if signal.is_set() else "failed",
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                    partial_content=partial_content,
                )
        finally:
            _cancel.reset(token)
            with self.lock:
                self.signals.pop(task_id, None)

    def cancel(self, task_id):
        with self.lock:
            task = self.get(task_id)
            if task["terminal"]:
                return task
            signal = self.signals.get(task_id)
            if signal is None:
                raise ValueError("任务执行器不可用，请重新读取状态。")
            signal.set()
            self._update(task_id, status="cancelling")
            return self.get(task_id)

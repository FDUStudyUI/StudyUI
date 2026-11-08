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
        self.live_content = {}
        self.subscribers = {}
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

    def subscribe(self, task_id, callback):
        """Subscribe to live task events and return a current, race-free snapshot."""
        with self.lock:
            task = self.get(task_id)
            self.subscribers.setdefault(task_id, set()).add(callback)
            live = self.live_content.get(task_id)
            task["partial_content"] = (
                "".join(live) if isinstance(live, list) else (live or task["partial_content"])
            )
        return task

    def unsubscribe(self, task_id, callback):
        with self.lock:
            listeners = self.subscribers.get(task_id)
            if listeners is not None:
                listeners.discard(callback)
                if not listeners:
                    self.subscribers.pop(task_id, None)

    def _publish(self, task_id, event):
        with self.lock:
            listeners = tuple(self.subscribers.get(task_id, ()))
        for callback in listeners:
            try:
                callback(event)
            except Exception:
                pass

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
            self.live_content[task_id] = []
            threading.Thread(target=self._run, args=(task_id, signal, work), daemon=True).start()
        return self.get(task_id)

    def _run(self, task_id, signal, work):
        token = _cancel.set(signal)
        partial_chunks = []
        partial_length = 0
        pending_emit_chunks = []
        pending_emit_length = 0
        pending_reasoning_chunks = []
        pending_reasoning_length = 0
        reasoning_length = 0
        last_emit = 0.0
        last_flush = 0.0
        last_reasoning_emit = 0.0

        def partial_content():
            return "".join(partial_chunks)

        def flush_stream():
            nonlocal pending_emit_length, last_emit
            if not pending_emit_chunks:
                return
            delta = "".join(pending_emit_chunks)
            pending_emit_chunks.clear()
            pending_emit_length = 0
            last_emit = time.monotonic()
            self._publish(task_id, {"type": "content_chunk", "delta": delta})

        def flush_reasoning():
            nonlocal pending_reasoning_length, last_reasoning_emit
            if not pending_reasoning_chunks:
                return
            delta = "".join(pending_reasoning_chunks)
            pending_reasoning_chunks.clear()
            pending_reasoning_length = 0
            last_reasoning_emit = time.monotonic()
            # Live only: reasoning deltas are never included in task snapshots or SQLite.
            self._publish(task_id, {"type": "reasoning_chunk", "delta": delta})

        try:
            with self.lock:
                checkpoint()
                self._update(task_id, status="running")
            self._publish(task_id, {"type": "status", "status": "running"})

            def progress(event):
                nonlocal partial_length, pending_emit_length, pending_reasoning_length, reasoning_length
                nonlocal last_flush, last_emit, last_reasoning_emit
                checkpoint()
                # Store bounded operational events, not model reasoning/token history.
                kind = event.get("type")
                if kind == "stream_reset":
                    with self.lock:
                        partial_chunks.clear()
                        partial_length = 0
                        pending_emit_chunks.clear()
                        pending_emit_length = 0
                        pending_reasoning_chunks.clear()
                        pending_reasoning_length = 0
                        reasoning_length = 0
                        last_emit = 0.0
                        last_reasoning_emit = 0.0
                        last_flush = 0.0
                        self.live_content[task_id] = partial_chunks
                        self._update(task_id, partial_content="")
                    retry = event.get("attempt")
                    maximum = event.get("max_attempts")
                    self._publish(
                        task_id,
                        {
                            "type": "stream_reset",
                            "attempt": retry if type(retry) is int else None,
                            "max_attempts": maximum if type(maximum) is int else None,
                        },
                    )
                elif kind == "content_chunk":
                    delta = str(event.get("delta", ""))
                    visible_delta = delta[: max(0, 100_000 - partial_length)]
                    if visible_delta:
                        with self.lock:
                            partial_chunks.append(visible_delta)
                            partial_length += len(visible_delta)
                            pending_emit_chunks.append(visible_delta)
                            pending_emit_length += len(visible_delta)
                            self.live_content[task_id] = partial_chunks
                        if (
                            not last_emit
                            or time.monotonic() - last_emit >= 0.016
                            or pending_emit_length >= 1024
                        ):
                            flush_stream()
                    if time.monotonic() - last_flush >= 0.2:
                        self._update(task_id, partial_content=partial_content())
                        last_flush = time.monotonic()
                elif kind == "reasoning":
                    delta = str(event.get("delta", ""))
                    visible_delta = delta[: max(0, 50_000 - reasoning_length)]
                    if visible_delta:
                        pending_reasoning_chunks.append(visible_delta)
                        pending_reasoning_length += len(visible_delta)
                        reasoning_length += len(visible_delta)
                        if (
                            not last_reasoning_emit
                            or time.monotonic() - last_reasoning_emit >= 0.016
                            or pending_reasoning_length >= 1024
                        ):
                            flush_reasoning()
                if kind in {"tool_start", "tool_end", "step_end", "thinking_start", "usage"}:
                    allowed = {
                        "type",
                        "step",
                        "round",
                        "model",
                        "id",
                        "name",
                        "title",
                        "icon",
                        "token_usage",
                        "performance",
                        "latest_request_usage",
                    }
                    safe = {k: v for k, v in event.items() if k in allowed}
                    if len(json.dumps(safe, ensure_ascii=False)) <= 8000:
                        self._update(task_id, progress=safe)
                        self._publish(task_id, {"type": "progress", "progress": safe})

            result = work(progress)
            flush_stream()
            flush_reasoning()
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
                self._update(task_id, status=status, result=result, partial_content=partial_content())
        except TaskCancelled as exc:
            flush_stream()
            flush_reasoning()
            with self.lock:
                self._update(task_id, status="cancelled", error=str(exc), partial_content=partial_content())
        except Exception as exc:
            flush_stream()
            flush_reasoning()
            with self.lock:
                self._update(
                    task_id,
                    status="cancelled" if signal.is_set() else "failed",
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                    partial_content=partial_content(),
                )
        finally:
            _cancel.reset(token)
            with self.lock:
                self.signals.pop(task_id, None)
            try:
                self._publish(task_id, {"type": "terminal", "task": self.get(task_id)})
            finally:
                with self.lock:
                    self.live_content.pop(task_id, None)

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
            self._publish(task_id, {"type": "status", "status": "cancelling"})
            return self.get(task_id)

    def resolve_approval(self, session_id, approval_id, outcome, *, resume_started=False):
        """Resolve task snapshots that were paused specifically for this approval."""
        if outcome not in {"approved", "rejected", "cancelled", "invalidated", "failed"}:
            raise ValueError("Invalid approval outcome")
        updated = []
        with self.lock, self._db() as db:
            rows = db.execute(
                "SELECT id,result FROM tasks WHERE session_id=? AND status='waiting_approval'",
                (session_id,),
            ).fetchall()
            for row in rows:
                result = json.loads(row["result"]) if row["result"] else {}
                pending = result.get("task_pending_approvals")
                if not isinstance(pending, list):
                    pending = result.get("pending_approvals", [])
                if not any(isinstance(item, dict) and item.get("id") == approval_id for item in pending):
                    continue
                remaining = [
                    item for item in pending if not isinstance(item, dict) or item.get("id") != approval_id
                ]
                result["task_pending_approvals"] = remaining
                result["pending_approvals"] = [
                    item
                    for item in result.get("pending_approvals", [])
                    if not isinstance(item, dict) or item.get("id") != approval_id
                ]
                outcomes = result.setdefault("resolved_approvals", [])
                outcomes.append({"id": approval_id, "status": outcome})
                if remaining:
                    status = "waiting_approval"
                elif outcome in {"invalidated", "failed"} or any(
                    item.get("status") in {"invalidated", "failed"}
                    for item in outcomes
                    if isinstance(item, dict)
                ):
                    status = "failed"
                    result["message"] = "审批所依据的操作已失效或失败；原操作未执行。"
                elif outcome in {"rejected", "cancelled"} or any(
                    item.get("status") in {"rejected", "cancelled"}
                    for item in outcomes
                    if isinstance(item, dict)
                ):
                    status = "cancelled"
                    result["message"] = "待审批操作已被拒绝或取消，未执行。"
                else:
                    status = "completed"
                    result["message"] = (
                        "获批操作已执行，StudyUI Agent 已在续接任务中继续研究。"
                        if resume_started
                        else "获批操作已执行。"
                    )
                self._update(row["id"], status=status, result=result)
                task = self.get(row["id"])
                updated.append({"id": task["id"], "status": task["status"], "terminal": task["terminal"]})
                self._publish(row["id"], {"type": "approval_resolved", "task": task})
                if task["terminal"]:
                    self._publish(row["id"], {"type": "terminal", "task": task})
        return updated

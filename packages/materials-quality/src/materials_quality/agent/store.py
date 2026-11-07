"""Local, append-only conversation and approval storage for the harness."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionStore:
    def __init__(self, path, *, workspace_file=None, workflow_root=None):
        self.path = Path(path).expanduser().absolute()
        self.workspace_file = Path(workspace_file).resolve() if workspace_file else None
        self.workflow_root = Path(workflow_root).resolve() if workflow_root else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _write_workspace(self, data):
        path = self.workspace_file
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as out:
            temporary = out.name
            out.write((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)

    def _workspace_operation(self, operation=None):
        """Use the same project catalog as the canvas and mirror IDs for session foreign keys."""
        if not self.workspace_file or not self.workspace_file.exists():
            return None
        with FileLock(str(self.workspace_file) + ".lock", timeout=30), self._connect() as db:
            workspace = json.loads(self.workspace_file.read_text(encoding="utf-8"))
            projects = workspace.setdefault("projects", [])
            if not workspace.get("session_projects_migrated"):
                known = {p["id"] for p in projects}
                for row in db.execute(
                    "SELECT id,title,description FROM projects ORDER BY position,created_at"
                ):
                    if row["id"] not in known:
                        projects.append(
                            {
                                "id": row["id"],
                                "name": row["title"],
                                "description": row["description"],
                                "parent_id": None,
                            }
                        )
                workspace["session_projects_migrated"] = True
            result = operation(workspace) if operation else None
            projects = workspace["projects"]
            now = _now()
            for position, p in enumerate(projects):
                db.execute(
                    """INSERT INTO projects(id,title,description,position,created_at,updated_at)
                              VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                              title=excluded.title, description=excluded.description,"""
                    " position=excluded.position",
                    (p["id"], p["name"], p.get("description", ""), position, now, now),
                )
            ids = [p["id"] for p in projects]
            if ids:
                db.execute("DELETE FROM projects WHERE id NOT IN (" + ",".join("?" * len(ids)) + ")", ids)
            else:
                db.execute("DELETE FROM projects")
            self._write_workspace(workspace)
            return result

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    message_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_by_session
                    ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    flow_id TEXT NOT NULL,
                    base_digest TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    project_id TEXT,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS approvals_by_session
                    ON approvals(session_id, status, created_at);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_by_session
                    ON artifacts(session_id, created_at);
                """
            )
            columns = {row["name"] for row in db.execute("PRAGMA table_info(sessions)")}
            if "project_id" not in columns:
                db.execute(
                    "ALTER TABLE sessions ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET "
                    "NULL"
                )

    def create_project(self, title, description=""):
        project_id, now = str(uuid.uuid4()), _now()
        title = str(title).strip()[:120]
        if not title:
            raise ValueError("项目名称不能为空")
        if self.workspace_file and self.workspace_file.exists():

            def add(workspace):
                workspace["projects"].append(
                    {
                        "id": project_id,
                        "name": title,
                        "description": str(description).strip()[:1000],
                        "parent_id": None,
                    }
                )

            self._workspace_operation(add)
            return project_id
        with self._connect() as db:
            position = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM projects").fetchone()[0]
            db.execute(
                "INSERT INTO projects(id,title,description,position,created_at,updated_at) VALUES(?,?,?,?,?,"
                "?)",
                (project_id, title, str(description).strip()[:1000], position, now, now),
            )
        return project_id

    def list_projects(self):
        self._workspace_operation()
        with self._connect() as db:
            rows = db.execute(
                """SELECT p.id,p.title,p.description,p.position,p.created_at,p.updated_at,
                          COUNT(s.id) AS session_count
                   FROM projects p LEFT JOIN sessions s ON s.project_id=p.id
                   GROUP BY p.id ORDER BY p.position,p.created_at"""
            ).fetchall()
        return [dict(row) for row in rows]

    def update_project(self, project_id, title):
        title = str(title).strip()[:120]
        if not title:
            raise ValueError("项目名称不能为空")
        if self.workspace_file and self.workspace_file.exists():

            def rename(workspace):
                project = next((p for p in workspace["projects"] if p["id"] == project_id), None)
                if project is None:
                    raise ValueError("项目不存在")
                project["name"] = title

            self._workspace_operation(rename)
            return True
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE projects SET title=?,updated_at=? WHERE id=?", (title, _now(), project_id)
            )
            if cursor.rowcount != 1:
                raise ValueError("项目不存在")
        return True

    def delete_project(self, project_id):
        if self.workspace_file and self.workspace_file.exists():

            def remove(workspace):
                if not any(p["id"] == project_id for p in workspace["projects"]):
                    raise ValueError("项目不存在")
                if self.workflow_root:
                    from .workflow_files import WorkflowFileStore

                    store = WorkflowFileStore(self.workflow_root)
                    for flow in store.list():
                        if flow.get("folder_id") == project_id:
                            store.delete(flow["id"])
                workspace["projects"] = [p for p in workspace["projects"] if p["id"] != project_id]

            self._workspace_operation(remove)
            return
        with self._connect() as db:
            cursor = db.execute("DELETE FROM projects WHERE id=?", (project_id,))
            if cursor.rowcount != 1:
                raise ValueError("项目不存在")

    def has_project(self, project_id):
        self._workspace_operation()
        with self._connect() as db:
            return db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is not None

    def create_session(self, title="科研任务", project_id=None):
        session_id, now = str(uuid.uuid4()), _now()
        if project_id and not self.has_project(project_id):
            raise ValueError("目标项目不存在")
        with self._connect() as db:
            db.execute(
                "INSERT INTO sessions(id,title,project_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                (session_id, str(title)[:120] or "科研任务", project_id, now, now),
            )
        return session_id

    def list_sessions(self, project_id=None):
        with self._connect() as db:
            if project_id == "__ungrouped__":
                query = (
                    "SELECT id,title,project_id,created_at,updated_at FROM sessions WHERE project_id IS "
                    "NULL ORDER BY updated_at DESC LIMIT 300"
                )
                rows = db.execute(query).fetchall()
            elif project_id:
                rows = db.execute(
                    "SELECT id,title,project_id,created_at,updated_at FROM sessions WHERE project_id=? "
                    "ORDER BY updated_at DESC LIMIT 300",
                    (project_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT id,title,project_id,created_at,updated_at FROM sessions ORDER BY updated_at "
                    "DESC LIMIT 300"
                ).fetchall()
        return [dict(row) for row in rows]

    def update_session(self, session_id, *, title=None, project_id=...):
        if project_id is not ... and project_id:
            self._workspace_operation()
        with self._connect() as db:
            if db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is None:
                raise ValueError("会话不存在")
            if title is not None:
                normalized = str(title).strip()[:120]
                if not normalized:
                    raise ValueError("会话名称不能为空")
                db.execute(
                    "UPDATE sessions SET title=?,updated_at=? WHERE id=?", (normalized, _now(), session_id)
                )
            if project_id is not ...:
                if (
                    project_id
                    and db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None
                ):
                    raise ValueError("目标项目不存在")
                db.execute(
                    "UPDATE sessions SET project_id=?,updated_at=? WHERE id=?",
                    (project_id, _now(), session_id),
                )

    def delete_session(self, session_id):
        with self._connect() as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            db.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            db.execute("DELETE FROM proposals WHERE session_id = ?", (session_id,))
            db.execute("DELETE FROM approvals WHERE session_id = ?", (session_id,))
            db.execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))
            cursor = db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            return cursor.rowcount > 0

    def has_session(self, session_id):
        with self._connect() as db:
            return db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is not None

    def session_context(self, session_id):
        with self._connect() as db:
            row = db.execute("SELECT id,title,project_id FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def append_message(self, session_id, message):
        now = _now()
        serialized = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as db:
            db.execute(
                "INSERT INTO messages(session_id,message_json,created_at) VALUES(?,?,?)",
                (session_id, serialized, now),
            )
            db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))

    def messages(self, session_id, limit=40):
        with self._connect() as db:
            rows = db.execute(
                "SELECT message_json FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def user_messages(self, session_id):
        """Keep the initial research request and recent user corrections across long tool histories."""
        with self._connect() as db:
            first = db.execute(
                "SELECT id,message_json FROM messages WHERE session_id=? AND json_extract(message_json,'$."
                "role')='user' ORDER BY id LIMIT 1",
                (session_id,),
            ).fetchall()
            recent = db.execute(
                "SELECT id,message_json FROM messages WHERE session_id=? AND json_extract(message_json,'$."
                "role')='user' ORDER BY id DESC LIMIT 8",
                (session_id,),
            ).fetchall()
        return [
            json.loads(row[1])
            for row in sorted({row[0]: row for row in first + recent}.values(), key=lambda row: row[0])
        ]

    def session_created_flow_ids(self, session_id):
        with self._connect() as db:
            rows = db.execute(
                "SELECT detail_json FROM events WHERE session_id=? AND kind='workflow_created'", (session_id,)
            ).fetchall()
        return {json.loads(row[0]).get("flow_id") for row in rows} - {None}

    def append_event(self, session_id, kind, detail):
        with self._connect() as db:
            db.execute(
                "INSERT INTO events(session_id,kind,detail_json,created_at) VALUES(?,?,?,?)",
                (session_id, str(kind)[:80], json.dumps(detail, ensure_ascii=False), _now()),
            )

    def events(self, session_id, limit=100):
        with self._connect() as db:
            rows = db.execute(
                "SELECT kind,detail_json,created_at FROM events WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, max(1, min(int(limit), 500))),
            ).fetchall()
        return [
            {"kind": row["kind"], "detail": json.loads(row["detail_json"]), "created_at": row["created_at"]}
            for row in reversed(rows)
        ]

    def register_artifact(self, artifact_id, session_id, project_id, name, path, sha256, size):
        created_at = _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO artifacts(id,session_id,project_id,name,path,sha256,size,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (artifact_id, session_id, project_id, name, str(path), sha256, int(size), created_at),
            )
        self.append_event(
            session_id,
            "artifact_created",
            {"artifact_id": artifact_id, "name": name, "sha256": sha256, "size": int(size)},
        )
        return self.get_artifact(artifact_id, session_id)

    @staticmethod
    def _public_artifact(row):
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "sha256": row["sha256"],
            "size": row["size"],
            "created_at": row["created_at"],
            "download_url": f"/api/sessions/{row['session_id']}/artifacts/{row['id']}",
        }

    def list_artifacts(self, session_id, *, since=None):
        query = "SELECT * FROM artifacts WHERE session_id=?"
        params = [session_id]
        if since is not None:
            query += " AND created_at>=?"
            params.append(str(since))
        query += " ORDER BY created_at,id"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._public_artifact(row) for row in rows]

    def latest_artifacts(self, session_id):
        """Return newest artifacts by name and content while keeping all history downloadable by id."""
        latest = {}
        for item in self.list_artifacts(session_id):
            previous = latest.get(item["name"])
            if previous is None or (item["created_at"], item["id"]) > (
                previous["created_at"],
                previous["id"],
            ):
                latest[item["name"]] = item
        unique_content = {}
        for item in latest.values():
            digest = item["sha256"]
            previous = unique_content.get(digest)
            if previous is None or (item["created_at"], item["id"]) > (
                previous["created_at"],
                previous["id"],
            ):
                unique_content[digest] = item
        return sorted(unique_content.values(), key=lambda item: (item["created_at"], item["id"]))

    def get_artifact(self, artifact_id, session_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM artifacts WHERE id=? AND session_id=?", (artifact_id, session_id)
            ).fetchone()
        if row is None:
            return None
        return {**self._public_artifact(row), "path": row["path"]}

    def save_proposal(self, session_id, flow_id, base_digest, candidate, summary):
        proposal_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO proposals
                   (id,session_id,flow_id,base_digest,candidate_json,summary_json,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    proposal_id,
                    session_id,
                    str(flow_id),
                    base_digest,
                    json.dumps(candidate, ensure_ascii=False),
                    json.dumps(summary, ensure_ascii=False),
                    "pending",
                    now,
                    now,
                ),
            )
        return proposal_id

    def get_proposal(self, proposal_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["candidate"] = json.loads(result.pop("candidate_json"))
        result["summary"] = json.loads(result.pop("summary_json"))
        return result

    def update_proposal_status(self, proposal_id, expected, status):
        now = _now()
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE proposals SET status=?,updated_at=? WHERE id=? AND status=?",
                (status, now, proposal_id, expected),
            )
            return cursor.rowcount == 1

    def pending_proposals(self, session_id=None):
        query = (
            "SELECT id,session_id,flow_id,summary_json,status,created_at FROM proposals WHERE "
            "status='pending'"
        )
        params = ()
        if session_id:
            query += " AND session_id=?"
            params = (session_id,)
        query += " ORDER BY created_at"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "flow_id": row["flow_id"],
                "summary": json.loads(row["summary_json"]),
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def create_approval(self, approval_id, session_id, project_id, action, reason, request):
        now = _now()
        with self._connect() as db:
            db.execute(
                """INSERT INTO approvals
                   (id,session_id,project_id,action,reason,request_json,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?, 'pending', ?, ?)""",
                (
                    approval_id,
                    session_id,
                    project_id,
                    str(action)[:100],
                    str(reason)[:1000],
                    json.dumps(request, ensure_ascii=False, allow_nan=False),
                    now,
                    now,
                ),
            )
        self.append_event(
            session_id,
            "approval_requested",
            {
                "approval_id": approval_id,
                "action": action,
                "project_id": project_id,
                "reason": str(reason)[:1000],
            },
        )

    def get_approval(self, approval_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        return result

    def pending_approvals(self, session_id=None):
        query = (
            "SELECT id,session_id,project_id,action,reason,request_json,status,created_at FROM approvals "
            "WHERE status='pending'"
        )
        params = ()
        if session_id:
            query += " AND session_id=?"
            params = (session_id,)
        query += " ORDER BY created_at"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            request = json.loads(item.pop("request_json"))
            item["summary"] = request.get("summary", {})
            result.append(item)
        return result

    def decide_approval(self, approval_id, decision):
        if decision not in {"approved", "rejected", "cancelled"}:
            raise ValueError("Invalid approval decision")
        now = _now()
        with self._connect() as db:
            row = db.execute(
                "SELECT session_id,action FROM approvals WHERE id=? AND status='pending'", (approval_id,)
            ).fetchone()
            if row is None:
                return False
            changed = (
                db.execute(
                    "UPDATE approvals SET status=?,updated_at=? WHERE id=? AND status='pending'",
                    (decision, now, approval_id),
                ).rowcount
                == 1
            )
        if changed:
            self.append_event(
                row["session_id"],
                "approval_decided",
                {"approval_id": approval_id, "action": row["action"], "decision": decision},
            )
        return changed

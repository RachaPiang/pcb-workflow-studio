"""SQLite is authoritative; immutable snapshots and content-addressed originals."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .schemas import Project, now


class Conflict(ValueError):
    pass


def digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "projects.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, version INTEGER NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (
                    project_id TEXT NOT NULL, version INTEGER NOT NULL, document TEXT NOT NULL,
                    PRIMARY KEY(project_id, version));
            """)

    def connect(self):
        return sqlite3.connect(self.db_path, timeout=15)

    def save(self, project: Project, expected: int, reason: str) -> Project:
        item = project.model_copy(deep=True)
        item.version = expected + 1
        item.updated_at = now()
        item.change_reason = reason
        document = item.model_dump_json(indent=2)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM projects WHERE id=?", (item.id,)).fetchone()
            if (row[0] if row else 0) != expected:
                raise Conflict("โปรเจกต์มีการเปลี่ยนแปลงแล้ว กรุณาโหลดใหม่ก่อนบันทึก")
            db.execute("INSERT OR REPLACE INTO projects VALUES (?,?,?)", (item.id, item.version, document))
            db.execute("INSERT INTO snapshots VALUES (?,?,?)", (item.id, item.version, document))
        return item

    def get(self, project_id: str, version: int | None = None) -> Project:
        with self.connect() as db:
            if version is None:
                row = db.execute("SELECT document FROM projects WHERE id=?", (project_id,)).fetchone()
            else:
                row = db.execute("SELECT document FROM snapshots WHERE project_id=? AND version=?", (project_id, version)).fetchone()
        if not row:
            raise KeyError("Project / version not found")
        return Project.model_validate_json(row[0])

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT document FROM projects ORDER BY rowid DESC").fetchall()
        return [{k: p[k] for k in ("id", "name", "version", "updated_at", "brief")} for (doc,) in rows if (p := json.loads(doc))]

    def history(self, project_id):
        with self.connect() as db:
            rows = db.execute("SELECT document FROM snapshots WHERE project_id=? ORDER BY version DESC", (project_id,)).fetchall()
        return [{k: p[k] for k in ("version", "updated_at", "change_reason")} for (doc,) in rows if (p := json.loads(doc))]

    def put_original(self, project_id: str, content: bytes) -> str:
        self.get(project_id)
        sha = hashlib.sha256(content).hexdigest()
        path = self.original_path(project_id, sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError("Original file integrity mismatch")
        return sha

    def original_path(self, project_id: str, sha: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", project_id) or not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("Invalid file identifier")
        return self.root / "projects" / project_id / "originals" / sha

"""Job records in SQLite. Internal states: queued -> running -> done | failed."""
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

MAX_ATTEMPTS = 2  # a job interrupted by a server restart is retried once

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,              -- 'api' (jury, keyed) or 'ui'
    priority    INTEGER NOT NULL,           -- lower runs first
    status      TEXT NOT NULL,
    progress    REAL NOT NULL DEFAULT 0,
    video_path  TEXT NOT NULL,
    filename    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    result      TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs (status, priority, created_at);
"""


@dataclass
class Job:
    id: str
    source: str
    priority: int
    status: str
    progress: float
    video_path: str
    filename: str
    created_at: float
    started_at: float | None
    finished_at: float | None
    attempts: int
    result: dict | None
    error: str | None


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    @staticmethod
    def _job(row: sqlite3.Row | None) -> Job | None:
        if row is None:
            return None
        d = dict(row)
        d["result"] = json.loads(d["result"]) if d["result"] else None
        return Job(**d)

    def new_id(self) -> str:
        while True:
            job_id = secrets.token_hex(6)
            if self.get(job_id) is None:
                return job_id

    def create(self, job_id: str, source: str, video_path: str, filename: str) -> None:
        self._exec(
            "INSERT INTO jobs (id, source, priority, status, video_path, filename, created_at)"
            " VALUES (?, ?, ?, 'queued', ?, ?, ?)",
            (job_id, source, 0 if source == "api" else 1, video_path, filename, time.time()))

    def get(self, job_id: str) -> Job | None:
        return self._job(self._exec("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def claim_next(self) -> Job | None:
        """Atomically move the oldest queued job (jury jobs first) to running."""
        with self._lock:
            row = self._db.execute(
                "SELECT id FROM jobs WHERE status = 'queued'"
                " ORDER BY priority, created_at LIMIT 1").fetchone()
            if row is None:
                return None
            self._db.execute(
                "UPDATE jobs SET status = 'running', started_at = ?, progress = 0,"
                " attempts = attempts + 1 WHERE id = ?", (time.time(), row["id"]))
            return self._job(self._db.execute(
                "SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())

    def set_progress(self, job_id: str, progress: float) -> None:
        self._exec("UPDATE jobs SET progress = ? WHERE id = ? AND status = 'running'",
                   (min(max(progress, 0.0), 1.0), job_id))

    def finish(self, job_id: str, result: dict) -> None:
        self._exec(
            "UPDATE jobs SET status = 'done', progress = 1, result = ?, finished_at = ?"
            " WHERE id = ?", (json.dumps(result, ensure_ascii=False), time.time(), job_id))

    def fail(self, job_id: str, error: str) -> None:
        self._exec(
            "UPDATE jobs SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            (error, time.time(), job_id))

    def queue_position(self, job: Job) -> int:
        """0 while running; n = jobs that will run before this one, plus one."""
        if job.status != "queued":
            return 0
        ahead = self._exec(
            "SELECT COUNT(*) FROM jobs WHERE status = 'running' OR (status = 'queued' AND"
            " (priority < ? OR (priority = ? AND created_at < ?)))",
            (job.priority, job.priority, job.created_at)).fetchone()[0]
        return ahead + 1

    def pending_count(self) -> int:
        return self._exec(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]

    def recover(self) -> None:
        """After a restart: re-queue interrupted jobs once, fail them the second time."""
        self._exec("UPDATE jobs SET status = 'failed', error = 'interrupted by a server"
                   " restart', finished_at = ? WHERE status = 'running' AND attempts >= ?",
                   (time.time(), MAX_ATTEMPTS))
        self._exec("UPDATE jobs SET status = 'queued', progress = 0 WHERE status = 'running'")

    def close(self) -> None:
        with self._lock:
            self._db.close()

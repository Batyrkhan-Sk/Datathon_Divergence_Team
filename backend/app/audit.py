"""Evidence integrity: HMAC-SHA256 seal on each completed result.

Usage in api.py:
    audit = AuditLog(storage_dir / "audit.db", secret)
    audit.attach(store)              # patches store.finish to auto-seal
    app.include_router(audit.router(store))

GET /ui/api/jobs/{job_id}/audit -> { job_id, digest, verified, ts }
The digest is over json.dumps(result, sort_keys=True), keyed by
HMAC_SECRET env var (falls back to API_KEY).  Any in-place DB edit or
replayed result breaks verification.
"""
import hashlib
import hmac
import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    job_id   TEXT PRIMARY KEY,
    digest   TEXT NOT NULL,
    ts       REAL NOT NULL
);
"""


class AuditLog:
    def __init__(self, db_path: Path, secret: str):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._secret = secret.encode() if secret else b"changeme"
        with self._lock:
            self._db.executescript(_SCHEMA)

    # -- HMAC helpers -------------------------------------------------------

    def _sign(self, job_id: str, result: dict) -> str:
        canon = json.dumps(result, ensure_ascii=False, sort_keys=True)
        msg = f"{job_id}:{canon}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    # -- write --------------------------------------------------------------

    def seal(self, job_id: str, result: dict) -> str:
        """Compute and persist the HMAC. Returns the hex digest."""
        digest = self._sign(job_id, result)
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO audit_log (job_id, digest, ts) VALUES (?, ?, ?)",
                (job_id, digest, time.time()))
        return digest

    # -- read / verify ------------------------------------------------------

    def verify(self, job_id: str, result: dict) -> tuple[bool, str | None, float | None]:
        """Returns (ok, stored_digest, sealed_at). ok=False when absent or mismatched."""
        with self._lock:
            row = self._db.execute(
                "SELECT digest, ts FROM audit_log WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return False, None, None
        stored, ts = row
        expected = self._sign(job_id, result)
        return hmac.compare_digest(stored, expected), stored, ts

    # -- attach to store (monkey-patch) ------------------------------------

    def attach(self, store) -> None:
        """Wrap store.finish so every completed job is automatically sealed."""
        _orig = store.finish

        def _sealing_finish(job_id: str, result: dict) -> None:
            _orig(job_id, result)
            try:
                self.seal(job_id, result)
            except Exception:
                pass  # audit failure must never break job storage

        store.finish = _sealing_finish

    # -- FastAPI router ----------------------------------------------------

    def router(self, store):
        from fastapi import APIRouter, HTTPException
        r = APIRouter()

        @r.get("/ui/api/jobs/{job_id}/audit")
        def audit_endpoint(job_id: str):
            job = store.get(job_id)
            if job is None or job.source != "ui":
                raise HTTPException(404, "job not found")
            if job.status != "done" or not job.result:
                raise HTTPException(409, "job not finished yet")
            ok, digest, ts = self.verify(job_id, job.result)
            return {
                "job_id": job_id,
                "digest": digest,
                "verified": ok,
                "sealed_at": ts,
            }

        return r

    def close(self) -> None:
        with self._lock:
            self._db.close()

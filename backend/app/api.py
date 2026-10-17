"""FastAPI app factory: jury API (X-API-Key), keyless UI API, health, static frontend."""
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException

from ml.video import probe, read_frame_at

from .config import Settings
from .results import render
from .store import Store
from .worker import Supervisor

log = logging.getLogger("backend")
VIDEO_EXTS = {".mov", ".mp4"}
CHUNK = 1 << 20


class RateLimiter:
    """At most `limit` events per `window` seconds per key (sliding window, in memory)."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, hits = time.monotonic(), self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def _client_ip(request: Request) -> str:
    # Behind a Cloudflare tunnel every request comes from localhost.
    h = request.headers
    fwd = h.get("cf-connecting-ip") or h.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (request.client.host if request.client else "unknown")


def _save(src, dest: Path, limit: int) -> int:
    """Copy the upload to disk; returns its size, or -1 as soon as it exceeds `limit`."""
    size = 0
    with dest.open("wb") as out:
        while chunk := src.read(CHUNK):
            size += len(chunk)
            if size > limit:
                return -1
            out.write(chunk)
    return size


def _readable(path: Path) -> bool:
    try:
        info = probe(str(path))
    except ValueError:
        return False
    return info.n_frames > 0 and info.duration > 0 and read_frame_at(str(path), 0.0) is not None


def _cleanup_uploads(uploads: Path, ttl_hours: float) -> None:
    cutoff, removed = time.time() - ttl_hours * 3600, 0
    for f in uploads.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    if removed:
        log.info("removed %d upload(s) older than %.0f h", removed, ttl_hours)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uploads = s.storage_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    store = Store(s.storage_dir / "jobs.db")
    supervisor = Supervisor(store, s.analyzer, s.job_timeout_sec, s.load_timeout_sec)
    ui_limiter = RateLimiter(s.ui_uploads_per_min)
    max_bytes = s.max_upload_mb * 1024 * 1024

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not s.api_key:
            log.warning("API_KEY is not set: every /api/v1 request will be rejected")
        store.recover()
        _cleanup_uploads(uploads, s.upload_ttl_hours)
        supervisor.start()
        log.info("analyzer=%s, job timeout=%.0f s, strict schema=%s",
                 s.analyzer, s.job_timeout_sec, s.strict_schema)
        yield
        supervisor.stop()
        store.close()

    app = FastAPI(title="ForteBank Datathon 26: violation detection API", lifespan=lifespan)
    app.state.settings, app.state.store, app.state.supervisor = s, store, supervisor

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    async def reject(request: Request, code: int, detail: str):
        # Read the body before answering: replying mid-upload makes the server close
        # the socket and many clients then see "connection reset" instead of the error.
        read = 0
        async for chunk in request.stream():
            read += len(chunk)
            if read > max_bytes + CHUNK:
                break
        raise HTTPException(code, detail)

    async def require_key(request: Request) -> None:
        given = request.headers.get("x-api-key", "")
        if not (s.api_key and given and secrets.compare_digest(given.encode(), s.api_key.encode())):
            await reject(request, 401, "missing or invalid X-API-Key header")

    async def submit(request: Request, source: str) -> dict:
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > max_bytes + CHUNK:
            raise HTTPException(413, f"file too large (limit {s.max_upload_mb} MB)")
        if not request.headers.get("content-type", "").startswith("multipart/form-data"):
            await reject(request, 422, "expected multipart/form-data with the video in field 'file'")
        try:
            form = await request.form()
        except MultiPartException as e:
            raise HTTPException(400, f"malformed multipart body: {e.message}")
        try:
            upload = form.get("file")
            if not isinstance(upload, UploadFile):
                raise HTTPException(422, "missing file: send the video in multipart field 'file'")
            ext = Path(upload.filename or "").suffix.lower()
            if ext not in VIDEO_EXTS:
                raise HTTPException(400, f"unsupported file type {ext or '(none)'!r}: expected .mov")
            job_id = store.new_id()
            dest = uploads / f"{job_id}{ext}"
            size = await run_in_threadpool(_save, upload.file, dest, max_bytes)
        finally:
            await form.close()
        if size <= 0:
            dest.unlink(missing_ok=True)
            if size < 0:
                raise HTTPException(413, f"file too large (limit {s.max_upload_mb} MB)")
            raise HTTPException(400, "empty file")
        if not await run_in_threadpool(_readable, dest):
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "cannot decode the video: expected an H.264 .mov file")
        store.create(job_id, source, str(dest), Path(upload.filename).name)
        log.info("job %s queued (%s, %.1f MB)", job_id, source, size / 1e6)
        return {"job_id": job_id, "status": "processing"}

    def job_view(job_id: str, source: str | None = None) -> dict:
        job = store.get(job_id)
        if job is None or (source and job.source != source):
            raise HTTPException(404, f"job {job_id!r} not found")
        return render(job, s.strict_schema, store.queue_position(job))

    # -- jury API ------------------------------------------------------------------
    @app.post("/api/v1/analyze", dependencies=[Depends(require_key)])
    async def analyze(request: Request):
        return await submit(request, "api")

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
    def get_job(job_id: str):
        return JSONResponse(job_view(job_id))

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok", "queue": store.pending_count(), "worker": supervisor.state,
                "analyzer": s.analyzer}

    # -- UI API (no key; the key must never reach the browser) ------------------------
    @app.post("/ui/api/analyze")
    async def ui_analyze(request: Request):
        if not ui_limiter.allow(_client_ip(request)):
            await reject(request, 429, f"too many uploads: at most {s.ui_uploads_per_min} per minute")
        return await submit(request, "ui")

    @app.get("/ui/api/jobs/{job_id}")
    def ui_get_job(job_id: str):
        return JSONResponse(job_view(job_id, source="ui"))

    @app.get("/ui/api/jobs/{job_id}/video")
    def ui_video(job_id: str):
        job = store.get(job_id)
        if job is None or job.source != "ui" or not Path(job.video_path).is_file():
            raise HTTPException(404, "video not found")
        return FileResponse(job.video_path, media_type="video/mp4")

    # Frontend last, so the API routes win.
    if s.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=s.frontend_dir, html=True), name="ui")
    else:
        log.warning("no frontend at %s; serving the API only", s.frontend_dir)

        @app.get("/")
        def root():
            return {"detail": "frontend not installed; API at /api/v1, docs at /docs"}
    return app

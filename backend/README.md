# Backend

FastAPI service around `ml.pipeline.analyze()`: the jury API (key in `X-API-Key`), a
keyless API for the web UI, and the static frontend. Uploads go to a queue; **one
persistent worker process** loads the analyzer (models) once and runs jobs one at a time
(one GPU). Jobs and uploads persist in `backend/storage/` (SQLite + files), so results
survive a restart.

```
backend/
  app/main.py        ASGI entry point (app = create_app())
  app/api.py         routes, auth, upload validation, rate limit, static files
  app/worker.py      worker process + supervisor (timeout, crash restart)
  app/analyzers.py   real / demo analyzers
  app/results.py     output normalisation (contract guarantees) and rendering
  app/store.py       job records (SQLite)
  app/config.py      settings from env / .env
  check_api_contract.py   jury-flow checker against a running server
  tests/             pytest suite
```

## Run

From the repo root, with the venv (`pip install -r requirements.txt -r backend/requirements.txt`):

```bash
# .env in the repo root (gitignored), e.g.:  API_KEY=<long random string>
python -c "import secrets; print(secrets.token_urlsafe(24))"     # make a key

uvicorn backend.app.main:app --host 0.0.0.0 --port 8000            # or: python -m backend
```

Run a single uvicorn process (no `--workers`, no `--reload`): the job queue lives in it.

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | (none) | Key for `/api/v1/*`. If unset, every keyed request gets 401. |
| `ANALYZER` | `real` | `real` = `ml.pipeline.analyze`; `demo` = fake violations with real frames (for UI work); or `module:function` |
| `JOB_TIMEOUT_SEC` | `240` | Hard limit per job; past it the job is `failed` and the worker is restarted |
| `LOAD_TIMEOUT_SEC` | `600` | Limit for the worker to load the analyzer (models) |
| `STRICT_SCHEMA` | `0` | `1` = output only the documented keys (no `type_id`, `confidence`, `rule`, `processing_sec`, `progress`, `error`) |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | For `python -m backend` |
| `MAX_UPLOAD_MB` | `300` | Larger uploads get 413 |
| `UI_UPLOADS_PER_MIN` | `5` | Per-IP upload limit for the keyless UI API |
| `STORAGE_DIR` | `backend/storage` | Job DB and uploads; uploads older than 24 h are deleted on start |

Public URL (not set up here): `cloudflared tunnel --url http://localhost:8000`, then give the
jury the `https://….trycloudflare.com` URL and the key.

## Endpoints

| Method | Path | Key | |
|---|---|---|---|
| `POST` | `/api/v1/analyze` | yes | multipart field `file` (`.mov`, also `.mp4`) → `{"job_id", "status": "processing"}` |
| `GET` | `/api/v1/jobs/{job_id}` | yes | status and result |
| `GET` | `/api/v1/health` | no | `{"status": "ok", "queue": n, "worker": "alive"\|"loading"\|"restarting", "analyzer"}` |
| `POST` | `/ui/api/analyze` | no | same as the jury endpoint, rate-limited per IP (429) |
| `GET` | `/ui/api/jobs/{job_id}` | no | same body; only jobs created through the UI |
| `GET` | `/ui/api/jobs/{job_id}/video` | no | the uploaded video (range requests), for the player |
| `GET` | `/` | no | `frontend/` (static), if present |

```bash
curl -X POST http://localhost:8000/api/v1/analyze -H "X-API-Key: $KEY" -F "file=@data/raw/X-26.mov"
curl http://localhost:8000/api/v1/jobs/3f2a9c1e1b2c -H "X-API-Key: $KEY"
```

Errors are JSON `{"detail": "..."}`: 401 bad/missing key, 404 unknown job, 400 wrong
extension / empty / undecodable video, 413 too large, 422 not multipart or no `file`
field, 429 UI rate limit.

### Job response

```jsonc
// processing (queued or running)
{"job_id": "…", "status": "processing", "verdict": null, "violations": [], "progress": 0.4, "queue_position": 0}
// failed
{"job_id": "…", "status": "failed", "verdict": null, "violations": [], "error": "timeout: processing exceeded 240 s"}
// done: documented keys first, extras after
{"job_id": "…", "status": "done", "verdict": "violation",
 "violations": [{"type": "…", "timecode_sec": 44.2, "description": "…",
                 "evidence_frames": [{"timestamp_sec": 44.2, "image_base64": "/9j/…"}],
                 "type_id": "cash_unattended", "confidence": 0.82,
                 "rule": {"document": "…", "clause": "…", "quote": "…", "url": "https://adilet…"}}],
 "processing_sec": 31.5}
```

Whatever the analyzer returns, the worker normalises it: `verdict` is `violation` iff
`violations` is non-empty; each violation has a non-empty `type` and `description`,
`timecode_sec` within [0, duration], and 1–3 evidence frames as raw base64 JPEG (missing
frames are extracted from the video at the timecode; extra ones are dropped).

## Tests

```bash
.venv/Scripts/python -m pytest backend/tests -v          # ~1 min, needs data/raw/X-26.mov, X-29.mov
```

Contract check against a running server, exactly like the jury (POST with field `file`,
poll every 2 s, 5-minute limit), optionally with N concurrent videos:

```bash
python backend/check_api_contract.py --base-url http://localhost:8000 --key $KEY \
    --video data/raw/X-26.mov --video data/raw/X-29.mov --concurrent 5
```

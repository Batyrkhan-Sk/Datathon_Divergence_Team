# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup (Python 3.11 required)
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r backend/requirements.txt
.venv/Scripts/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv/Scripts/python -m pip install -r requirements-ml.txt

# Run backend (create .env with API_KEY=... first)
python -m backend                         # or: uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# Run frontend in mock mode (no backend needed)
python -m http.server 8090 --directory frontend
# http://127.0.0.1:8090/?mock=1

# Analyse one video
python -m ml.pipeline data/raw/X-26.mov

# Run all backend tests (~1 min, needs data/raw/X-26.mov and X-29.mov)
.venv/Scripts/python -m pytest backend/tests -v

# Check jury API contract against a running server
python backend/check_api_contract.py --base-url http://localhost:8000 --key $KEY \
    --video data/raw/X-26.mov --concurrent 5

# Evaluate pipeline on training videos
python -m eval.run_eval --tag my-change
# Subset: --layouts D E   or   --videos X-26 X-29

# Cache video frames at 4 fps (run once after copying data)
python tools/extract_frames.py data/raw data/frames 4

# Contact sheets for all videos
python tools/contact_sheets.py data/raw data/open_labels.xlsx out/sheets

# Dense zoom on a segment: video t0 t1 step x0 y0 x1 y1 (fractions) out.jpg
python tools/zoom.py data/raw/X-1.mov 19 24 0.5 0 0.3 0.7 0.6 out/zoom/X-1.jpg
```

## Architecture

The service is split into three layers that communicate through one contract: `ml.pipeline.analyze(video_path) -> dict`.

```
frontend/   Plain HTML/CSS/JS, no build step. Served by the backend at /.
            Uses /ui/api/* (keyless, rate-limited) for the web flow and
            URL.createObjectURL for local video playback.

backend/    FastAPI. Two API surfaces:
            - /api/v1/*   — jury API, requires X-API-Key header
            - /ui/api/*   — same logic, no key, per-IP rate limit
            One persistent worker process holds the models and runs jobs
            one at a time. Jobs and uploads live in backend/storage/
            (SQLite + files). Output is normalised in app/results.py
            (verdict matches violations; 1–3 JPEG frames guaranteed).

ml/         The analysis pipeline.
            pipeline.py   orchestrates: sample frames → run detectors →
                          merge events → build violations dict
            detectors/    one module per violation type; each exports
                          detect(ctx) -> list[Event] and self-registers
                          with @register("<type_id>")
            video.py      PyAV/OpenCV decoding with exact timestamps
            evidence.py   JPEG evidence frames (base64, optional boxes)
            catalog.py    reads data/rules.json for names and citations
```

**Adding a detector:** create `ml/detectors/<type_id>.py`, decorate the function with `@register("<type_id>")`, then import it at the bottom of `ml/detectors/__init__.py`. The `type_id` must exist in `data/rules.json` before the detector is used.

**`data/rules.json` is the single source of truth** for violation types and legal citations. The pipeline copies citations from it verbatim — it never generates legal text. Every violation type has an `id`, a Russian `name`, an `observable` description (the detector spec), and `sources[]` pointing to clauses of one of three RK acts (НБРК No. 231, НБРК No. 14, АРРФР No. 53).

## Environment variables (`.env` in repo root)

| Variable | Default | Notes |
|---|---|---|
| `API_KEY` | (none) | Required; every `/api/v1/*` request without it gets 401 |
| `ANALYZER` | `real` | `demo` uses fake violations with real frames (for UI dev) |
| `JOB_TIMEOUT_SEC` | `240` | Hard kill per job |
| `STRICT_SCHEMA` | `0` | `1` strips `type_id`, `confidence`, `rule`, `processing_sec` from output |
| `STORAGE_DIR` | `backend/storage` | SQLite DB + uploaded files |

## Key constraints

- **No cloud AI, ever.** No OpenAI / Gemini / Claude API calls in the analysis path — immediate disqualification.
- **No AGPL models.** Ultralytics YOLOv5/v8/v11 are AGPL-3.0; do not use them. Apache-2.0 / MIT / BSD only.
- **No face recognition.** Analysis is strictly visual and positional.
- **No invented citations.** All legal text comes from `data/rules.json`; verify every clause on adilet.zan.kz before submission.
- **5-minute limit per video.** The queue is sequential; 5 concurrent jury videos must all finish within 5 min.

## Data (not in git)

Copy training videos from the team drive into `data/raw/`. Rename Cyrillic `Х-` filenames to Latin `X-` (the organisers mix both). Run `tools/extract_frames.py` once to populate `data/frames/` at 4 fps.

## Public URL

```bash
cloudflared tunnel --url http://localhost:8000
# share the https://….trycloudflare.com URL and the API_KEY with the jury
```

Run a **single** uvicorn process (no `--workers`, no `--reload`) — the job queue lives inside the process.

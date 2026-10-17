# ForteBank Datathon 26: cash-discipline violation detection

An AI service that analyses video of a bank teller's workplace. For each video it
reports whether there are visible signs of possible violations of cash-handling
procedures. Each finding comes with a type, a timecode, evidence frames, a short
explanation, and a reference to the relevant regulation of the Republic of Kazakhstan.

The result is a hint for a human reviewer, not a legal conclusion.

## Project status

*Last updated: 2026-10-17, after backend and frontend were built; feasibility test in
progress. This section is updated after every step.*

### Done
| Area | Result | Where |
|---|---|---|
| Case analysis | Requirements, scoring and constraints summarised | `docs/internal/PLAN.md` §1 |
| Data | 42 training videos: 22 violations, 20 clean, all 464×848 at ~30 fps. Names normalised; frames cached at 4 fps (5,797 frames) | `data/raw/`, `data/frames/` (not in git) |
| Violation types | 9 types defined; **18 of 22** violation videos typed with confidence | `docs/internal/step1_findings.md` |
| Legal mapping | Each type mapped to clauses of 3 RK acts (НБРК No. 231, НБРК No. 14, АРРФР No. 53), with verbatim quotes | `data/rules.json`, `docs/internal/legal_mapping.md` |
| Labels | One table: verdict, timestamp, type, type confidence, room layout (**A–E**, 5 setups) | `data/labels.csv` |
| Pipeline skeleton | `analyze()` returns the exact API format, with evidence frames and citations. Detectors plug into `ml/detectors/` | `ml/` |
| Evaluation | Misses, false alarms, timecode error, type accuracy and runtime, per video and per layout. Scoring checked with a synthetic oracle | `eval/run_eval.py` |
| Baseline | Empty pipeline: recall 0 / 22, false alarms 0 / 20, ~0.5 s per video | `out/eval/*-empty-baseline.json` |
| **Backend** | FastAPI. Jury API exactly per the case (`POST /api/v1/analyze`, `GET /api/v1/jobs/{id}`, `X-API-Key` → 401 otherwise); keyless UI routes `/ui/api/...` with a rate limit. One persistent GPU worker plus a queue, a 240 s hard timeout per job, SQLite store, `ANALYZER=real\|demo`, `STRICT_SCHEMA=1` to strip extras. Output repaired defensively (verdict matches violations; 1–3 JPEG frames). **27/27 tests pass; jury contract checker PASS** (incl. 5 concurrent uploads) | `backend/` (see `backend/README.md`) |
| **Frontend** | Plain HTML/JS/CSS, no build, works offline, Russian UI. Upload → progress → verdict banner → violation cards (type, timecode, description, rule with adilet link, evidence frames with lightbox) → video player with timeline markers. Mock mode `?mock=1`. Tested in headless Chrome, desktop and mobile | `frontend/` (see `frontend/README.md`) |
| Integration | Backend serves the UI at `/`. UI flow and jury contract checker verified end to end (demo analyzer) | — |

### Next
| # | Task | Owner | Why |
|---|---|---|---|
| 1 | **Feasibility test** *(in progress)*: which objects off-the-shelf models see reliably; speed and memory on a 4 GB GPU | ML | Decides the model set and whether we must fine-tune |
| 2 | First detectors, in order of value: `unauthorized_access`, `cash_unattended`, `safe_left_open`, `workstation_unlocked`, `personal_items` | ML | Covers 16 of 22 violation videos |
| 3 | Pipeline fixes from the backend review: add `ml.pipeline.warmup()` (load models at worker start); stream frames instead of `list(iter_frames(...))` (~670 MB RAM for a 143 s video); make `evidence.frames_for` never return 0 frames | ML | Startup time, memory, robustness |
| 4 | **Time budget:** ≤ ~50 s per video including 143 s clips. The queue runs jobs one at a time, so the 5th of 5 concurrent jury videos waits for the other four | ML | 5-min limit per video |
| 5 | Leave-one-layout-out evaluation, plus simulated camera angles (perspective warp, flip, zoom) on the training videos | ML | Honest estimate for the new camera angle |
| 6 | Create the jury `API_KEY` in a root `.env`; public URL via Cloudflare Tunnel; final load test on the real pipeline | Backend | Jury access; 5-min limit under load |

**Open questions**
- Violation types are unknown or uncertain for X-1, X-2, X-13, X-44 and X-17.
- `workstation_unlocked` has only an indirect legal source so far.
- The date of the 12:00 deadline has not been confirmed.

### Model recommendations
*Pre-feasibility: these are candidates, chosen for licence, size and fit with a 4 GB
GPU. The feasibility test will confirm or replace them.*

| Job | First choice | Alternatives | Licence | Notes |
|---|---|---|---|---|
| People detection | RT-DETR-R18 (HF `transformers`) | D-FINE-S, YOLOX-S | Apache-2.0 | Pre-trained COCO `person` is enough; no training needed |
| Tracking | ByteTrack | OC-SORT | MIT | Tells the teller, client and outsiders apart over time (no faces) |
| Hands / pose | RTMPose-s | — | Apache-2.0 | Hand position at the safe, laptop, cash or counting machine |
| Scene objects, zero-shot | OWLv2 | Grounding DINO-T, Florence-2 (MIT) | Apache-2.0 | Text-prompted: safe, door, laptop, counting machine, bag, coat, cup, phone. Used to find zones in each video |
| **Fine-tune if zero-shot is weak** | **RT-DETR-R18 or D-FINE-S** trained on our frames | RF-DETR-S, YOLOX-S | Apache-2.0 | Small objects: banknotes, coin rolls, cash bag, key in lock. Label ~300–500 frames from `data/frames/` with CVAT or Label Studio (both run locally) |
| **State classifiers** | **MobileNetV3 / EfficientNet-B0** on crops (torchvision) | — | BSD-3 | Cheapest way to read states: safe door open/closed, laptop screen on/locked, cash on desk yes/no. ~100–200 labelled crops per state |
| Verification / unseen types | Qwen3-VL-2B *(verify licence)* | SmolVLM2-2.2B, Moondream2, Florence-2 | Apache-2.0 / MIT | Yes/no questions on crops around candidate events only. Keeps within 4 GB and the time budget |

**Do not use**
- Ultralytics YOLOv5/v8/v11: AGPL-3.0.
- Qwen2.5-VL-3B: research licence, not for commercial use.
- Any cloud API: disqualification.

**Training recommendation:** do not train one end-to-end video model; 42 clips are far
too few, and it would not survive a new camera angle. Use pre-trained detectors as they
are, and fine-tune only small parts: a detector for cash-type objects and crop
classifiers for states. Hold out one layout per round.

## Principles
- **Fully local.** All models run inside the service. No cloud AI APIs are used, and no
  video, frames or descriptions leave the machine. After the model weights are
  downloaded, the service works offline.
- **Open-source models only,** under licences that allow commercial use.
- **Visual facts only.** No audio, and no face recognition or identification.

## API

Every request needs an `X-API-Key` header.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/analyze` | Upload a `.mov` file in field `file`. Returns `job_id`. |
| `GET` | `/api/v1/jobs/{job_id}` | Returns `status` (`processing` / `done` / `failed`) and the result. |

```bash
curl -X POST https://<host>/api/v1/analyze -H "X-API-Key: <key>" -F "file=@video.mov"
```

## Repository layout

```
backend/    API, job queue, GPU worker; run: python -m backend  (see backend/README.md)
frontend/   upload and result UI, served by the backend at /  (see frontend/README.md)
ml/         video analysis pipeline
  pipeline.py    analyze(video_path) -> result dict in the API format
  detectors/     one module per violation type (register with @register)
  video.py       decoding / sampling with exact timestamps
  evidence.py    evidence frames (JPEG, base64, boxes drawn)
  catalog.py     violation types and legal citations from data/rules.json
eval/       evaluation on the labelled training set
tools/      data utilities (frame cache, contact sheets, zoom)
docs/       documentation
```

### For backend: the ML contract

```python
from ml.pipeline import analyze
result = analyze("video.mov", progress=lambda p: ...)   # p in 0..1
# {"verdict": "violation"|"no_violation",
#  "violations": [{"type", "type_id", "timecode_sec", "confidence", "description",
#                  "rule": {"document", "clause", "quote", "url"},
#                  "evidence_frames": [{"timestamp_sec", "image_base64"}]}],
#  "processing_sec": float}
```

### `data/rules.json`: violation catalogue and legal citations

The single source of truth for violation types and the regulations behind them. The
service copies citations from it and **never generates legal text**, which protects the
rule-grounding score.

- `_meta.documents`: the 3 RK acts used (НБРК No. 231, НБРК No. 14, АРРФР No. 53), each
  with `title`, `act` and an adilet `url`.
- `types[]`: one entry per violation type:
  - `id`: e.g. `cash_unattended`; detectors emit this as `Event.type_id`
  - `name`: the Russian display name, returned as `type` in the API
  - `observable`: what must be *visible* on video for this type (the detector spec)
  - `sources[]`: `doc` key, `clause`, verbatim `quote`; the first source is the one the API returns
  - `interpretation`: how the clause applies, and what must not be claimed
  - `legal_confidence`: `direct` / `interpretation` / `indirect`
  - `train_examples`: training videos as `X-26@9` (`?` = type not confirmed)
- `_meta.unresolved_train_examples`, `_meta.ruled_out`: open cases and rejected ideas.

**Who uses what**
- **ML:** `id`, `observable`, `train_examples`. Adding a new type means adding an entry here first.
- **Backend:** nothing directly; `ml.catalog` resolves names and citations.
- **Frontend:** the `rule` object in the API response (`document`, `clause`, `quote`, `url`).
- **Everyone:** before submission, open each `url` and check the clause numbers and quotes
  against adilet.zan.kz.

### For ML: adding a detector

Create `ml/detectors/<type>.py` with a function `detect(ctx) -> list[Event]`
decorated with `@register("<type>")`, and import it in `ml/detectors/__init__.py`.
`ctx.frames` holds sampled `(t_sec, frame)` pairs at 4 fps. `Event` needs a `type_id`
that exists in `data/rules.json`, the onset time, a confidence, and a plain-language
`observation` of what is visible.

## Setup (development)

Requires Python 3.11.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS

# backend
.venv/Scripts/python -m pip install -r backend/requirements.txt
# ML (models): PyTorch with CUDA first, then the rest (see requirements-ml.txt)
.venv/Scripts/python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
.venv/Scripts/python -m pip install -r requirements-ml.txt
```

| Path | What | Source |
|---|---|---|
| `data/raw/X-<n>.mov` | training videos, names normalised to Latin `X` | **team drive** (not in git) |
| `data/frames/` | frames cached at 4 fps | build with `tools/extract_frames.py` |
| `data/open_labels.xlsx` | organisers' labels | in repo |
| `data/labels.csv` | our labels: verdict, timestamp, type, room layout (A–E) | in repo |
| `data/rules.json` | violation types and legal citations (needed by the pipeline) | in repo |

Copy the videos from the team drive into `data/raw/`. Rename Cyrillic `Х-` to Latin `X-`
(the organisers' files mix both).

Common commands (run from the repo root):

```bash
# analyse one video, print the result JSON
python -m ml.pipeline data/raw/X-26.mov

# evaluate on all labelled videos (or --layouts D E / --videos X-26 X-29)
python -m eval.run_eval --tag my-change

# cache frames at 4 fps -> data/frames/<video>/ (run once)
python tools/extract_frames.py data/raw data/frames 4
```

Exploration tools:

```bash
# contact sheets for every video → out/sheets/
python tools/contact_sheets.py data/raw data/open_labels.xlsx out/sheets

# dense zoomed sheet for one segment: video t0 t1 step x0 y0 x1 y1 (fractions) out.jpg
python tools/zoom.py data/raw/X-1.mov 19 24 0.5 0 0.3 0.7 0.6 out/zoom/X-1.jpg
```

## Team

| Role | Area |
|---|---|
| ML engineer | video analysis pipeline, models, evaluation |
| Backend engineer | API, job processing, deployment |
| Frontend engineer | user interface |

Start with `docs/internal/PLAN.md`: architecture, task split, milestones, risks.
Analysis notes are in `docs/internal/step1_findings.md`, and the regulation mapping is in
`docs/internal/legal_mapping.md` and `data/rules.json`.

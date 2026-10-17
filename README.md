# ForteBank Datathon 26: cash-discipline violation detection

An AI service that analyses video of a bank teller's workplace. For each video it
reports whether there are visible signs of possible violations of cash-handling
procedures. Each finding comes with a type, a timecode, evidence frames, a short
explanation, and a reference to the relevant regulation of the Republic of Kazakhstan.

The result is a hint for a human reviewer, not a legal conclusion.

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
backend/    API, job queue, worker            (planned)
frontend/   upload and result UI              (planned)
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

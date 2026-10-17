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
ml/         video analysis pipeline           (planned)
eval/       evaluation on the training set    (planned)
tools/      data exploration utilities
docs/       documentation
```

## Setup (development)

Requires Python 3.11.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS
```

Put the training videos in `data/raw/` with names normalised to `X-<n>.mov` (Latin `X`)
and the label file at `data/open_labels.xlsx`. Data is not part of the repository.

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

The internal plan, analysis notes and regulation mapping live in `docs/internal/` and
`data/rules.json`. They are excluded from git and shared inside the team separately.

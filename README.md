# ForteBank Datathon 26: cash-discipline violation detection

An AI service that analyses video of a bank teller's workplace. For each video it
reports whether there are visible signs of possible violations of cash-handling
procedures. Each finding comes with a type, a timecode, evidence frames, a short
explanation, and a reference to the relevant regulation of the Republic of Kazakhstan.

The result is a hint for a human reviewer, not a legal conclusion.

## Project status

*Last updated: 2026-10-18, after v19 (frame timestamps fix from the format stress test; deployed at the fixed ngrok URL). Presentation draft: claude.ai artifact (English). **Deadline:
2026-10-18 12:00.** This section is updated after every step.*

**Current score (`eval/run_eval.py`, tag `v12`, GPU server, VLM on; LIVE):** recall
**15/22**, false alarms **0/20** (unique videos: 14/21 caught, 0/19 false; accuracy 82.5%,
precision 100%). Timecodes **73%** within 2 s (5.1 s mean), type accuracy **79%**, runtime
**6.7 s average / 21 s worst** per video. v12 vs v10: departure onset uses the last moment at
the workstation for a standing teller (X-11 18.5 s, X-15 15.0 s); crowd onset = entry complete
(X-18 18 s). Tried and dropped: "person enters while cash on desk" (4 false alarms: cash on
the desk during normal client service). For comparison, another team's best end-to-end
VLM (35B) reached 60% accuracy. v10 vs v8: X-17 now typed as the cash collector's bag (not
personal items), X-33 timecode fixed (teller arrival onset), short act names in descriptions,
type names limited to what is visible. Submission document: `docs/SUBMISSION.md`.

| Version | Caught | False alarms |
|---|---|---|
| Laptop v5 (detectors) | 11/22 | 0/20 |
| Server, detectors only | 12/22 | 0/20 |
| v6: + VLM safe and key | 15/22 | 2/20 (key rule) |
| v7: key rule off, + coat/bag | 15/22 | 2/20 (coat/bag too loose) |
| v8: coat/bag tightened | 15/22 | 0/20 |
| v10: cash bag, arrival onset | 15/22 | 0/20 (type acc 64%) |
| v11: + entry-with-cash detector | 15/22 | **4/20** → dropped |
| v12: timecode fixes | 15/22 | 0/20 (type acc 79%, 73% within 2 s) |
| v13: robustness fixes | **15/22** | **0/20**; simulated camera changes (`tools/augment_videos.py`): mirror/tilt/zoom 12/22 with 0 FA (v12 had 1 FA each), low-quality camera 7/22, 0 FA |
| v14: + scene overlay and downloadable report | 15/22 | 0/20 (detections unchanged; 27/27 backend tests) |
| v15: cup must not be banknotes (wide-crop VLM check) | 13/22 | 0/20; type acc 92%, 85% of timecodes within 2 s. X-4/X-47 no longer flagged: they were only caught via a rolled banknote bundle taken for a cup |
| v16: workplace fallback + merge window 8 s | 13/22 | 0/20; all 4 camera variants unchanged with 0 FA. If no laptop is visible (new angle), the workplace is taken from where the teller sits most of the time; simulated "laptop hidden" run: **10/22, 0/20** (before: the departure, cash and belongings checks were off without a laptop). Money needs score ≥ 0.15 in that mode (first try: 1 FA on X-23 at 0.09). X-46 now one episode instead of two |
| v17: UI polish + checklist | 13/22 | 0/20 (detections unchanged). Compact verdict, disclaimer as a hover tooltip, new icon, timeline removed, the frame viewer plays the moment in place. «Как сервис понял сцену» replaced by «Что проверил сервис» (`ml/checks.py`, extra `checks` field): found / not found / not checked with the reason per type; scene photo (boxes only) collapsed under it |
| v18: adilet deep links | 13/22 | 0/20 (detections unchanged). Rule links open adilet scrolled to the cited clause with it highlighted (text fragment `#:~:text=`, `ml/catalog.deep_link`; checked for all 9 types in Chrome). Timecode buttons play from the timecode; footer and «О результате» label removed (ⓘ tooltip kept) |
| **v19 (LIVE): real frame timestamps** | **13/22** | **0/20**; timecodes within 2 s 85% → **92%**. Format stress test (15 variants via the API: HEVC, rotation flag, variable fps, 60 fps, 1080p, 4K 12 s, landscape, 4-min video 34 s, .mp4, Cyrillic name, 3 s clip): all processed, same verdict and type. Found: variable frame rate shifted timecodes (10.0 → 6.5 s); fixed by sampling on frame timestamps (`ml/video.py`), duration from ffprobe |

Missed: X-22, X-13 (key left in safe: too small to see), X-32 (door left open), X-34
(client absent), X-1, X-2, X-44 (types unclear). Timecodes of unauthorized_access are ~4–5 s
off (X-18, X-33, X-38), which costs type accuracy. X-4/X-47 are flagged via a cup at 35 s
(right verdict, wrong type).

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
| Feasibility, detectors | **RT-DETR v2** chosen for people and laptops (best quality, fastest); OWLv2 for text-prompted checks on crops; Grounding DINO rejected (too slow). No detector finds the safe or a key | `docs/internal/feasibility.md` |
| **First detectors** | `ml/detectors/workplace.py`: teller leaves (stand-up / walk-off onset) → **cash_unattended** (OWLv2 money on desk crop, at desk height, ≥ 2 frames) and **workstation_unlocked** (screen still shows the bright bluish-white app). `ml/detectors/crowd.py`: **≥ 3 people for ≥ 5 s**, or a **second person entering a solo room** (median count 1, stays ≥ 4 s, or ≥ 2.5 s if until video end) → unauthorized_access. `ml/detectors/personal_items.py`: cup/bottle ≥ 2 s that is either confident (≥ 0.55) or moving → personal_items. People seen through or reflected in the glass are filtered by size and position | `ml/` |
| **GPU server** | Team Jupyter server, 2× RTX A6000 (48 GB). Project at `~/work/forte_datathon` (Jupyter: `forte_datathon/`) with its own env `env/`, models in `hf_cache/`, logs in `logs/`. Nothing outside that folder is touched (other projects live there). RT-DETR runs at 0.017 s/frame there, ~11× the laptop | `forte_datathon/` on the server |
| VLM result (2B) | Qwen3-VL-2B 4-bit passed only **6/16** state checks (never saw the key, rarely the cash) → moving to **Qwen3-VL-8B** on the server, on zoomed crops. `ml/perception/vlm.py` picks 8B on a big GPU, 2B in 4-bit on a small one; includes `p_yes`, `locate` (bounding box) and `describe` | `ml/perception/vlm.py` |
| VLM result (8B) | Qwen3-VL-8B (bf16, GPU server): **12/16** checks, 0.17 s per question, 16.5 GB. Full-frame answers are noisy (confuses the open room door with the safe door), so all VLM use is on **crops** with multi-sample consistency | `out/feasibility/qwen3vl8b/` (server) |
| Safe detector (VLM) | `ml/detectors/safe.py`: VLM locates the safe once, then every 2 s asks "door open?" on an enlarged crop. **Open ≥ 6 s** → safe_left_open (X-20 caught at 4 s vs label 5 s, no false alarms). **Key left in the lock is not detectable**: a few pixels; single and before/after questions failed, and the behaviour rule also fired on clean X-12/X-25, so it is off (`ML_SAFE_KEY_RULE=1` to enable) | `ml/detectors/safe.py` |
| Coat/bag on desk (VLM) | `personal_items.py`: VLM on the desk crop every 3 s; item must be absent at the start and then seen with p ≥ 0.9 for ≥ 3 samples (or ≥ 2 until the end). Catches X-40 (and the cash bag in X-17), no false alarms | `ml/detectors/personal_items.py` |
| **Deployment (LIVE)** | Service on the GPU server (GPU 1, VLM on, offline weights, localhost only) at the **fixed ngrok address https://eggbeater-stardom-unsaid.ngrok-free.dev** (UI at `/`, API at `/api/v1/...`; Cloudflare quick tunnel kept as a backup, its current URL in the server's `logs/public_url.txt`). The jury API key is only in the server's project `.env` (ask the team lead). **Jury contract checker PASS over the public URL** (X-26 → violation in 14.5 s, X-29 → no_violation in 7.4 s). The quick-tunnel URL changes if the tunnel restarts | `deploy/`, server `logs/service.log`, `logs/tunnel.log` |
| Dev tooling | `eval/cache_detections.py` caches RT-DETR detections; `ML_OBJECTS_CACHE=out/cache/objects python -m eval.run_eval` reuses them, so a full evaluation takes about 3 min instead of 15 | `eval/` |
| Data findings | **X-4 = X-47 and X-5 = X-48 are identical files** (40 unique videos; X-4 holds 2 violations at 57 s and 68 s). Labels mark the moment the teller *gets up*, not when she leaves the room | `data/labels.csv` (`duplicate_of`) |

### Next
| # | Task | Owner | Why |
|---|---|---|---|
| 1 | **More detectors** for the missed videos: X-38 (3 people; the crowd rule misses it), X-4 (person enters while cash on desk, layout A), X-32 (door left open), X-40 (coat and bag on desk: OWLv2 on desk crop), X-20/X-22 (safe: needs VLM), X-34 (client leaves, cash processed), X-47 (hand counting). Also merge same-type events further apart than 3 s (X-46 reports 2) | ML | Recall is 11/22 |
| 2 | VLM (Qwen3-VL-2B, 4-bit) test and integration: safe / key / cash states, unseen-type checklist, describe the 5 unresolved clips. Weights are downloading slowly (`weights/qwen3-vl-2b/`) | ML | Types no detector can see |
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

# ForteBank Datathon 26: cash-discipline violation detection

An AI service that analyses video of a bank teller's workplace. For each video it
reports whether there are visible signs of possible violations of cash-handling
procedures. Each finding comes with a type, a timecode, evidence frames, a short
explanation, and a reference to the relevant regulation of the Republic of Kazakhstan.

The result is a hint for a human reviewer, not a legal conclusion.

**Live service:** https://eggbeater-stardom-unsaid.ngrok-free.dev — web UI at `/`, jury API at
`/api/v1/analyze` and `/api/v1/jobs/{id}` (header `X-API-Key`). Details: `docs/SUBMISSION.md`.

## Project status

**Current score (`eval/run_eval.py`, v21, GPU server, VLM on; LIVE):** recall **13/22**, false alarms **0/20** (unique videos: 13/21 caught, 0/19 false; accuracy 80%, precision 100%). Timecodes **92%** within 2 s, type accuracy **92%**, about 7 s per video (max 22 s). Submission document: `docs/SUBMISSION.md`.

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
| v19: real frame timestamps | 13/22 | 0/20; timecodes within 2 s 85% → **92%**. Format stress test (15 variants via the API: HEVC, rotation flag, variable fps, 60 fps, 1080p, 4K 12 s, landscape, 4-min video 34 s, .mp4, Cyrillic name, 3 s clip): all processed, same verdict and type. Found: variable frame rate shifted timecodes (10.0 → 6.5 s); fixed by sampling on frame timestamps (`ml/video.py`), duration from ffprobe |
| v20: legal and wording fixes (teammate review, verified first) | 13/22 | 0/20 (detections unchanged). `workstation_unlocked` now cites АРРФР № 53 п. 26 подп. 1) and п. 53 (п. 71 only as context); НБРК № 14 п. 16 marked as the temporary edition until 01.01.2027; X-33 text says only what the frame shows; adilet deep links can use an `anchor` per source |
| **v21 (LIVE): external-video check** | **13/22** | **0/20** (eval unchanged). 13 outside clips through the service, no tuning: Edinburgh Office Monitoring (4 real office CCTV excerpts, 90–120 s), 7 Mixkit stock clips (bank desk, checkouts, pharmacy, meeting, safe-deposit boxes, counting machine), 2 public-domain Wikimedia Commons clips (VP9 CCTV, 4K AV1 bodycam, 4 min in 46 s). No crashes, all within the limit. Alarms match the rules: crowd of 3+ people (shop checkout, meeting, bodycam), a real cup on the desk, papers on the desk when the person left (open-vocabulary cash detector cannot tell papers from banknotes). Fixed: same-type episodes now merged by gap from the previous end (one cup was reported twice), crowd text gives the typical count, not one frame's. Camera variants re-run: mirror 12/22, tilt 12/22, zoom 10/22, lower quality 7/22, laptop hidden 10/22, same recall as v16; 0 false alarms except 1 on tilted X-12 (cup, 12 s). Traced to v19 frame sampling (v18 sampling: no alarm; v20 code without the v21 fixes: same alarm), not changed: v19 fixes real timecode drift. Model weights: `deploy/download_models.sh` (tested on an empty cache); 27/27 backend tests |

Missed: X-22, X-13 (key left in safe: too small to see), X-32 (door left open), X-34
(client absent), X-1, X-44, X-4 = X-47 (counting cash by hand), X-2 (type unclear).

### Done
| Area | Result | Where |
|---|---|---|
| Case analysis | Requirements, scoring and constraints summarised | `docs/internal/PLAN.md` §1 |
| Data | 42 training videos = 40 unique (X-47 = X-4, X-48 = X-5): 21 with a violation, 19 clean, all 464×848 at ~30 fps. Names normalised; frames cached at 4 fps (5,797 frames) | `data/raw/`, `data/frames/` (not in git) |
| Violation types | 9 types defined; types of X-1, X-2, X-13, X-17, X-44 remain uncertain (X-1 and X-44 do use the counting machine, so not «без машинки») | `docs/internal/step1_findings.md` |
| Legal mapping | Each type mapped to clauses of 3 RK acts (НБРК No. 231, НБРК No. 14, АРРФР No. 53), with verbatim quotes | `data/rules.json`, `docs/internal/legal_mapping.md` |
| Labels | One table: verdict, timestamp, type, type confidence, room layout (**A–E**, 5 setups) | `data/labels.csv` |
| Pipeline skeleton | `analyze()` returns the exact API format, with evidence frames and citations. Detectors plug into `ml/detectors/` | `ml/` |
| Evaluation | Misses, false alarms, timecode error, type accuracy and runtime, per video and per layout. Scoring checked with a synthetic oracle | `eval/run_eval.py` |
| Baseline | Empty pipeline: recall 0 / 22, false alarms 0 / 20, ~0.5 s per video | `out/eval/*-empty-baseline.json` |
| **Backend** | FastAPI. Jury API exactly per the case (`POST /api/v1/analyze`, `GET /api/v1/jobs/{id}`, `X-API-Key` → 401 otherwise); keyless UI routes `/ui/api/...` with a rate limit. One persistent GPU worker plus a queue, a 240 s hard timeout per job, SQLite store, `ANALYZER=real\|demo`, `STRICT_SCHEMA=1` to strip extras. Output repaired defensively (verdict matches violations; 1–3 JPEG frames). **27/27 tests pass; jury contract checker PASS** (incl. 5 concurrent uploads) | `backend/` (see `backend/README.md`) |
| **Frontend** | Plain HTML/JS/CSS, no build, works offline, Russian UI. Upload → progress → compact verdict (disclaimer in an ⓘ tooltip) → violation cards (type, timecode, description, rule with an adilet deep link to the clause, evidence frames; the lightbox plays the moment in place) → «Что проверил сервис» checklist (found / not found / not checked, with the reason) → video player; timecode buttons play from that moment. Downloadable report. Mock mode `?mock=1`. Tested in headless Chrome, desktop and mobile | `frontend/` (see `frontend/README.md`) |
| Integration | Backend serves the UI at `/`. UI flow (headless Chrome) and jury contract checker verified end to end over the public URL with the real analyzer | `backend/check_api_contract.py` |
| Feasibility, detectors | **RT-DETR v2** chosen for people and laptops (best quality, fastest); OWLv2 for text-prompted checks on crops; Grounding DINO rejected (too slow). No detector finds the safe or a key | `docs/internal/feasibility.md` |
| **First detectors** | `ml/detectors/workplace.py`: teller leaves (stand-up / walk-off onset) → **cash_unattended** (OWLv2 money on desk crop, at desk height, ≥ 2 frames) and **workstation_unlocked** (screen still shows the bright bluish-white app). `ml/detectors/crowd.py`: **≥ 3 people for ≥ 7 s** (≥ 5 s if until the video ends), or a **second person entering a solo room** (median count 1, stays ≥ 4 s, or ≥ 2.5 s if until video end) → unauthorized_access. `ml/detectors/personal_items.py`: cup/bottle ≥ 2 s that is either confident (≥ 0.55) or moving, confirmed by the VLM on a wide crop (cup, not banknotes) → personal_items. People seen through or reflected in the glass are filtered by size and position | `ml/` |
| **GPU server** | Team Jupyter server, 2× RTX A6000 (48 GB). Project at `~/work/forte_datathon` (Jupyter: `forte_datathon/`) with its own env `env/`, models in `hf_cache/`, logs in `logs/`. Nothing outside that folder is touched (other projects live there). RT-DETR runs at 0.017 s/frame there, ~11× the laptop | `forte_datathon/` on the server |
| VLM result (2B) | Qwen3-VL-2B 4-bit passed only **6/16** state checks (never saw the key, rarely the cash) → moving to **Qwen3-VL-8B** on the server, on zoomed crops. `ml/perception/vlm.py` picks 8B on a big GPU, 2B in 4-bit on a small one; includes `p_yes`, `locate` (bounding box) and `describe` | `ml/perception/vlm.py` |
| VLM result (8B) | Qwen3-VL-8B (bf16, GPU server): **12/16** checks, 0.17 s per question, 16.5 GB. Full-frame answers are noisy (confuses the open room door with the safe door), so all VLM use is on **crops** with multi-sample consistency | `out/feasibility/qwen3vl8b/` (server) |
| Safe detector (VLM) | `ml/detectors/safe.py`: VLM locates the safe once, then every 2 s asks "door open?" on an enlarged crop. **Open ≥ 6 s** → safe_left_open (X-20 caught at 4 s vs label 5 s, no false alarms). **Key left in the lock is not detectable**: a few pixels; single and before/after questions failed, and the behaviour rule also fired on clean X-12/X-25, so it is off (`ML_SAFE_KEY_RULE=1` to enable) | `ml/detectors/safe.py` |
| Coat/bag on desk (VLM) | `personal_items.py`: VLM on the desk crop every 3 s; item must be absent at the start and then seen with p ≥ 0.9 for ≥ 3 samples (or ≥ 2 until the end). Catches X-40 (and the cash bag in X-17), no false alarms | `ml/detectors/personal_items.py` |
| **Deployment (LIVE)** | Service on the GPU server (GPU 1, VLM on, offline weights, localhost only) at the **fixed ngrok address https://eggbeater-stardom-unsaid.ngrok-free.dev** (UI at `/`, API at `/api/v1/...`; Cloudflare quick tunnel kept as a backup, its current URL in the server's `logs/public_url.txt`; `deploy/watchdog.sh` restarts the service and tunnels). The jury API key is only in the server's project `.env` (ask the team lead). **Jury contract checker PASS over the public URL** (v21: X-26 → violation, 3 concurrent jobs in 22.5 s wall time; limit 300 s). The quick-tunnel URL changes if the tunnel restarts | `deploy/`, server `logs/service.log`, `logs/tunnel.log` |
| Dev tooling | `eval/cache_detections.py` caches RT-DETR detections; `ML_OBJECTS_CACHE=out/cache/objects python -m eval.run_eval` reuses them, so a full evaluation takes about 3 min instead of 15 | `eval/` |
| Data findings | **X-4 = X-47 and X-5 = X-48 are identical files** (40 unique videos; X-4 holds 2 violations at 57 s and 68 s). Labels mark the moment the teller *gets up*, not when she leaves the room | `data/labels.csv` (`duplicate_of`) |

### Future work
| Missed type | Videos | Approach |
|---|---|---|
| Counting cash by hand | X-1, X-44, X-4 = X-47 | Hand pose (RTMPose) over the desk crop: repeated flicking motion while the counting machine is idle |
| Key left in the safe | X-13 | Higher-resolution crop of the safe lock, or a small fine-tuned detector for the key |
| Door left open | X-32 | Locate the room door once (VLM), then ask "door open?" on its crop over time, like the safe rule |
| Client absent during an operation | X-34 | Track the client side of the desk; flag cash handling while it is empty |
| Type unclear | X-2, X-22 | Needs clarification of the label before a detector |

**Open questions**
- Violation types are uncertain for X-1, X-2, X-13, X-44 and X-17 (see `docs/internal/step1_findings.md`).
- `workstation_unlocked` rests on the bank's internal information-security rules referenced by АРРФР № 53 (`legal_confidence: referential`).

### Models used
| Job | Model | Licence | How |
|---|---|---|---|
| People, laptop, cups | RT-DETRv2-R18 (`PekingU/rtdetr_v2_r18vd`) | Apache-2.0 | Pre-trained COCO, every sampled frame |
| Cash on the desk | OWLv2 (`google/owlv2-base-patch16-ensemble`) | Apache-2.0 | Text prompts on the desk crop |
| States on zoomed crops (safe open, coat/bag, cup vs banknotes) | Qwen3-VL-8B-Instruct; Qwen3-VL-2B in 4-bit on a small GPU | Apache-2.0 | Yes/no P(yes) from next-token logits |

No model was trained or fine-tuned on the case videos: 42 clips are too few, and the final
test uses a new camera angle. Rules over time combine the model outputs (`ml/detectors/`).

**Not used:** Ultralytics YOLO (AGPL-3.0), Qwen2.5-VL-3B (research licence), any cloud API.

## Principles
- **Fully local.** All models run inside the service. No cloud AI APIs are used, and no
  video, frames or descriptions leave the machine. After the model weights are
  downloaded, the service works offline: with every outside network connection blocked,
  models load in 8 s and X-26, X-20, X-29 give the same results, with zero network attempts.
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
  catalog.py     violation types and legal citations from data/rules.json, adilet deep links
  checks.py      «Что проверил сервис» checklist (extra `checks` field)
  perception/    RT-DETRv2, OWLv2, Qwen3-VL wrappers
eval/       evaluation on the labelled training set
tools/      data utilities (frame cache, contact sheets, zoom, camera-change augmentation)
deploy/     start scripts: model download, server, ngrok/Cloudflare tunnels, watchdog
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
# plus "checks" and "scene" for the UI (removed by the backend when STRICT_SCHEMA=1)
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
`ctx.frames` holds sampled `(t_sec, frame)` pairs at 2 fps (`SAMPLE_FPS`), on the video's own timestamps. `Event` needs a `type_id`
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

Model weights are not in git (open models from Hugging Face, ~22 GB with Qwen3-VL-8B). Download them once into `hf_cache/` with `bash deploy/download_models.sh` (needs internet); after that the service runs offline. `deploy/run_server.sh` also downloads them on first start if `hf_cache/` is missing.

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

# simulated camera changes (mirror, tilt, zoom, low quality) -> data/aug/<variant>/, then evaluate one
python tools/augment_videos.py data/raw data/aug tilt mirror zoom lowq
python -m eval.run_eval --video-dir data/aug/tilt --ext .mp4 --tag my-change-tilt
ML_IGNORE_LAPTOP=1 python -m eval.run_eval --tag my-change-nolaptop   # laptop hidden

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
| ML engineer | @batyr_ssh, @adik_it |
| Backend engineer | @aruzhanimm |
| Frontend engineer | @batyr_ssh |

Start with `docs/internal/PLAN.md`: architecture, task split, milestones, risks.
Analysis notes are in `docs/internal/step1_findings.md`, and the regulation mapping is in
`docs/internal/legal_mapping.md` and `data/rules.json`.

# ForteBank Datathon 26 — cashier-violation detection

A local-only AI service. Someone uploads a `.mov` of a teller's workplace, and the
service says whether it shows visible signs of possible cash-discipline violations.
For each violation it gives the type, a timecode, evidence frames, a description and
the RK legal rule behind it.

The full brief is `Кейс_ForteBank.docx` (in Russian; sections 1–10 plus the FAQ). The
summary below is what drives our design.

---

## 1. The task in one page

**What we must deliver**
- A web UI where the user uploads a video, sees the processing status, and gets the
  verdict "Нарушение не обнаружено" or "Обнаружены признаки возможных нарушений".
  For each violation it shows the type, timecode, description, 1–3 evidence frames
  and the rule (document name plus clause).
- A public API, which the jury grades automatically:
  - `POST /api/v1/analyze`: multipart field `file` (.mov), returns `job_id`.
  - `GET /api/v1/jobs/{job_id}`: returns `status` (`processing|done|failed`),
    `verdict` (`violation|no_violation`) and `violations[]`. Each violation has `type`,
    `timecode_sec`, `description` and `evidence_frames[{timestamp_sec, image_base64}]`.
  - Every request carries an `X-API-Key` header; requests without a valid key are rejected.
- Documentation: architecture, models, legal sources, the list of violation types,
  and known limitations.

**Hard constraints**
| Constraint | What it means for us |
|---|---|
| Everything runs locally | No cloud AI APIs, ever. Using one gets us **disqualified**. |
| Portable | Once weights are downloaded, the service runs with no internet access. |
| Open-source models only | Licence must allow commercial use (Apache-2.0 / MIT / BSD). **Avoid AGPL** (Ultralytics YOLO). |
| No faces, no audio | No face recognition or identification of any kind. Analysis is visual only. |
| 5 min per video | A video that is not finished within 5 minutes counts as unprocessed. The jury may submit 5+ at once. |
| Public URL | We host it ourselves, on our own hardware. |
| RK law only | Sources are НБРК / adilet.zan.kz. Invented citations are penalised. |
| Visible facts only | Never claim something the video cannot show (e.g. that a lock was turned). |

**Scoring (100 points)**: detection 25 · localisation 15 · classification 15 ·
rule grounding 15 · robustness to a new camera angle 10 · product 10 · tech 10.
**A missed violation is unacceptable; false positives should be as few as possible.**

---

## 2. What is done

| Item | Where |
|---|---|
| Dataset copied, with filenames normalised (labels mix Latin `X` and Cyrillic `Х`) | `data/raw/`, `data/open_labels.xlsx` |
| Contact sheets for every video, plus dense zoom tool | `tools/contact_sheets.py`, `tools/zoom.py`, output in `out/` |
| Violation taxonomy: 18 of 22 violation videos typed | `docs/internal/step1_findings.md` |
| Legal mapping: 9 types → clauses of 3 RK acts, verbatim quotes | `data/rules.json`, `docs/internal/legal_mapping.md` |

**Dataset facts**
- 42 videos: 22 violations, 20 clean.
- All 464×848 portrait, about 30 fps, 11–143 s long.
- **3 room layouts** already appear in training. We use them as the stand-in for the
  new camera angle in the final test.
- The label timestamp is the moment the violation becomes visible.

**Violation types (current)**
| id | What is visible | Training examples |
|---|---|---|
| `unauthorized_access` | Door left open after the teller enters, or another person enters / joins while cash is out | X-4, X-30, X-38, X-18, X-33, X-32 |
| `cash_unattended` | Teller leaves; cash or coin rolls stay on the desk | X-26, X-15, X-24 |
| `safe_left_open` | Safe door left open, or key left in the lock | X-20, X-22 (X-13?) |
| `workstation_unlocked` | Teller leaves; laptop still shows the working app | X-28, X-11 |
| `personal_items` | Coat or bag on the cash desk; eating or drinking; camera phone | X-40, X-46 |
| `no_machine_check` | Client's cash counted by hand only; counting machine unused | X-47 (X-1?, X-44?) |
| `client_absent` | Cash processed after the client has left | X-34 |
| `collector_handover` | Cash bag from the collector accepted without visible checks | X-17? |
| `no_client_identification` | Cash accepted with no ID shown (hypothesis) | X-2? |

**Still unknown:** X-1, X-13, X-44 (and the exact violation in X-2 and X-17).

**Ruled out:**
- "Door not locked when leaving": the clean X-29 behaves the same, so it is not a usable signal.
- "Hair worn down": the clean X-43 shows the same, and no RK rule covers it.

---

## 3. Proposed architecture

**Design goals, taken from the scoring:**
- High recall, so no missed violations.
- Exact timecodes.
- Explanations backed by evidence.
- Zero invented citations.
- Robust to a new camera angle.
- Fits a **4 GB GPU** and well under 5 min per video.

The design is a perception layer, then per-type rules over time, then a small
vision-language model (VLM) that verifies candidates. The rules give exact timecodes
and explainability. The VLM removes false positives and catches what the rules miss.
Citations always come from `rules.json`.

```
 .mov ──► [1 Decode & sample] ──► [2 Scene layout] ──► [3 Perception per frame] ──► [4 State timeline]
            PyAV/OpenCV             find desk, safe,      people + tracks,             teller_present,
            4 fps (+1 fps heavy)    door, laptop,         hands (pose),                n_people, outsider,
                                    counting machine      objects (open-vocab),        cash_on_desk, safe_open,
                                    → zones per video     crop classifiers             screen_on, item_on_desk…
                                                                                              │
          [8 Verdict + JSON] ◄── [7 Evidence + text] ◄── [6 VLM verify] ◄── [5 Rule engine] ◄─┘
           any confirmed         1–3 JPEG frames with     small local VLM        one temporal rule per
           event → violation     boxes; templated         answers yes/no on      type, e.g. teller_absent
                                 description; citation    crops around each      ∧ cash_on_desk ≥ 2 s
                                 copied from rules.json   candidate              → event at onset
```

| Stage | What it does | Candidate tech (licence must be checked in feasibility) |
|---|---|---|
| 1 Decode | Sample 4 fps for light models and ~1 fps for heavy ones; keep exact timestamps | PyAV / OpenCV |
| 2 Scene layout | Run once per video: detect static objects → build zones (desk, teller side, client side, door, safe). Nothing is hard-coded, which is what makes it robust to the angle change | open-vocab detector on the first N frames |
| 3 Perception | Person boxes + IDs over time; hand keypoints; objects (laptop, bag, coat, cup, phone, cash bag); small crop classifiers for cash-on-desk, safe-door state and screen state | RT-DETR / D-FINE (Apache-2.0), ByteTrack (MIT), RTMPose (Apache-2.0), OWLv2 / Grounding DINO (Apache-2.0) |
| 4 State timeline | Per-timestamp boolean and numeric states, smoothed | pure Python |
| 5 Rule engine | One detector per type; emits candidate events with onset time and confidence | pure Python, thresholds tuned on train |
| 6 VLM verify | Runs only on candidates and a few keyframes: a yes/no checklist on crops. Also asks generic questions for unseen types (phone in hand, cash on floor…) | Qwen3-VL-2B/4B, SmolVLM2, Moondream2, Florence-2: pick by licence, VRAM and accuracy |
| 7 Evidence | Onset frame plus 1–2 context frames, boxes drawn; description built from a template using observed facts only | OpenCV |
| 8 Output | Exact API schema; verdict `violation` if any confirmed event | Pydantic |

**Choices that matter for the score**
- **Timecode = onset of the visible state** (e.g. the moment the teller leaves). This matches the labels.
- **Citations live in the API output.** Append "Возможное нарушение: <document>, <clause>" to `description`, and also add an extra `rule` object to each violation.
- **No hallucinated descriptions.** Text comes from templates filled with detected facts. The VLM may add one short caption, but never a legal claim.
- **Unknown types.** If the VLM flags something suspicious that no rule matches, report a generic type such as "Иное возможное нарушение" with low confidence, but only when the recall/precision trade-off on train supports it.
- **Throughput.** Target **≤ 60 s per video**, with one GPU worker and a queue, so 5 concurrent jury videos still finish within 5 min.

---

## 4. Repository layout (target)

```
backend/        FastAPI app: API, auth, job queue, worker, result store, serves frontend
frontend/       Upload page, status, result view, video player with timeline markers
ml/
  pipeline.py   analyze(video_path) -> AnalysisResult   ← the one contract between ML and backend
  perception/   detectors, tracker, pose, crop classifiers
  scene/        layout & zone inference
  rules/        one module per violation type
  vlm/          verification + checklist prompts
  evidence.py   frame selection, drawing, JPEG/base64
eval/           run on all 42 videos → verdict acc, timecode error, type acc, runtime
data/           raw/ (not committed), open_labels.xlsx, rules.json
docs/           findings, legal mapping, architecture, limitations
tools/          contact sheets, zoom
```

**The ML ↔ backend contract** (agree on this on day 1, then work in parallel):

```python
def analyze(video_path: str, progress: Callable[[float], None] | None = None) -> dict:
    return {
        "verdict": "violation" | "no_violation",
        "violations": [{
            "type": str,                 # human-readable name from rules.json
            "type_id": str,              # e.g. "cash_unattended"
            "timecode_sec": float,
            "confidence": float,
            "description": str,          # observed facts + "Возможное нарушение: …"
            "rule": {"document": str, "clause": str, "quote": str, "url": str},
            "evidence_frames": [{"timestamp_sec": float, "image_base64": str}],
        }],
        "processing_sec": float,
    }
```

The backend exposes the required fields exactly and passes `rule` and `confidence`
through as extras. The frontend reads the same JSON.

---

## 5. Team split

### ML engineer: detection quality (criteria 1, 2, 3, 5)
1. **Feasibility test (next step).** Find out which objects off-the-shelf models see
   reliably (people, door, safe and its door state, banknotes, laptop screen, coat, bag,
   cup, phone, counting machine). Measure fps and VRAM on the 4 GB GPU and check licences.
   Output: chosen model set plus a list of objects that need fine-tuning.
2. Build `eval/` first: run all 42 videos and report metrics. Hold out one room layout
   as the "new angle" test.
3. Implement `ml/pipeline.py` stages 1–5. Order types by value:
   `unauthorized_access` → `cash_unattended` → `safe_left_open` →
   `workstation_unlocked` → `personal_items` → the rest.
4. Add VLM verification (stage 6) and tune thresholds for recall first.
5. If needed, label a few hundred frames for weak objects (cash, safe door) and fine-tune.
   Augment with flips, perspective warps and crops, and film our own clips from other angles.

### Backend engineer: product reliability and API (criteria 6, 7, and keeping all others from scoring zero)
1. FastAPI skeleton with the two endpoints, `X-API-Key` auth, a job store (SQLite) and
   **one GPU worker process plus a queue**. Start with a **mock `analyze()`** that returns
   canned results, so the frontend and jury flow work from hour one.
2. Upload validation (.mov, size limit ~200 MB), temp storage, cleanup, timeouts
   (a job that runs past its time budget is marked `failed`, never left hanging),
   a health endpoint, structured logs.
3. Packaging: Dockerfile with CUDA, weights baked in or mounted, no runtime downloads
   (the offline/portable requirement).
4. Public URL: run on the team GPU machine behind a Cloudflare Tunnel (or similar) and
   keep it up continuously on jury day. Load-test 5–10 concurrent uploads.
5. Own the submission docs: run instructions, API key handover, architecture write-up.

### Frontend engineer: product (criterion 6) and how the result reads (criterion 4)
1. Upload page: drag-and-drop, file checks, progress bar, polling `GET /jobs/{id}`.
2. Result page:
   - a verdict banner;
   - one card per violation with type, timecode, description, a **rule citation with an adilet link**, and evidence frames that can be enlarged;
   - a **video player with timeline markers** that jumps to each timecode.
3. Russian UI. Clear empty, error and "processing" states. A note that the result is a
   hint for a human reviewer, not a legal conclusion (case §7).
4. Build against the mock API from day 1, then switch to the real backend.
5. Help the ML engineer with labelling (cash, safe door) if fine-tuning is needed.

### Shared
- The agreed `analyze()` JSON contract (above) is the integration point. Changing it
  needs all three people.
- The legal sources: re-check every clause in `rules.json` directly on adilet before
  submitting, and find a direct source for `workstation_unlocked`.

---

## 6. Plan and milestones

| # | Milestone | Owner | Done when |
|---|---|---|---|
| M0 | Contract agreed; backend with mock + frontend end-to-end on localhost | BE + FE | Upload → mock result renders |
| M1 | Feasibility test complete; model set chosen | ML | Table of detectable objects, fps, VRAM, licences |
| M2 | Eval harness, then first 2 types working | ML | Metrics printed on all 42 videos |
| M3 | Real pipeline wired into backend; public URL live | BE + ML | Jury-style curl works end to end |
| M4 | Remaining types, plus VLM verification and threshold tuning | ML | Recall on violations ≈ 100 %, FP rate measured |
| M5 | Freeze: docs, limitations, load test, re-verify citations | all | Submission package ready **before 12:00** |

---

## 7. Known risks

- **Banknotes are tiny** (~20–40 px). Cash-on-desk needs crops, a fine-tuned classifier or a VLM.
- **Key in lock (X-22)** is a few pixels. It may need a VLM on the safe crop or a motion heuristic.
- **4 GB VRAM** limits VLM size. Keep the VLM on crops and candidates only.
- **New camera angle**: zones must come from detection, never from fixed coordinates.
- **Concurrency**: sequential processing of 5 jury videos must still fit in 5 min.
- **Unseen types**: they are expected in the test set (FAQ #9). The VLM checklist is the safety net.
- **Weak legal source** for `workstation_unlocked` (only an indirect clause so far).

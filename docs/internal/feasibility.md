# Feasibility test: which models can see what we need

**Setup.** 84 frames from all 5 layouts (`out/feasibility/frames.csv`): for each violation
video, 2 s before the label, at the label and 2 s after; plus 2 frames each from 9 clean
videos. Hardware: RTX 3050 Laptop, 4 GB. Scripts: `eval/feasibility/`. Annotated sheets:
`out/feasibility/<model>/sheet_XX.jpg`.

## 1. Object detectors

| Model | Licence | s/frame | Peak GPU | Verdict |
|---|---|---|---|---|
| **RT-DETR v2 R18** (`PekingU/rtdetr_v2_r18vd`) | Apache-2.0 | **0.16** | **0.18 GB** | **Use for people and laptops** |
| OWLv2 base (`google/owlv2-base-patch16-ensemble`) | Apache-2.0 | 0.58 | 0.39 GB | Use sparingly (scene setup only) |
| Grounding DINO tiny (`IDEA-Research/grounding-dino-tiny`) | Apache-2.0 | 7.08 | 1.93 GB | **Reject**: too slow, merges labels |

What each sees (judged from the sheets):

| Object | RT-DETR | OWLv2 | Grounding DINO |
|---|---|---|---|
| Person | **excellent** (0.88–0.93) | good (0.3–0.5) | good (0.6–0.8) |
| Laptop | **excellent** (0.9+) | good | good |
| Counting machine | as "handbag" (0.5–0.65), consistent | yes (0.15–0.25) | yes |
| Safe (grey cabinet) | no class | **not detected** | **not detected** |
| Banknotes / coin rolls on desk | no class | partial, unreliable | partial, label noise |
| Key in safe lock | no class | false positives (door handles) | false positives |
| Coat / bag / cup / phone | handbag, cell phone (some) | some | some |

**Pitfall in all models:** people and screens **reflected in or seen through the glass
wall** are detected. They are people outside the room. RT-DETR gives most of them lower
scores (~0.5–0.65 vs ~0.9 for people inside). Filter by score ≥ 0.75 and by feet position
on the floor inside the room; otherwise `unauthorized_access` will raise false alarms.

**Implication:** no off-the-shelf detector finds the **safe**, **cash** or a **key**.
These must come from (a) a VLM on crops, (b) fine-tuning, or (c) geometry: the safe is a
static object, so its box can be found once per video and its *state* read from crops.

## 2. Vision-language models (state questions)
*Running.*

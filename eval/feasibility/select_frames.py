"""Pick a fixed, diverse frame set for the model feasibility test.

Violation videos: frames at label_t - 2 s, label_t, label_t + 2 s.
Clean videos: 2 frames (1/3 and 2/3 of the clip), up to 2 videos per layout.
Frames come from the cache in data/frames/.

    python -m eval.feasibility.select_frames      -> out/feasibility/frames.csv
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "data" / "frames"
OUT = ROOT / "out" / "feasibility"


def nearest(video: str, t: float):
    with open(FRAMES / video / "index.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    best = min(rows, key=lambda r: abs(float(r["t_sec"]) - t))
    return float(best["t_sec"]), FRAMES / video / best["file"]


def main():
    with open(ROOT / "data" / "labels.csv", encoding="utf-8") as fh:
        labels = list(csv.DictReader(fh))
    picks = []
    clean_per_layout = defaultdict(int)
    for lab in labels:
        v, dur = lab["video"], float(lab["duration_s"])
        if lab["violation"] == "1":
            t0 = float(lab["label_t"])
            for role, dt in (("before", -2), ("at_label", 0), ("after", 2)):
                t = min(max(0, t0 + dt), dur - 0.3)
                picks.append((v, lab["layout"], lab["type_id"], lab["type_confident"], role,
                              *nearest(v, t)))
        elif clean_per_layout[lab["layout"]] < 2:
            clean_per_layout[lab["layout"]] += 1
            for role, frac in (("clean_1", 1 / 3), ("clean_2", 2 / 3)):
                picks.append((v, lab["layout"], "", "", role, *nearest(v, dur * frac)))

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "frames.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["video", "layout", "type_id", "type_confident", "role", "t_sec", "path"])
        for p in picks:
            w.writerow([*p[:5], f"{p[5]:.3f}", p[6].relative_to(ROOT).as_posix()])
    by_layout = defaultdict(int)
    for p in picks:
        by_layout[p[1]] += 1
    print(f"{len(picks)} frames; per layout: {dict(sorted(by_layout.items()))}")


if __name__ == "__main__":
    main()

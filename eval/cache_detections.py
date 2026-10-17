"""Run the object detector over the cached frames once and store the results,
so detector rules can be developed and evaluated without re-running models.

    python -m eval.cache_detections [--fps 2]   -> out/cache/objects/<video>.json
"""
import argparse
import csv
import json
import time
from pathlib import Path

import cv2

from ml.perception import objects

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / "data" / "frames"
OUT = ROOT / "out" / "cache" / "objects"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=float, default=2.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    objects.warmup()
    total_frames, total_time = 0, 0.0
    for vdir in sorted(FRAMES.iterdir(), key=lambda p: int(p.name.split("-")[1])):
        with open(vdir / "index.csv", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        step = max(1, round(4 / args.fps))  # cache is 4 fps
        rows = rows[::step]
        imgs = [cv2.imread(str(vdir / r["file"])) for r in rows]
        t0 = time.time()
        dets = objects.detect(imgs)
        dt = time.time() - t0
        total_frames += len(imgs)
        total_time += dt
        h, w = imgs[0].shape[:2]
        data = {"video": vdir.name, "fps": args.fps, "width": w, "height": h,
                "frames": [{"t": float(r["t_sec"]), "dets": d} for r, d in zip(rows, dets)]}
        (OUT / f"{vdir.name}.json").write_text(json.dumps(data), encoding="utf-8")
        print(f"{vdir.name}: {len(imgs)} frames in {dt:.1f}s", flush=True)
    print(f"total {total_frames} frames, {total_time / max(1, total_frames):.3f} s/frame")


if __name__ == "__main__":
    main()

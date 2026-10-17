"""Decode each video once and cache frames at a fixed rate.

Output layout:
    OUT_DIR/<video>/t_000250.jpg   (filename = timestamp in milliseconds)
    OUT_DIR/<video>/index.csv      (frame_idx, t_sec, file)

Usage:
    python tools/extract_frames.py data/raw data/frames [FPS=4]
"""
import csv
import sys
from pathlib import Path

import cv2


def extract(video: Path, out_dir: Path, rate: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # Frame indices closest to t = 0, 1/rate, 2/rate, ...
    wanted = {}
    k = 0
    while True:
        idx = int(round(k / rate * fps))
        if idx >= n:
            break
        wanted.setdefault(idx, k / rate)
        k += 1

    rows = []
    idx = 0
    while idx < n:
        if idx in wanted:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / fps  # true timestamp of the decoded frame
            name = f"t_{int(round(t * 1000)):06d}.jpg"
            cv2.imwrite(str(out_dir / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            rows.append([idx, f"{t:.3f}", name])
        elif not cap.grab():
            break
        idx += 1
    cap.release()

    with open(out_dir / "index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame_idx", "t_sec", "file"])
        w.writerows(rows)
    return len(rows)


def main(video_dir, out_root, rate="4"):
    video_dir, out_root, rate = Path(video_dir), Path(out_root), float(rate)
    videos = sorted(video_dir.glob("*.mov"), key=lambda p: int(p.stem.split("-")[1]))
    total = 0
    for v in videos:
        if (out_root / v.stem / "index.csv").exists():
            continue  # already cached
        count = extract(v, out_root / v.stem, rate)
        total += count
        print(f"{v.stem}: {count} frames", flush=True)
    print(f"done, {total} new frames")


if __name__ == "__main__":
    main(*sys.argv[1:])

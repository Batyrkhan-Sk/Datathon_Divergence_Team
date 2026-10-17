"""Make "different camera" copies of the training videos to test robustness.

Labels and timestamps stay valid, so eval/run_eval.py can score them directly:
    python tools/augment_videos.py data/raw data/aug tilt mirror zoom lowq
    python -m eval.run_eval --video-dir data/aug/tilt --ext .mp4 --tag aug-tilt

Variants (one camera change each, moderate on purpose):
    tilt    perspective change as if the camera were moved sideways and lower
    mirror  horizontal flip (room layout mirrored)
    zoom    camera closer: central 85% crop, scaled back up
    lowq    worse camera: half resolution, slight blur, darker, JPEG artefacts
"""
import sys
from pathlib import Path

import cv2
import numpy as np


def tilt(f):
    h, w = f.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[0.06 * w, 0.04 * h], [w, 0], [0.94 * w, h], [0, 0.96 * h]])
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(f, m, (w, h), borderMode=cv2.BORDER_REPLICATE)


def mirror(f):
    return cv2.flip(f, 1)


def zoom(f):
    h, w = f.shape[:2]
    ch, cw = int(h * 0.85), int(w * 0.85)
    y, x = (h - ch) // 2, (w - cw) // 2
    return cv2.resize(f[y:y + ch, x:x + cw], (w, h), interpolation=cv2.INTER_LINEAR)


def lowq(f):
    h, w = f.shape[:2]
    small = cv2.resize(f, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    f = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    f = cv2.GaussianBlur(f, (3, 3), 0)
    f = cv2.convertScaleAbs(f, alpha=0.85, beta=-10)
    ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 45])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


VARIANTS = {"tilt": tilt, "mirror": mirror, "zoom": zoom, "lowq": lowq}


def convert(src: Path, dst: Path, fn):
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = cv2.VideoWriter(str(dst), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.write(fn(f))
    cap.release()
    out.release()


def main(src_dir, out_root, *variants):
    src_dir, out_root = Path(src_dir), Path(out_root)
    for name in variants or VARIANTS:
        d = out_root / name
        d.mkdir(parents=True, exist_ok=True)
        for v in sorted(src_dir.glob("*.mov")):
            dst = d / f"{v.stem}.mp4"
            if not dst.exists():
                convert(v, dst, VARIANTS[name])
        print(f"{name}: {len(list(d.glob('*.mp4')))} videos", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])

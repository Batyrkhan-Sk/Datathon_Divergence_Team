"""Dense zoomed contact sheet for one video segment.

Usage:
    python tools/zoom.py VIDEO T0 T1 STEP X0 Y0 X1 Y1 OUT.jpg [COLS]
Crop box is given as fractions of frame width/height (0..1).
"""
import sys

import cv2
import numpy as np


def main(video, t0, t1, step, x0, y0, x1, y1, out, cols=4):
    t0, t1, step = float(t0), float(t1), float(step)
    x0, y0, x1, y1 = map(float, (x0, y0, x1, y1))
    cols = int(cols)
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tiles = []
    t = t0
    while t <= t1 + 1e-6:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, f = cap.read()
        if not ok:
            break
        h, w = f.shape[:2]
        c = f[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        scale = 480 / c.shape[1]
        c = cv2.resize(c, (480, int(c.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
        cv2.rectangle(c, (0, 0), (110, 26), (0, 0, 0), -1)
        cv2.putText(c, f"{t:.2f}s", (5, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(c)
        t += step
    th, tw = tiles[0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * th, cols * tw, 3), 255, np.uint8)
    for i, c in enumerate(tiles):
        r, k = divmod(i, cols)
        sheet[r * th:(r + 1) * th, k * tw:(k + 1) * tw] = c
    cv2.imwrite(out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])


if __name__ == "__main__":
    main(*sys.argv[1:])

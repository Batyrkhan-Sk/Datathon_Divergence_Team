"""Step 1 exploration: build labelled contact sheets for every training video.

For violation videos: a dense sheet around the labelled timestamp (t-4s .. t+4s)
plus an overview sheet across the whole video.
For clean videos: an overview sheet only.

Usage:
    python tools/contact_sheets.py data/raw data/open_labels.xlsx out/sheets
"""
import csv
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import openpyxl

TILE_W = 480
# Vertical band (fraction of frame height) holding the desk, safe and people.
CROP_Y = (0.2, 0.76)


def normalize_name(name: str) -> str:
    # Labels mix Latin "X" and Cyrillic "Х"; the copied files use Latin.
    return name.strip().replace("Х", "X")


def parse_timestamp(text: str):
    """'22 секунда' -> 22.0, '1минута 8 секунда' -> 68.0, other -> None."""
    if not text:
        return None
    m = re.search(r"(\d+)\s*минут", text)
    s = re.search(r"(\d+)\s*секунд", text)
    if not m and not s:
        return None
    return float((int(m.group(1)) * 60 if m else 0) + (int(s.group(1)) if s else 0))


def load_labels(path: Path):
    ws = openpyxl.load_workbook(path, read_only=True).active
    labels = {}
    for row in list(ws.iter_rows(values_only=True))[1:]:
        cells = [str(c) for c in row if c is not None]
        if not cells:
            continue
        name = normalize_name(cells[0])
        ts = parse_timestamp(cells[1]) if len(cells) > 1 else None
        violation = any(c.strip() == "нарушение" for c in cells[1:])
        labels[name] = {"violation": violation, "t": ts}
    return labels


def read_frame(cap, t_sec, fps, n_frames):
    idx = int(round(t_sec * fps))
    idx = max(0, min(idx, n_frames - 1))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, frame = cap.read()
    return frame if ok else None


def tile(frame, caption, highlight=False):
    h, w = frame.shape[:2]
    frame = cv2.resize(frame, (TILE_W, int(h * TILE_W / w)))
    color = (0, 0, 255) if highlight else (0, 0, 0)
    cv2.rectangle(frame, (0, 0), (TILE_W, 30), color, -1)
    cv2.putText(frame, caption, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                (255, 255, 255), 2, cv2.LINE_AA)
    if highlight:
        cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1),
                      (0, 0, 255), 4)
    return frame


def grid(tiles, cols):
    th, tw = tiles[0].shape[:2]
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * th, cols * tw, 3), 255, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = t[:th, :tw]
    return sheet


def sheet_for_times(cap, fps, n_frames, times, label_t, title):
    tiles = []
    for t in times:
        f = read_frame(cap, t, fps, n_frames)
        if f is None:
            continue
        hl = label_t is not None and abs(t - label_t) < 0.26
        tiles.append(tile(f, f"{title}  t={t:.1f}s", highlight=hl))
    return grid(tiles, 4) if tiles else None


def main(video_dir, labels_path, out_dir):
    video_dir, out_dir = Path(video_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = load_labels(Path(labels_path))
    meta_rows = []

    for vp in sorted(video_dir.glob("*.mov"), key=lambda p: int(p.stem.split("-")[1])):
        name = vp.stem
        lab = labels.get(name, {"violation": None, "t": None})
        cap = cv2.VideoCapture(str(vp))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        dur = n / fps if fps else 0
        meta_rows.append([name, lab["violation"], lab["t"], f"{fps:.2f}", n,
                          f"{dur:.1f}", w, h])

        # Overview: 12 evenly spaced frames over the whole clip.
        times = list(np.linspace(0, max(dur - 0.1, 0), 12))
        if lab["t"] is not None:
            times = sorted(set(times) | {lab["t"]})
        s = sheet_for_times(cap, fps, n, times, lab["t"], name)
        if s is not None:
            tag = "VIOL" if lab["violation"] else "CLEAN"
            cv2.imwrite(str(out_dir / f"{name}_{tag}_overview.jpg"), s,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])

        # Dense window around the labelled moment: t-4 .. t+4 every 0.5s.
        if lab["t"] is not None:
            t0 = lab["t"]
            times = [t0 + d for d in np.arange(-4, 4.01, 0.5) if 0 <= t0 + d < dur]
            s = sheet_for_times(cap, fps, n, times, t0, name)
            if s is not None:
                cv2.imwrite(str(out_dir / f"{name}_VIOL_window.jpg"), s,
                            [cv2.IMWRITE_JPEG_QUALITY, 80])
            # Close-up: desk area only, 1s steps, near-native resolution.
            times = [t0 + d for d in range(-4, 5) if 0 <= t0 + d < dur]
            tiles = []
            for t in times:
                f = read_frame(cap, t, fps, n)
                if f is None:
                    continue
                y0, y1 = int(h * CROP_Y[0]), int(h * CROP_Y[1])
                tiles.append(tile(f[y0:y1], f"{name}  t={t:.0f}s",
                                  highlight=abs(t - t0) < 0.26))
            if tiles:
                cv2.imwrite(str(out_dir / f"{name}_VIOL_crop.jpg"), grid(tiles, 3),
                            [cv2.IMWRITE_JPEG_QUALITY, 85])
        cap.release()
        print(f"{name}: viol={lab['violation']} t={lab['t']} fps={fps:.1f} "
              f"dur={dur:.1f}s {w}x{h}")

    with open(out_dir / "metadata.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["video", "violation", "label_t", "fps", "frames",
                     "duration_s", "width", "height"])
        wr.writerows(meta_rows)


if __name__ == "__main__":
    main(*sys.argv[1:4])

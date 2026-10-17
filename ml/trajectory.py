"""Person trajectory overlay — renders movement paths on a single frame.

The trajectory map shows where people moved during the video, drawn as
coloured paths on one representative frame. This helps the reviewer
understand the scene layout without watching the whole recording.

Returns a base64 JPEG image embedded in the result as `trajectory_map`.
"""
import base64
from typing import NamedTuple

import cv2
import numpy as np

# Colour palette for up to 6 tracked individuals (BGR)
_PALETTE = [
    (60, 120, 220),    # blue
    (220, 60, 60),     # red
    (60, 200, 60),     # green
    (200, 160, 30),    # amber
    (160, 60, 200),    # purple
    (30, 200, 200),    # teal
]


class TrackPoint(NamedTuple):
    t: float
    cx: float   # centre-x
    cy: float   # centre-y


def _box_centre(box: list[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _extract_tracks(times: list[float],
                    people: list[list[list[float]]]) -> list[list[TrackPoint]]:
    """Greedy nearest-neighbour tracker: assigns each detection to the closest
    existing track centre, or starts a new track."""
    tracks: list[list[TrackPoint]] = []
    active_centres: list[tuple[float, float]] = []   # last centre per track

    for t, boxes in zip(times, people):
        used = [False] * len(tracks)
        for box in boxes:
            cx, cy = _box_centre(box)
            best_i, best_d = -1, float("inf")
            for i, (ax, ay) in enumerate(active_centres):
                if used[i]:
                    continue
                d = (cx - ax) ** 2 + (cy - ay) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            MERGE_DIST_SQ = 80 ** 2  # px; boxes >80 px apart = different people
            if best_i >= 0 and best_d < MERGE_DIST_SQ:
                tracks[best_i].append(TrackPoint(t, cx, cy))
                active_centres[best_i] = (cx, cy)
                used[best_i] = True
            else:
                tracks.append([TrackPoint(t, cx, cy)])
                active_centres.append((cx, cy))
    return [tr for tr in tracks if len(tr) >= 3]


def build_map(frame: np.ndarray,
              times: list[float],
              people: list[list[list[float]]]) -> str | None:
    """Render trajectory paths on `frame` and return base64 JPEG, or None."""
    if not times or not people:
        return None

    tracks = _extract_tracks(times, people)
    if not tracks:
        return None

    img = frame.copy()
    # Darken background slightly so paths stand out
    img = cv2.addWeighted(img, 0.6, np.zeros_like(img), 0.4, 0)

    for idx, track in enumerate(tracks[:6]):
        color = _PALETTE[idx % len(_PALETTE)]
        pts = [(int(p.cx), int(p.cy)) for p in track]
        for i in range(1, len(pts)):
            cv2.line(img, pts[i - 1], pts[i], color, 2, cv2.LINE_AA)
        # Start dot (larger) and end dot
        if pts:
            cv2.circle(img, pts[0], 5, color, -1, cv2.LINE_AA)
            cv2.circle(img, pts[-1], 4, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.circle(img, pts[-1], 4, color, -1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None

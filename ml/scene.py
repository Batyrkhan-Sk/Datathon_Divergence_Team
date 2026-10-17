"""Scene understanding on top of per-frame detections: who is in the room, where the
workplace is, and when the teller leaves it. Positions are always derived from the
video itself (no fixed coordinates), so a new camera angle is handled the same way.
"""
from dataclasses import dataclass

import numpy as np

# A person counts as "in the room" if detected confidently, tall enough and reaching low
# enough in the frame. Removes people seen through / reflected in the glass wall.
PERSON_MIN_SCORE = 0.7
PERSON_MIN_HEIGHT = 0.11   # fraction of frame height
PERSON_MIN_BOTTOM = 0.36   # box bottom must be below this fraction of frame height


def people_in_room(dets: list[dict], height: int) -> list[list[float]]:
    out = []
    for d in dets:
        if d["label"] != "person" or d["score"] < PERSON_MIN_SCORE:
            continue
        x1, y1, x2, y2 = d["box"]
        if y2 - y1 >= PERSON_MIN_HEIGHT * height and y2 >= PERSON_MIN_BOTTOM * height:
            out.append(d["box"])
    return out


def laptop_box(per_frame: list[list[dict]]) -> list[float] | None:
    boxes = [d["box"] for dets in per_frame for d in dets
             if d["label"] == "laptop" and d["score"] >= 0.6]
    return np.median(np.array(boxes), axis=0).tolist() if boxes else None


def _center(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def near(box: list[float], anchor: list[float], k: float = 1.6) -> bool:
    """Box centre within k anchor-widths (x) / k*1.5 anchor-heights (y) of the anchor."""
    (cx, cy), (ax, ay) = _center(box), _center(anchor)
    aw, ah = anchor[2] - anchor[0], anchor[3] - anchor[1]
    return abs(cx - ax) <= k * aw + (box[2] - box[0]) / 2 and abs(cy - ay) <= 1.5 * k * ah + (box[3] - box[1]) / 2


@dataclass
class Departure:
    t_left_desk: float      # moment the teller left the workplace (onset / timecode)
    t_room_empty: float     # first moment nobody is in the room
    teller_box: list[float] # teller's box just before leaving (for the desk crop)


STAND_UP_RATIO = 1.35       # box height jump that marks standing up from the chair
LOOKBACK_SEC = 12.0


def _leaving_onset(times, track, workplace=None) -> tuple[int, str]:
    """Index where the teller starts leaving. `track` = [(i, box)] of the leaving person,
    oldest first, ending at the last frame before the room is empty."""
    hs = [b[3] - b[1] for _, b in track]
    # 1) stood up from the chair: height jumps vs the previous ~2 s
    for k in range(len(track) - 1, 3, -1):
        prev = float(np.median(hs[max(0, k - 4):k]))
        if hs[k] >= STAND_UP_RATIO * prev and hs[k - 1] < STAND_UP_RATIO * prev:
            return track[k - 1][0], "stood_up"
    # 2) already standing: last moment at the workstation (near the laptop) before the
    #    final walk out (X-11: 17.5 s vs label 18; X-15: 15.5 s vs label 15)
    if workplace is not None:
        for k in range(len(track) - 2, 0, -1):
            if near(track[k][1], workplace) and not near(track[k + 1][1], workplace):
                return track[k][0], "left_workstation"
    # 3) end of the last still period away from the exit position
    cx = [(b[0] + b[2]) / 2 for _, b in track]
    width = float(np.median([b[2] - b[0] for _, b in track]))
    for k in range(len(track) - 2, 1, -1):
        still = all(abs(cx[m] - cx[m - 1]) < 0.15 * width for m in (k, k - 1))
        if still and abs(cx[k] - cx[-1]) > 0.6 * width:
            return track[k][0], "walked_off"
    return track[max(0, len(track) - 6)][0], "fallback"


def _follow(people, last_idx, start_idx):
    """Follow the person seen at last_idx backwards (nearest box, frame to frame)."""
    box = max(people[last_idx], key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    track = [(last_idx, box)]
    for i in range(last_idx - 1, start_idx - 1, -1):
        if not people[i]:
            continue
        c = _center(box)
        box = min(people[i], key=lambda b: abs(_center(b)[0] - c[0]) + abs(_center(b)[1] - c[1]))
        track.append((i, box))
    return track[::-1]


def departures(times: list[float], people: list[list[list[float]]],
               min_empty_sec: float = 1.5, workplace: list[float] | None = None) -> list[Departure]:
    """Episodes where the room becomes empty (for >= min_empty_sec, or until the end)
    after someone was present. Onset = when that person stood up / walked off."""
    out = []
    i, n = 0, len(times)
    while i < n:
        if people[i]:
            i += 1
            continue
        j = i
        while j < n and not people[j]:
            j += 1
        empty_long = (j == n) or (times[j - 1] - times[i] >= min_empty_sec)
        last = i - 1
        if empty_long and last >= 0 and people[last]:
            start = last
            while start > 0 and times[last] - times[start - 1] <= LOOKBACK_SEC:
                start -= 1
            track = _follow(people, last, start)
            if len(track) >= 4:
                k, _ = _leaving_onset(times, track, workplace)
                box = next(b for idx, b in track if idx == k)
                out.append(Departure(times[k], times[i], box))
        i = j
    return out


def sustained(times: list[float], flags: list[bool], min_sec: float,
              max_gap: int = 1) -> list[tuple[float, float]]:
    """Intervals where flags stay True for at least min_sec (gaps of up to max_gap
    frames, e.g. a missed detection, are bridged)."""
    flags = list(flags)
    for i in range(len(flags)):
        if not flags[i] and any(flags[max(0, i - max_gap):i]) and any(flags[i + 1:i + 1 + max_gap]):
            flags[i] = True
    out, start = [], None
    for t, f in zip(times + [None], flags + [False]):
        if f and start is None:
            start = t
        elif not f and start is not None:
            end = prev
            if end - start >= min_sec:
                out.append((start, end))
            start = None
        prev = t
    return out

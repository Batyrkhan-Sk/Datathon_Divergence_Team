"""Teller leaves the workplace -> cash_unattended and/or workstation_unlocked.

Departure = the room becomes empty after someone was at the workplace (laptop area).
Onset (timecode) = the last moment the teller was at the workplace, which matches how
the training labels are placed (the moment she gets up).
"""
import numpy as np

from .. import scene
from ..events import Event
from ..perception import zeroshot
from . import Context, register

# Money must be seen in >= 2 of the checked frames (score >= MONEY_HIT), or once strongly.
MONEY_HIT = 0.08
# Without a laptop the desk zone is only estimated from the teller's position, so it is
# wider and less certain: weak hits there are not enough (clean X-23: 0.09 at the zone edge).
MONEY_HIT_NO_LAPTOP = 0.15
MONEY_STRONG = 0.25
MONEY_CHECK_OFFSETS = (0.5, 1.5, 2.5)   # seconds after the room became empty
# Unlocked screen = bright, bluish-white working app (spreadsheet). Calibrated on X-28/X-11
# vs 9 locked/off cases; re-check on new footage.
SCREEN_MIN_BRIGHTNESS = 125
SCREEN_MIN_BLUE_MINUS_RED = 15
CHECK_AFTER_EMPTY_SEC = 1.0


def _frame_at(ctx: Context, t: float):
    return min(ctx.frames, key=lambda tf: abs(tf[0] - t))


def _desk_region(teller_box, laptop, w, h):
    x1, y1 = min(teller_box[0], laptop[0]), min(teller_box[1], laptop[1])
    x2, y2 = max(teller_box[2], laptop[2]), max(teller_box[3], laptop[3])
    mx, my = 0.3 * (x2 - x1), 0.3 * (y2 - y1)
    return [max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y2 + my)]


def screen_unlocked(frame, laptop) -> bool:
    x1, y1, x2, y2 = (int(v) for v in laptop)
    screen = frame[y1:y1 + max(1, (y2 - y1) // 2), x1:x2].astype(float)
    if screen.size == 0:
        return False
    b, r = screen[..., 0].mean(), screen[..., 2].mean()
    brightness = screen.max(axis=2).mean()
    return brightness >= SCREEN_MIN_BRIGHTNESS and b - r >= SCREEN_MIN_BLUE_MINUS_RED


@register("workplace")
def detect(ctx: Context) -> list[Event]:
    # Workplace = the laptop, or (no laptop in view, e.g. another camera angle) where the
    # teller sits most of the time. The screen check needs a real laptop.
    laptop = ctx.extras.get("laptop")
    anchor = ctx.extras.get("workplace") or laptop
    if anchor is None:
        return []
    h, w = ctx.info.height, ctx.info.width
    events = []
    for dep in scene.departures(ctx.extras["times"], ctx.extras["people"], workplace=anchor):
        t_frame, frame = _frame_at(ctx, dep.t_room_empty + CHECK_AFTER_EMPTY_SEC)
        left = (f"Кассир покинул рабочее место ({dep.t_left_desk:.0f} с) и вышел из "
                f"помещения ({dep.t_room_empty:.0f} с)")
        # Evidence: leaving the workstation (onset), walking out, then the state left behind.
        t_exit = dep.t_room_empty - 1.0
        exit_frames = [t_exit] if t_exit > dep.t_left_desk + 0.5 else []

        desk = _desk_region(dep.teller_box, anchor, w, h)
        if laptop is not None:
            desk_level = laptop[1] - 0.25 * (laptop[3] - laptop[1])  # money lies on the desk
        else:  # seated teller: the desk top is roughly at mid-torso
            desk_level = anchor[1] + 0.5 * (anchor[3] - anchor[1])
        min_hit = MONEY_HIT if laptop is not None else MONEY_HIT_NO_LAPTOP
        hits, seen = [], set()
        for off in MONEY_CHECK_OFFSETS:
            tm, fm = _frame_at(ctx, dep.t_room_empty + off)
            if tm in seen:  # near the end of the video offsets map to the same frame
                continue
            seen.add(tm)
            m = zeroshot.find_money(fm, desk)
            if m and m["score"] >= min_hit and (m["box"][1] + m["box"][3]) / 2 >= desk_level:
                hits.append((tm, m))
        if hits and (len(hits) >= 2 or max(m["score"] for _, m in hits) >= MONEY_STRONG):
            tm, money = max(hits, key=lambda h: h[1]["score"])
            events.append(Event(
                "cash_unattended", dep.t_left_desk,
                confidence=min(0.95, 0.55 + money["score"]),
                # The detector matches object classes, so describe what it looks like rather
                # than asserting what it is (X-24: green cylinders matched "coin roll").
                observation=(f"{left}; на столе без присмотра остались предметы, похожие на "
                             f"ценности ({money['what']})"),
                evidence_times=exit_frames + [tm],
                boxes={tm: [(*money["box"], money["what"])]},
            ))

        if laptop is not None and screen_unlocked(frame, laptop):
            events.append(Event(
                "workstation_unlocked", dep.t_left_desk, confidence=0.6,
                observation=f"{left}; экран ноутбука остаётся включённым с открытым "
                            f"рабочим приложением (не заблокирован)",
                evidence_times=exit_frames + [t_frame],
                boxes={t_frame: [(*laptop, "экран")]},
            ))
    return events

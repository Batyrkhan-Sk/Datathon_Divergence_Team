"""Food/drink or personal belongings at the cash workplace -> personal_items.

RT-DETR "cup"/"bottle" is reliable here (>= 2 s only in X-46, at most 1 frame in clean
videos). Its "handbag"/"cell phone" classes are not usable: they fire on the counting
machine and the desk telephone.
"""
import os

import numpy as np

from .. import scene
from ..events import Event
from . import Context, register

DRINK_LABELS = {"cup", "bottle"}
MIN_SCORE = 0.4
MIN_SECONDS = 2.0
# A static, weak "cup" is usually a hand or desk item (clean X-35: hand at the desk edge,
# max 0.50, box fixed). Accept if confident once, or if the cup moves (drinking, X-46).
STRONG_SCORE = 0.55
MIN_MOVE_PX = 10


BELONGINGS_Q = "Is there a coat, jacket, handbag or backpack lying on this desk?"
# Items placed on the desk stay there (X-40: >= 0.99 to the end); clean false hits are brief
# (X-12: two samples, then gone) or weak (X-16: <= 0.78).
BELONGINGS_P = 0.9
BELONGINGS_SAMPLE_SEC = 3.0
BELONGINGS_MIN_HITS = 3     # consecutive samples ...
BELONGINGS_MIN_HITS_AT_END = 2  # ... or fewer if they run to the end of the video
BELONGINGS_BASELINE = 2     # first samples must be clear: the item has to *appear*
# Cash-collection bags here are green sacks. Long, specific wording scored 0 on X-17; the
# simple question separates X-17 (1.0) from the coat and handbag in X-40 (0.0).
CASH_BAG_Q = "Is there a green bag on the desk?"
CASH_BAG_P = 0.6


def _desk_crop_box(ctx: Context):
    laptop = ctx.extras.get("laptop")
    boxes = [max(p, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) for p in ctx.extras["people"] if p]
    if laptop is None or not boxes:
        return None
    t = np.median(np.array(boxes), axis=0)
    x1, y1 = min(t[0], laptop[0]), min(t[1], laptop[1])
    x2, y2 = max(t[2], laptop[2]), max(t[3], laptop[3])
    mx, my = 0.3 * (x2 - x1), 0.3 * (y2 - y1)
    return [max(0, x1 - mx), max(0, y1 - my), min(ctx.info.width, x2 + mx),
            min(ctx.info.height, y2 + my)]


def _belongings(ctx: Context) -> list[Event]:
    """VLM on the desk crop: a coat or bag newly placed on the desk (X-40)."""
    if os.environ.get("ML_USE_VLM") != "1":
        return []
    from ..perception import vlm
    box = _desk_crop_box(ctx)
    if box is None:
        return []
    times = ctx.extras["times"]
    step = max(1, round(BELONGINGS_SAMPLE_SEC * len(times) / max(1e-6, times[-1] - times[0])))
    samples = [(t, vlm.p_yes(vlm.crop(f, box, pad=0.0), BELONGINGS_Q))
               for t, f in ctx.frames[::step]]
    if len(samples) <= BELONGINGS_BASELINE or any(p >= BELONGINGS_P for _, p in samples[:BELONGINGS_BASELINE]):
        return []
    for k in range(BELONGINGS_BASELINE, len(samples)):
        run = 0
        while k + run < len(samples) and samples[k + run][1] >= BELONGINGS_P:
            run += 1
        to_end = k + run == len(samples)
        if run >= BELONGINGS_MIN_HITS or (to_end and run >= BELONGINGS_MIN_HITS_AT_END):
            t, t_ev = samples[k][0], samples[k + 1][0]
            frame = min(ctx.frames, key=lambda tf: abs(tf[0] - t_ev))[1]
            # A cash-collection bag is not a personal item (X-17): report it as a collector
            # handover and describe only what is visible.
            if vlm.p_yes(vlm.crop(frame, box, pad=0.0), CASH_BAG_Q) >= CASH_BAG_P:
                return [Event(
                    "collector_handover", t, confidence=0.55,
                    observation=(f"С {t:.0f} с на столе кассира лежит сумка, по виду "
                                 f"инкассаторская; проверьте по записи, осмотрены ли целостность "
                                 f"сумки и пломба"),
                    evidence_times=[t_ev],
                    boxes={t_ev: [(*box, "сумка")]},
                )]
            return [Event(
                "personal_items", t, confidence=0.6,
                observation=(f"С {t:.0f} с на кассовом столе лежат вещи, похожие на личные "
                             f"(верхняя одежда и/или сумка), которых не было в начале записи"),
                evidence_times=[t_ev],
                boxes={t_ev: [(*box, "личные вещи")]},
            )]
    return []


@register("personal_items")
def detect(ctx: Context) -> list[Event]:
    return _drinks(ctx) + _belongings(ctx)


def _drinks(ctx: Context) -> list[Event]:
    times, dets = ctx.extras["times"], ctx.extras["objects"]
    found = [[d for d in f if d["label"] in DRINK_LABELS and d["score"] >= MIN_SCORE]
             for f in dets]
    boxes = [[d["box"] for d in f] for f in found]
    events = []
    for start, end in scene.sustained(times, [bool(b) for b in boxes], MIN_SECONDS):
        span = [k for k, t in enumerate(times) if start <= t <= end and found[k]]
        best = max(d["score"] for k in span for d in found[k])
        ys = [(d["box"][1] + d["box"][3]) / 2 for k in span for d in found[k]]
        if best < STRONG_SCORE and max(ys) - min(ys) < MIN_MOVE_PX:
            continue
        i = span[0]
        events.append(Event(
            "personal_items", start, t_end=end, confidence=0.6,
            observation=(f"На рабочем месте кассира находится посуда для напитков/еды "
                         f"(чашка или бутылка), видна с {start:.0f} по {end:.0f} с"),
            evidence_times=[min(end, start + 1.5)],
            boxes={times[i]: [(*b, "чашка") for b in boxes[i]]},
        ))
    return events

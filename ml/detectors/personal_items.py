"""Food/drink or personal belongings at the cash workplace -> personal_items.

RT-DETR "cup"/"bottle" is reliable here (>= 2 s only in X-46, at most 1 frame in clean
videos). Its "handbag"/"cell phone" classes are not usable: they fire on the counting
machine and the desk telephone.
"""
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


@register("personal_items")
def detect(ctx: Context) -> list[Event]:
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
            observation=(f"На рабочем месте кассира находится посуда с напитком/едой "
                         f"(чашка или бутылка), видна с {start:.0f} по {end:.0f} с; "
                         f"рядом находятся наличные или кассовое оборудование"),
            evidence_times=[min(end, start + 1.5)],
            boxes={times[i]: [(*b, "чашка") for b in boxes[i]]},
        ))
    return events

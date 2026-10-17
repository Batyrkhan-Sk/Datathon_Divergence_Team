"""Per-second signal timeline for the UI player strip.

Returns a compact representation of what the pipeline "sees" at each second:
people count, cash detected, laptop present, safe state. The frontend renders
this as a colour-coded strip under the video scrubber.

The timeline is cheap to generate (reuses ctx.extras) and adds no analysis cost.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class TimelineFrame:
    t: float
    people: int
    has_laptop: bool
    has_cash: bool
    violations: list[str]   # type_ids active at this second


def build(ctx, violations: list[dict]) -> list[dict]:
    """Build timeline from pipeline context + final violations list.

    Returns a JSON-serialisable list of {t, people, laptop, cash, violations}.
    """
    times = ctx.extras.get("times") or []
    people = ctx.extras.get("people") or []
    objects_per_frame = ctx.extras.get("objects") or []
    laptop_box = ctx.extras.get("laptop")

    frames = []
    for i, t in enumerate(times):
        n_people = len(people[i]) if i < len(people) else 0
        has_laptop = laptop_box is not None

        # cash: look for money detections in objects (if OWL results were stored)
        has_cash = False
        if i < len(objects_per_frame):
            for d in objects_per_frame[i]:
                if d.get("label", "").lower() in ("banknotes", "coin roll", "green cash bag",
                                                   "stack of money", "paper money on a table"):
                    has_cash = True
                    break

        # which violations are active at time t
        active_vio = [
            v["type_id"] for v in violations
            if isinstance(v, dict)
            and v.get("timecode_sec") is not None
            and abs(v["timecode_sec"] - t) <= 4.0
        ]

        frames.append({
            "t": round(t, 2),
            "people": n_people,
            "laptop": has_laptop,
            "cash": has_cash,
            "violations": active_vio,
        })

    return frames

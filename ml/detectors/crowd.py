"""Unauthorized presence in the cash room -> unauthorized_access.

1. Crowd: >= 3 people for >= 5 s. Normal service has at most two (teller and client);
   clean training videos only show short bursts of a third detection (<= ~4 s).
2. Entry into a solo room: in a room where the teller normally works alone (median
   people count = 1), a second person *enters* and stays >= 4 s. A second person present
   from the very start (e.g. a colleague, clean X-14) is not an entry.
"""
import numpy as np

from .. import scene
from ..events import Event
from . import Context, register

MIN_PEOPLE = 3
MIN_SECONDS = 5.0
# The third person is first counted while still in the doorway; report the moment the
# entry is complete (X-18: first counted 16 s, walks in ~18 s, label 20 s).
CROWD_ONSET_SEC = 2.0
ENTRY_MIN_SECONDS = 4.0
ENTRY_MIN_AT_END_SEC = 2.5
ENTRY_SOLO_BEFORE_SEC = 3.0


def _solo_room_entries(times, people) -> list[Event]:
    counts = [len(p) for p in people]
    if not counts or np.median(counts) > 1:
        return []
    events = []
    # Shorter minimum when the presence lasts until the video ends (clip cut off, X-33).
    for start, end in scene.sustained(times, [c >= 2 for c in counts], ENTRY_MIN_AT_END_SEC):
        if end < times[-1] and end - start < ENTRY_MIN_SECONDS:
            continue
        before = [c for t, c in zip(times, counts) if start - ENTRY_SOLO_BEFORE_SEC <= t < start]
        if not before or max(before) >= 2 or sum(before) == 0:
            continue  # not an entry: two people already there, or nobody before
        i = times.index(start)
        arrived = _teller_arrival(times, counts, start)
        if arrived is not None:
            # Room was empty at the start: the teller came in and the door stayed passable,
            # so the violation starts at her arrival (X-33: label 6 s, outsider at 10.5 s).
            onset = arrived
            text = (f"Кассир вошла в помещение кассы ({arrived:.0f} с), после чего в помещение "
                    f"вошло второе лицо ({start:.0f} с) и находилось там {end - start:.0f} с: "
                    f"вход в кассу не был закрыт")
        else:
            onset = start
            text = (f"Во время работы кассира в помещение кассы вошло второе лицо "
                    f"({start:.0f} с) и находилось там {end - start:.0f} с")
        events.append(Event(
            "unauthorized_access", onset, t_end=end, confidence=0.55, observation=text,
            evidence_times=[start, min(end, start + 2.0)],
            boxes={start: [(*b, "человек") for b in people[i]]},
        ))
    return events


def _teller_arrival(times, counts, before):
    """If the room is empty at the start (>= 1.5 s, so one missed detection does not count),
    the time the first person settles in (present for >= 2 s) before `before`; else None."""
    empty_start = [c == 0 for t, c in zip(times, counts) if t - times[0] < 1.5]
    if not empty_start or not all(empty_start):
        return None
    for start, end in scene.sustained(times, [c >= 1 for c in counts], 2.0):
        if start < before:
            return start
    return None


@register("crowd")
def detect(ctx: Context) -> list[Event]:
    times, people = ctx.extras["times"], ctx.extras["people"]
    flags = [len(p) >= MIN_PEOPLE for p in people]
    events = _solo_room_entries(times, people)
    for start, end in scene.sustained(times, flags, MIN_SECONDS):
        onset = min(end, start + CROWD_ONSET_SEC)
        i = min(range(len(times)), key=lambda k: abs(times[k] - onset))
        events.append(Event(
            "unauthorized_access", onset, t_end=end, confidence=0.6,
            observation=(f"В помещении кассы одновременно находятся {len(people[i])} человека "
                         f"в течение {end - start:.0f} с (с {start:.0f} по {end:.0f} с): помимо "
                         f"кассира и клиента в помещении находится ещё как минимум один человек"),
            evidence_times=[min(end, onset + 1.0)],
            boxes={times[i]: [(*b, "человек") for b in people[i]]},
        ))
    return events

"""Safe left open, or key left in the lock -> safe_left_open.

No detector can find the safe (feasibility), so the VLM locates it once per video and
then answers yes/no questions on a zoomed crop of it every SAMPLE_SEC.
- Open: the door stays open for >= OPEN_MIN_SECONDS. A safe is opened briefly to take or
  put cash (clean X-21: one sample); "is someone near" cannot be used because in some
  layouts the seated teller overlaps the safe in the image.
- Key: a key is seen in the lock while nobody is near the safe, or when the room is empty.
Runs only when the VLM is enabled (env ML_USE_VLM=1); otherwise returns nothing.
"""
import os

from .. import scene
from ..events import Event
from . import Context, register

SAMPLE_SEC = 2.0
P_OPEN = 0.6
P_KEY = 0.6
OPEN_MIN_SECONDS = 6.0
OPEN_ONSET_SEC = 2.0
KEY_LEAVE_SEC = 15.0
SAFE_NAMES = "grey metal safe (a small steel cabinet with a lock)"


def _near(person, safe, margin=0.5):
    w, h = safe[2] - safe[0], safe[3] - safe[1]
    return not (person[2] < safe[0] - margin * w or person[0] > safe[2] + margin * w or
                person[3] < safe[1] - margin * h or person[1] > safe[3] + margin * h)


@register("safe")
def detect(ctx: Context) -> list[Event]:
    if os.environ.get("ML_USE_VLM") != "1":
        return []
    from ..perception import vlm

    times, people = ctx.extras["times"], ctx.extras["people"]
    safe = None
    for t, frame in ctx.frames[:: max(1, len(ctx.frames) // 4)][:4]:
        safe = vlm.locate(frame, SAFE_NAMES)
        if safe:
            break
    if not safe:
        return []
    ctx.extras["safe"] = safe

    step = max(1, round(SAMPLE_SEC * len(times) / max(1e-6, times[-1] - times[0] + 1e-6)))
    samples = []  # (t, p_open, p_key, someone_near)
    for k in range(0, len(ctx.frames), step):
        t, frame = ctx.frames[k]
        crop = vlm.crop(frame, safe, pad=0.25)
        near = any(_near(p, safe) for p in people[k])
        samples.append((t, vlm.p_yes(crop, "Is the door of this metal safe open?"),
                        vlm.p_yes(crop, "Is a key inserted in the lock of this safe?"), near))
    ctx.extras["safe_samples"] = samples

    events = []
    ts = [s[0] for s in samples]
    for start, end in scene.sustained(ts, [s[1] >= P_OPEN for s in samples], OPEN_MIN_SECONDS):
        onset = min(end, start + OPEN_ONSET_SEC)  # the moment it has clearly been left open
        events.append(Event(
            "safe_left_open", onset, t_end=end, confidence=0.75,
            observation=(f"Дверца сейфа остаётся открытой в течение {end - start:.0f} с "
                         f"(с {start:.0f} по {end:.0f} с)"),
            evidence_times=[min(end, onset + 2.0)],
            boxes={onset: [(*safe, "сейф открыт")]},
        ))
    # Key: a key left in the lock is only a few pixels (X-22), so the VLM cannot see it once
    # the hand is gone (single-image and before/after questions both failed). The fallback
    # "worked the lock with a key, then left" also fires on clean X-12/X-25 (proper locking
    # looks the same), so it is OFF by default: documented limitation.
    if os.environ.get("ML_SAFE_KEY_RULE") != "1":
        return events
    key_times = [s[0] for s in samples if s[2] >= P_KEY]
    for dep in scene.departures(times, people):
        used = [t for t in key_times if 0 <= dep.t_room_empty - t <= KEY_LEAVE_SEC]
        if not used:
            continue
        t_empty = dep.t_room_empty
        events.append(Event(
            "safe_left_open", dep.t_left_desk, confidence=0.6,
            observation=(f"Кассир открывал(а) замок сейфа ключом ({used[0]:.0f} с), затем "
                         f"покинул(а) помещение ({t_empty:.0f} с); на кадре после ухода в замке "
                         f"сейфа виден ключ"),
            evidence_times=[used[0], t_empty + 1.0],
            boxes={t_empty + 1.0: [(*safe, "замок сейфа")]},
        ))
    return events

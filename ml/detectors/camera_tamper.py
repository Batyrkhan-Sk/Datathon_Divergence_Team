"""Camera tamper detector — reports when the camera appears to be covered,
blacked out, defocused beyond normal, or physically shifted.

These are separate from the regular violation types; the type_id is
"camera_tamper" with a sub-code in the observation text.
"""
from .. import tamper
from ..events import Event
from . import Context, register

_CONFIDENCE = 0.70


@register("camera_tamper")
def detect(ctx: Context) -> list[Event]:
    times = ctx.extras.get("times") or []
    frames = [f for _, f in ctx.frames]
    if not times or not frames:
        return []

    # Use the first stable frame as the NCC reference (avoid the very first
    # which may be a cut or a transition).
    ref_idx = min(2, len(frames) - 1)
    events = tamper.detect_tamper(times, frames, ref_frame=frames[ref_idx])

    result = []
    for ev in events:
        duration = ev.t_end - ev.t_start
        observation = (
            f"{ev.kind.label}: с {ev.t_start:.0f} по {ev.t_end:.0f} с "
            f"({duration:.0f} с)."
        )
        result.append(Event(
            type_id="camera_tamper",
            t_start=ev.t_start,
            t_end=ev.t_end,
            confidence=_CONFIDENCE,
            observation=observation,
            evidence_times=[ev.t_start, min(ev.t_end, ev.t_start + 2.0)],
        ))
    return result

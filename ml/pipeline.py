"""analyze(video) -> result dict in the API format.

    python -m ml.pipeline data/raw/X-26.mov          # prints JSON (images truncated)
"""
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

import cv2

from . import catalog, checks, evidence, scene
from .detectors import DETECTORS, Context
from .events import Event
from .perception import objects, zeroshot
from .video import iter_frames, probe

SAMPLE_FPS = 2.0
MIN_CONFIDENCE = 0.5      # tune on eval; keep low — a missed violation is worse than a FP
MERGE_WINDOW_SEC = 8.0    # same-type events closer than this are one violation (X-46: 10.5 + 16 s)


def _merge(events: list[Event]) -> list[Event]:
    events = sorted(events, key=lambda e: (e.type_id, e.t_start))
    merged: list[Event] = []
    for e in events:
        last = merged[-1] if merged else None
        if last and last.type_id == e.type_id and e.t_start - last.t_start <= MERGE_WINDOW_SEC:
            if e.confidence > last.confidence:
                merged[-1] = e
            continue
        merged.append(e)
    return sorted(merged, key=lambda e: e.t_start)


def _describe(event: Event, rule: dict | None) -> str:
    text = event.observation.strip() or "Зафиксированы признаки возможного нарушения."
    if not text.endswith("."):
        text += "."
    if rule:
        text += f' Возможное нарушение: {rule.get("short", rule["document"])}, {rule["clause"]}.'
    return text


def warmup() -> None:
    """Load all models once (called by the backend worker at start-up)."""
    objects.warmup()
    zeroshot.warmup()
    if os.environ.get("ML_USE_VLM") == "1":
        from .perception import vlm
        vlm.warmup()


def _cached_objects(ctx: Context) -> list[list[dict]] | None:
    """Development shortcut: reuse detections from eval/cache_detections.py when the
    env var ML_OBJECTS_CACHE points to that folder. Never set in production."""
    folder = os.environ.get("ML_OBJECTS_CACHE")
    path = Path(folder) / f"{Path(ctx.info.path).stem}.json" if folder else None
    if not path or not path.exists():
        return None
    cached = json.loads(path.read_text(encoding="utf-8"))["frames"]
    return [min(cached, key=lambda f: abs(f["t"] - t))["dets"] for t, _ in ctx.frames]


def perceive(ctx: Context) -> None:
    """Shared perception for all detectors, stored in ctx.extras."""
    dets = _cached_objects(ctx) or objects.detect([f for _, f in ctx.frames])
    ctx.extras["times"] = [t for t, _ in ctx.frames]
    ctx.extras["objects"] = dets
    ctx.extras["people"] = [scene.people_in_room(d, ctx.info.height) for d in dets]
    ctx.extras["laptop"] = scene.laptop_box(dets)
    if os.environ.get("ML_IGNORE_LAPTOP") == "1":  # test switch: simulate a hidden laptop
        ctx.extras["laptop"] = None
    # Workplace anchor: the laptop if visible, otherwise where the teller sits most of the
    # time (a new camera angle may hide the laptop; detectors must keep working).
    if ctx.extras["laptop"] is not None:
        ctx.extras["workplace"], ctx.extras["workplace_source"] = ctx.extras["laptop"], "laptop"
    else:
        ctx.extras["workplace"] = scene.teller_anchor(ctx.extras["people"], ctx.info.width,
                                                      ctx.info.height)
        ctx.extras["workplace_source"] = "teller" if ctx.extras["workplace"] else None


def analyze(video_path: str, progress: Callable[[float], None] | None = None,
            rules_path: str | None = None) -> dict:
    started = time.time()
    report = progress or (lambda p: None)
    info = probe(video_path)

    report(0.05)
    frames = list(iter_frames(video_path, SAMPLE_FPS))
    ctx = Context(info=info, frames=frames)
    report(0.15)
    perceive(ctx)
    report(0.3)

    events: list[Event] = []
    for i, (name, detect) in enumerate(DETECTORS.items()):
        events.extend(detect(ctx))
        report(0.3 + 0.6 * (i + 1) / max(1, len(DETECTORS)))
    events = _merge([e for e in events if e.confidence >= MIN_CONFIDENCE])

    violations = []
    for e in events:
        rule = catalog.citation(e.type_id, rules_path)
        violations.append({
            "type": catalog.type_name(e.type_id, rules_path),
            "type_id": e.type_id,
            "timecode_sec": round(e.t_start, 2),
            "confidence": round(e.confidence, 3),
            "description": _describe(e, rule),
            "rule": rule,
            "evidence_frames": evidence.frames_for(video_path, e, info.duration),
        })
    try:
        scene_view = _scene(ctx)
    except Exception:  # an explanatory extra must never break the result
        scene_view = None
    try:
        checklist = checks.build(ctx, events)
    except Exception:
        checklist = None
    report(1.0)
    result = {
        "verdict": "violation" if violations else "no_violation",
        "violations": violations,
        "processing_sec": round(time.time() - started, 2),
    }
    if scene_view:
        result["scene"] = scene_view
    if checklist:
        result["checks"] = checklist
    return result


SCENE_COLORS = {"Рабочее место (ноутбук)": (60, 180, 60),
                "Рабочее место (по положению кассира)": (60, 180, 60), "Зона стола": (220, 140, 40),
                "Сейф": (0, 140, 255), "Человек": (230, 230, 230)}


def _scene(ctx: Context) -> dict | None:
    """One frame showing what the service found in this room (workplace, desk, safe,
    people). Explains results to the reviewer and shows that zones are derived from the
    video itself rather than fixed coordinates."""
    from .detectors.personal_items import _desk_crop_box
    times, people = ctx.extras.get("times") or [], ctx.extras.get("people") or []
    if not times:
        return None
    present = [k for k, p in enumerate(people) if p] or list(range(len(times)))
    k = present[len(present) // 2]
    t, frame = ctx.frames[k]
    objects = []
    if ctx.extras.get("laptop"):
        objects.append(("Рабочее место (ноутбук)", ctx.extras["laptop"]))
    elif ctx.extras.get("workplace"):
        objects.append(("Рабочее место (по положению кассира)", ctx.extras["workplace"]))
    desk = _desk_crop_box(ctx)
    if desk:
        objects.append(("Зона стола", desk))
    if ctx.extras.get("safe"):
        objects.append(("Сейф", ctx.extras["safe"]))
    objects += [("Человек", b) for b in people[k]]
    img = frame.copy()
    # Boxes only: text tags overlap in a crowded room;
    # the UI legend explains the colours.
    for label, (x1, y1, x2, y2) in objects:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), SCENE_COLORS[label], 2,
                      cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None
    return {"timestamp_sec": round(t, 2),
            "image_base64": base64.b64encode(buf.tobytes()).decode("ascii"),
            "objects": [{"label": lbl, "box": [round(float(v), 1) for v in b]}
                        for lbl, b in objects]}


def _truncate_images(result: dict) -> dict:
    for v in result["violations"]:
        for f in v["evidence_frames"]:
            f["image_base64"] = f["image_base64"][:40] + "..."
    if "scene" in result:
        result["scene"]["image_base64"] = result["scene"]["image_base64"][:40] + "..."
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1251
    res = analyze(sys.argv[1])
    print(json.dumps(_truncate_images(res), ensure_ascii=False, indent=2))

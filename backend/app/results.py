"""Result normalisation (so the jury never gets an invalid result) and API rendering."""
import base64
import binascii
import math
import re

import cv2
import numpy as np

from ml import catalog
from ml.video import probe, read_frame_at

MAX_FRAMES = 3
JPEG_QUALITY = 85
_DATA_URI = re.compile(r"^data:[^,]*,", re.IGNORECASE)

DOC_VIOLATION = ("type", "timecode_sec", "description", "evidence_frames")
DOC_FRAME = ("timestamp_sec", "image_base64")


def _num(value, default: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _clamp(t: float, duration: float) -> float:
    t = max(0.0, t)
    return round(min(t, duration) if duration > 0 else t, 2)


def _encode(frame: np.ndarray) -> str | None:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


def as_jpeg_base64(value) -> str | None:
    """Raw base64 JPEG (no data-URI prefix); other image formats are re-encoded."""
    if not isinstance(value, str):
        return None
    s = "".join(_DATA_URI.sub("", value.strip()).split())
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        return None
    if raw[:2] == b"\xff\xd8":
        return base64.b64encode(raw).decode("ascii")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    return _encode(img) if img is not None else None


def frame_at(video_path: str, t: float, duration: float) -> dict:
    """Evidence frame extracted from the video; a placeholder if decoding fails."""
    t = _clamp(t, max(0.0, duration - 0.05))
    for at in (t, 0.0):
        img = read_frame_at(video_path, at)
        if img is not None and (b64 := _encode(img)):
            return {"timestamp_sec": round(at, 2), "image_base64": b64}
    img = np.full((240, 320, 3), 128, np.uint8)
    return {"timestamp_sec": t, "image_base64": _encode(img)}


def normalize(raw: dict, video_path: str) -> dict:
    """Make the analyzer output satisfy the contract: verdict == bool(violations),
    every violation has type, timecode in [0, duration], description, 1-3 JPEG frames."""
    try:
        duration = probe(video_path).duration
    except ValueError:
        duration = 0.0
    raw = raw if isinstance(raw, dict) else {}
    violations = []
    for v in raw.get("violations") or []:
        if not isinstance(v, dict):
            continue
        type_id = str(v.get("type_id") or "").strip()
        vtype = str(v.get("type") or "").strip() or catalog.type_name(type_id)
        tc = _clamp(_num(v.get("timecode_sec"), 0.0), duration)
        desc = str(v.get("description") or "").strip() or (
            f"{vtype}: признаки возможного нарушения на {tc:.1f} с.")
        frames = []
        for f in v.get("evidence_frames") or []:
            if len(frames) == MAX_FRAMES:
                break
            if isinstance(f, dict) and (b64 := as_jpeg_base64(f.get("image_base64"))):
                ts = _clamp(_num(f.get("timestamp_sec"), tc), duration)
                frames.append({"timestamp_sec": ts, "image_base64": b64})
        if not frames:
            frames.append(frame_at(video_path, tc, duration))

        out = {"type": vtype, "timecode_sec": tc, "description": desc, "evidence_frames": frames}
        if type_id:
            out["type_id"] = type_id
        if "confidence" in v:
            out["confidence"] = round(min(max(_num(v["confidence"], 0.0), 0.0), 1.0), 3)
        if "rule" in v:
            out["rule"] = v["rule"] if isinstance(v["rule"], dict) else None
        violations.append(out)

    violations.sort(key=lambda x: x["timecode_sec"])
    result = {"verdict": "violation" if violations else "no_violation", "violations": violations}
    if "processing_sec" in raw:
        result["processing_sec"] = round(_num(raw["processing_sec"], 0.0), 2)
    scene = raw.get("scene")
    if isinstance(scene, dict) and (b64 := as_jpeg_base64(scene.get("image_base64"))):
        result["scene"] = {"timestamp_sec": _clamp(_num(scene.get("timestamp_sec"), 0.0), duration),
                           "image_base64": b64,
                           "objects": [o for o in scene.get("objects") or [] if isinstance(o, dict)]}
    return result


def render(job, strict: bool, queue_position: int = 0) -> dict:
    """Public JSON for a job: documented keys first, extras after (none when strict)."""
    status = {"queued": "processing", "running": "processing"}.get(job.status, job.status)
    body = {"job_id": job.id, "status": status, "verdict": None, "violations": []}
    if job.status == "done" and job.result:
        body["verdict"] = job.result["verdict"]
        body["violations"] = job.result["violations"]
        if not strict and "processing_sec" in job.result:
            body["processing_sec"] = job.result["processing_sec"]
        if not strict and "scene" in job.result:
            body["scene"] = job.result["scene"]
    elif status == "processing" and not strict:
        body["progress"] = round(job.progress, 3)
        body["queue_position"] = queue_position
    elif job.status == "failed" and not strict:
        body["error"] = job.error or "processing failed"
    if strict:
        body["violations"] = [
            {k: v[k] for k in DOC_VIOLATION}
            | {"evidence_frames": [{k: f[k] for k in DOC_FRAME} for f in v["evidence_frames"]]}
            for v in body["violations"]]
    return body

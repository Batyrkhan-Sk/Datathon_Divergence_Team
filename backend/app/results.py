"""Validate analyzer results, extract source evidence and render the jury API."""
import base64
import binascii
import math
import re
from numbers import Real

import cv2
import numpy as np

from ml.video import probe, read_frame_with_timestamp

MAX_FRAMES = 3
JPEG_QUALITY = 85
_DATA_URI = re.compile(r"^data:[^,]*,", re.IGNORECASE)

DOC_VIOLATION = ("type", "timecode_sec", "description", "evidence_frames")
DOC_FRAME = ("timestamp_sec", "image_base64")


class InvalidResult(ValueError):
    """The analyzer did not produce a complete, consistent result."""


class EvidenceUnavailable(ValueError):
    """The requested evidence cannot be decoded from the source video."""


def _required_number(value, field: str, minimum: float = 0.0,
                     maximum: float = math.inf) -> float:
    if (isinstance(value, bool) or not isinstance(value, Real)
            or not math.isfinite(value) or not minimum <= value <= maximum):
        raise InvalidResult(f"{field} must be a finite number within its valid range")
    return float(value)


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
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR) if raw else None
    return _encode(img) if img is not None else None


def frame_at(video_path: str, t: float, duration: float) -> dict:
    """Read actual source pixels; failure is never replaced with another moment."""
    t = _required_number(t, "evidence timestamp", maximum=duration)
    decoded = read_frame_with_timestamp(video_path, t)
    if decoded is None:
        raise EvidenceUnavailable("cannot decode the requested evidence frame")
    at, img = decoded
    if not math.isfinite(at) or not 0 <= at <= duration:
        raise EvidenceUnavailable("decoded evidence has an invalid timestamp")
    b64 = _encode(img)
    if b64 is None:
        raise EvidenceUnavailable("cannot encode the decoded evidence frame")
    return {"timestamp_sec": round(at, 4), "image_base64": b64}


def normalize(raw: dict, video_path: str) -> dict:
    """Reject unknown/error outputs and re-read evidence from the uploaded video.

    The worker catches these exceptions and stores status=failed, verdict=null.
    Analyzer-provided image bytes are not used as evidence of source content.
    """
    if not isinstance(raw, dict):
        raise InvalidResult("analyzer result must be an object")
    if raw.get("status", "done") != "done" or raw.get("error"):
        raise InvalidResult("analyzer did not report successful completion")
    verdict, entries = raw.get("verdict"), raw.get("violations")
    if verdict not in ("violation", "no_violation") or not isinstance(entries, list):
        raise InvalidResult("analyzer must return an explicit verdict and event list")
    if (verdict == "violation") != bool(entries):
        raise InvalidResult("verdict contradicts the event list")
    duration = probe(video_path).duration
    if not math.isfinite(duration) or duration <= 0:
        raise InvalidResult("source video duration is unavailable")
    violations = []
    for v in entries:
        if not isinstance(v, dict):
            raise InvalidResult("each event must be an object")
        type_id = str(v.get("type_id") or "").strip()
        vtype, desc = v.get("type"), v.get("description")
        if not isinstance(vtype, str) or not vtype.strip():
            raise InvalidResult("event type is missing")
        if not isinstance(desc, str) or not desc.strip():
            raise InvalidResult("observed event description is missing")
        vtype, desc = vtype.strip(), desc.strip()
        tc = _required_number(v.get("timecode_sec"), "event timecode", maximum=duration)
        source_frames = v.get("evidence_frames", [])
        if not isinstance(source_frames, list):
            raise InvalidResult("evidence frames must be a list")
        frames = []
        for f in source_frames:
            if len(frames) == MAX_FRAMES:
                break
            if not isinstance(f, dict):
                raise InvalidResult("each evidence reference must be an object")
            ts = _required_number(f.get("timestamp_sec"), "evidence timestamp", maximum=duration)
            frames.append(frame_at(video_path, ts, duration))
        if not frames:
            frames.append(frame_at(video_path, tc, duration))

        out = {"type": vtype, "timecode_sec": tc, "description": desc, "evidence_frames": frames}
        if type_id:
            out["type_id"] = type_id
        if "confidence" in v:
            out["confidence"] = round(_required_number(v["confidence"], "confidence", maximum=1.0), 3)
        if "rule" in v:
            out["rule"] = v["rule"] if isinstance(v["rule"], dict) else None
        violations.append(out)

    violations.sort(key=lambda x: x["timecode_sec"])
    result = {"verdict": verdict, "violations": violations}
    if "processing_sec" in raw:
        result["processing_sec"] = round(_required_number(raw["processing_sec"], "processing time"), 2)
    scene = raw.get("scene")
    if isinstance(scene, dict) and (b64 := as_jpeg_base64(scene.get("image_base64"))):
        result["scene"] = {"timestamp_sec": _clamp(_num(scene.get("timestamp_sec"), 0.0), duration),
                           "image_base64": b64,
                           "objects": [o for o in scene.get("objects") or [] if isinstance(o, dict)]}
    checks = raw.get("checks")
    if isinstance(checks, dict) and isinstance(checks.get("items"), list):
        result["checks"] = {"items": [i for i in checks["items"] if isinstance(i, dict)],
                            "manual": [m for m in checks.get("manual") or [] if isinstance(m, str)]}
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
        if not strict and "checks" in job.result:
            body["checks"] = job.result["checks"]
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

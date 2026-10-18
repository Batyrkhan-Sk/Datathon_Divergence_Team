"""Synthetic analyzer outputs for worker/API integrity tests. No models loaded."""
from ml.video import probe


def invalid(video_path, progress=None):
    return None


def clean(video_path, progress=None):
    return {"verdict": "no_violation", "violations": []}


def valid(video_path, progress=None):
    return {"verdict": "violation", "violations": [{
        "type": "Synthetic test event", "timecode_sec": 0.5,
        "description": "A generated test pattern is visible.",
        "evidence_frames": [{"timestamp_sec": 0.53, "image_base64": "untrusted bytes"}],
    }]}


def absent_frame(video_path, progress=None):
    raw = valid(video_path, progress)
    raw["violations"][0]["evidence_frames"][0]["timestamp_sec"] = probe(video_path).duration
    return raw


def invalid_then_valid(video_path, progress=None):
    global _calls
    _calls = globals().get("_calls", 0) + 1
    return invalid(video_path) if _calls == 1 else valid(video_path)

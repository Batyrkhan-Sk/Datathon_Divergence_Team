"""Analyzer stubs for the tests (ANALYZER=backend.tests.stubs:<name>)."""
import base64
import os
import time

import cv2
import numpy as np

from ml.video import probe


def slow_on_long_video(video_path: str, progress=None) -> dict:
    """Hangs on videos longer than 18 s (X-26), returns at once otherwise (X-29)."""
    if probe(video_path).duration > 18:
        time.sleep(120)
    return {"verdict": "no_violation", "violations": [], "processing_sec": 0.0}


def crash(video_path: str, progress=None) -> dict:
    os._exit(3)


def error(video_path: str, progress=None) -> dict:
    raise RuntimeError("detector exploded")


def _b64(ext: str) -> str:
    ok, buf = cv2.imencode(ext, np.zeros((16, 16, 3), np.uint8))
    return base64.b64encode(buf.tobytes()).decode("ascii")


def messy(video_path: str, progress=None) -> dict:
    """Output breaking every rule normalisation must repair."""
    jpg = _b64(".jpg")
    return {
        "verdict": "no_violation",                     # wrong: there are violations
        "violations": [
            {"type": "", "type_id": "cash_unattended", "timecode_sec": -5,
             "description": "", "evidence_frames": []},                     # 0 frames
            {"type": "X", "timecode_sec": 1e6, "description": "d", "confidence": 7,
             "evidence_frames": [{"timestamp_sec": 1, "image_base64": jpg}] * 5},
            {"type": "Y", "timecode_sec": "nan", "description": "d", "evidence_frames": [
                {"timestamp_sec": 2, "image_base64": "data:image/jpeg;base64," + jpg},
                {"timestamp_sec": 3, "image_base64": _b64(".png")},
                {"timestamp_sec": 4, "image_base64": "not base64!"}]},
            "garbage",
        ],
    }

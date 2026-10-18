"""Video decoding and sampling with exact timestamps.

Times come from the frames' own timestamps, not frame index / fps: phones record with a
variable frame rate (e.g. in low light), where index / fps drifts by seconds (format stress
test: 10.0 s became 6.5 s)."""
import subprocess
import math
from dataclasses import dataclass
from typing import Iterator

import cv2
import numpy as np


@dataclass
class VideoInfo:
    path: str
    fps: float
    n_frames: int
    width: int
    height: int
    container_duration: float | None = None  # from ffprobe when available

    @property
    def duration(self) -> float:
        if self.container_duration:
            return self.container_duration
        return self.n_frames / self.fps if self.fps else 0.0


def _container_duration(path: str) -> float | None:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=15)
        d = float(r.stdout.strip())
        return d if d > 0 else None
    except Exception:  # no ffprobe or unreadable: fall back to the header
        return None


def _timestamp(cap, idx: int, fps: float) -> float:
    ms = cap.get(cv2.CAP_PROP_POS_MSEC)
    return ms / 1000.0 if ms > 0 or idx == 0 else idx / fps


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"cannot open video: {path}")
    info = VideoInfo(
        path=path,
        fps=cap.get(cv2.CAP_PROP_FPS) or 30.0,
        n_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        container_duration=_container_duration(path),
    )
    cap.release()
    return info


def iter_frames(path: str, rate: float = 4.0) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (t_sec, BGR frame) at ~`rate` fps, decoding sequentially (no seeks): the
    first frame at or after each 1/rate step of the frames' own timestamps."""
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("sampling rate must be positive and finite")
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise ValueError("cannot open video for analysis")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        expected = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        period, next_t, idx = 1.0 / rate, 0.0, 0
        tol = 0.25 / fps
        while cap.grab():
            t = _timestamp(cap, idx, fps)
            idx += 1
            if t + tol < next_t:
                continue
            ok, frame = cap.retrieve()
            if not ok or frame is None:
                raise ValueError("cannot decode a sampled video frame")
            yield t, frame
            while next_t <= t + tol:
                next_t += period
        if idx == 0:
            raise ValueError("video contains no decodable frames")
        # Container counts may have small rounding differences. A substantial
        # shortfall must not turn a partially read video into a clean verdict.
        if expected > 0 and expected - idx > max(2, math.ceil(expected * 0.01)):
            raise ValueError("video decoding ended before the declared frame count")
    finally:
        cap.release()


def read_frame_with_timestamp(path: str, t_sec: float) -> tuple[float, np.ndarray] | None:
    """Return a decoded frame and its decoder timestamp, never a fabricated frame.

    Try a nearby seek first. If the seek lands elsewhere, scan to the first
    timestamp at or after the request. Missing timestamps/frames return None.
    """
    if not math.isfinite(t_sec) or t_sec < 0:
        return None
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t_sec * fps))))
        ok, frame = cap.read()
        got = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if (ok and frame is not None and math.isfinite(got) and got >= 0
                and (got > 0 or t_sec == 0) and abs(got - t_sec) <= 1.5 / fps):
            return got, frame
    finally:
        cap.release()
    cap = cv2.VideoCapture(path)
    try:
        previous = -1.0
        while cap.grab():
            got = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if not math.isfinite(got) or got < 0 or got <= previous:
                return None
            previous = got
            if got >= t_sec:
                ok, frame = cap.retrieve()
                return (got, frame) if ok and frame is not None else None
        return None
    finally:
        cap.release()


def read_frame_at(path: str, t_sec: float) -> np.ndarray | None:
    """Compatibility wrapper for callers that only need pixels."""
    decoded = read_frame_with_timestamp(path, t_sec)
    return decoded[1] if decoded is not None else None

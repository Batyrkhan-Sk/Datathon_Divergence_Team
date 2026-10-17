"""Video decoding and sampling with exact timestamps.

Times come from the frames' own timestamps, not frame index / fps: phones record with a
variable frame rate (e.g. in low light), where index / fps drifts by seconds (format stress
test: 10.0 s became 6.5 s)."""
import subprocess
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
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    period, next_t, idx = 1.0 / rate, 0.0, 0
    tol = 0.25 / fps  # timestamp rounding
    while cap.grab():
        t = _timestamp(cap, idx, fps)
        idx += 1
        if t + tol < next_t:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        yield t, frame
        while next_t <= t + tol:
            next_t += period
    cap.release()


def read_frame_at(path: str, t_sec: float) -> np.ndarray | None:
    """Random access to a single frame (used for evidence frames). Seeks, then checks the
    decoded frame's timestamp; if it is off (variable frame rate), decodes up to t."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t_sec * fps))))
    ok, frame = cap.read()
    got = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
    cap.release()
    if ok and (t_sec < 1.0 / fps or abs(got - t_sec) <= 1.5 / fps):
        return frame
    cap = cv2.VideoCapture(path)
    idx, last = 0, None
    while cap.grab():
        t = _timestamp(cap, idx, fps)
        idx += 1
        if t + 0.5 / fps >= t_sec:
            ok, last = cap.retrieve()
            break
    cap.release()
    return last if last is not None else (frame if ok else None)

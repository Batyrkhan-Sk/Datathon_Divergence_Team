"""Video decoding and sampling with exact timestamps."""
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

    @property
    def duration(self) -> float:
        return self.n_frames / self.fps if self.fps else 0.0


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
    )
    cap.release()
    return info


def iter_frames(path: str, rate: float = 4.0) -> Iterator[tuple[float, np.ndarray]]:
    """Yield (t_sec, BGR frame) at ~`rate` fps, decoding sequentially (no seeks)."""
    info = probe(path)
    step = info.fps / rate
    cap = cv2.VideoCapture(path)
    next_idx, k, idx = 0, 0, 0
    while idx < info.n_frames:
        if idx == next_idx:
            ok, frame = cap.read()
            if not ok:
                break
            yield idx / info.fps, frame
            k += 1
            next_idx = int(round(k * step))
        elif not cap.grab():
            break
        idx += 1
    cap.release()


def read_frame_at(path: str, t_sec: float) -> np.ndarray | None:
    """Random access to a single frame (used for evidence frames)."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t_sec * fps))))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None

"""Camera tamper detection: covered, blacked-out, heavily defocused, or shifted.

This is NOT about person detection — it looks at the global image statistics
to decide whether the camera itself has been interfered with.

Returns a list of TamperEvent (timecoded) so the pipeline can report them.
"""
from dataclasses import dataclass
from typing import NamedTuple

import cv2
import numpy as np


# --- per-frame thresholds ---
BLACK_LUMA_THRESHOLD = 8        # frame mean Y < this → blacked out
COVERED_UNIFORM_THRESHOLD = 12  # std(Y) < this → uniform (hand/cloth cover)
BLUR_VAR_THRESHOLD = 15         # Laplacian var < this → extreme defocus (tamper)
SHIFT_CORR_THRESHOLD = 0.60     # normalised cross-correlation < this → shifted

# --- temporal thresholds ---
MIN_TAMPER_SEC = 2.0            # shorter runs are noise


class TamperKind(NamedTuple):
    code: str
    label: str


KIND_BLACK = TamperKind("camera_blackout", "Камера закрыта / отключена (изображение чёрное)")
KIND_COVER = TamperKind("camera_covered", "Камера закрыта рукой или предметом")
KIND_BLUR  = TamperKind("camera_defocused", "Камера расфокусирована (возможная манипуляция)")
KIND_SHIFT = TamperKind("camera_shifted", "Камера сдвинута (изменился ракурс)")


@dataclass
class TamperEvent:
    kind: TamperKind
    t_start: float
    t_end: float


def _luma_stats(frame_bgr: np.ndarray) -> tuple[float, float]:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.mean()), float(gray.std())


def _blur_var(frame_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised cross-correlation of two grayscale images (0..1)."""
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    a -= a.mean(); b -= b.mean()
    num = float(np.sum(a * b))
    den = float(np.sqrt(np.sum(a ** 2) * np.sum(b ** 2)) + 1e-9)
    return (num / den + 1.0) / 2.0  # map [-1,1] → [0,1]


def _classify(mean_y: float, std_y: float, blur: float,
              ncc_ref: float | None) -> TamperKind | None:
    if mean_y < BLACK_LUMA_THRESHOLD:
        return KIND_BLACK
    if std_y < COVERED_UNIFORM_THRESHOLD:
        return KIND_COVER
    if blur < BLUR_VAR_THRESHOLD:
        return KIND_BLUR
    if ncc_ref is not None and ncc_ref < SHIFT_CORR_THRESHOLD:
        return KIND_SHIFT
    return None


def _run_length_events(times: list[float], kinds: list[TamperKind | None],
                       min_sec: float) -> list[TamperEvent]:
    """Group consecutive same-kind frames into events, filter by duration."""
    events: list[TamperEvent] = []
    i = 0
    while i < len(times):
        k = kinds[i]
        if k is None:
            i += 1
            continue
        j = i + 1
        while j < len(times) and kinds[j] == k:
            j += 1
        if times[j - 1] - times[i] >= min_sec:
            events.append(TamperEvent(k, times[i], times[j - 1]))
        i = j
    return events


def detect_tamper(times: list[float], frames: list[np.ndarray],
                  ref_frame: np.ndarray | None = None) -> list[TamperEvent]:
    """Analyse a sequence of frames (same fps as pipeline.SAMPLE_FPS).

    ref_frame: a stable frame from early in the video used as the NCC reference.
    If None, the first frame is used as reference.
    """
    if not frames:
        return []

    ref = ref_frame if ref_frame is not None else frames[0]
    kinds: list[TamperKind | None] = []

    for frame in frames:
        mean_y, std_y = _luma_stats(frame)
        blur = _blur_var(frame)
        ncc_val = _ncc(ref, frame) if ref is not None else None
        kinds.append(_classify(mean_y, std_y, blur, ncc_val))

    return _run_length_events(times, kinds, MIN_TAMPER_SEC)

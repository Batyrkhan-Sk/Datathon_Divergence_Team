"""Video quality pre-flight check.

Called once per video before heavy analysis. Returns a QualityReport with
issues (dark, blurry, frozen, wrong orientation) and an overall ok flag.
A poor-quality video may produce unreliable detection results; the API
includes the report in the result so the reviewer knows.
"""
from dataclasses import dataclass, field
from typing import NamedTuple

import cv2
import numpy as np


# --- thresholds (tuned empirically on a small sample) ---
DARK_LUMA_THRESHOLD = 40        # mean Y < this → too dark
BLUR_LAPLACIAN_THRESHOLD = 40   # variance of Laplacian < this → blurry
FROZEN_DIFF_THRESHOLD = 0.5     # mean abs pixel diff < this → frozen
PORTRAIT_RATIO = 0.8            # w/h < this → portrait (wrong for a desk cam)
SAMPLE_FRAMES = 12              # how many frames to probe


class Issue(NamedTuple):
    code: str
    label: str
    severity: str  # "warning" | "error"


@dataclass
class QualityReport:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "issues": [{"code": i.code, "label": i.label, "severity": i.severity}
                       for i in self.issues],
            "notes": self.notes,
        }


def _sample_frames(path: str, n: int = SAMPLE_FRAMES) -> list[np.ndarray]:
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return []
    step = max(1, total // n)
    frames = []
    for i in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(i * step, total - 1))
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def _luma(frame_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def _blur_score(frame_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _frozen_score(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference between two frames (0 = identical)."""
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))


def check(path: str) -> QualityReport:
    """Run all quality checks and return a QualityReport."""
    frames = _sample_frames(path)
    if not frames:
        return QualityReport(ok=False, issues=[
            Issue("no_frames", "Видео не содержит кадров", "error")])

    issues: list[Issue] = []
    notes: list[str] = []

    # 1. Orientation (portrait vs landscape)
    h, w = frames[0].shape[:2]
    if w > 0 and (w / h) < PORTRAIT_RATIO:
        issues.append(Issue("portrait",
                            "Видео в портретной ориентации (ожидается альбомная)", "warning"))
        notes.append(f"Разрешение {w}×{h}")

    # 2. Darkness: check middle frames
    mid = frames[len(frames) // 4: 3 * len(frames) // 4]
    dark_count = sum(1 for f in mid if _luma(f) < DARK_LUMA_THRESHOLD)
    if dark_count > len(mid) // 2:
        issues.append(Issue("dark", "Видео слишком тёмное", "error"))
        notes.append(f"Средняя яркость < {DARK_LUMA_THRESHOLD}")

    # 3. Blur: check middle frames
    blur_count = sum(1 for f in mid if _blur_score(f) < BLUR_LAPLACIAN_THRESHOLD)
    if blur_count > len(mid) // 2:
        issues.append(Issue("blurry", "Видео размытое или не в фокусе", "warning"))

    # 4. Frozen (static image or nearly static video)
    if len(frames) >= 4:
        diffs = [_frozen_score(frames[i], frames[i + 1])
                 for i in range(0, len(frames) - 1, len(frames) // 4)]
        if all(d < FROZEN_DIFF_THRESHOLD for d in diffs):
            issues.append(Issue("frozen", "Видео не содержит движения (заморожено?)", "error"))

    error_count = sum(1 for i in issues if i.severity == "error")
    return QualityReport(ok=(error_count == 0), issues=issues, notes=notes)

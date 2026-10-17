"""Banking secrecy — pixelate laptop screens in evidence frames.

The laptop screen may show customer account details. Pixelating it before
the frame is shown to the reviewer protects banking secrecy (банковская тайна).

Usage:
    from ml import privacy
    frame_bgr = privacy.redact(frame_bgr, laptop_box)
"""
import cv2
import numpy as np

PIXEL_BLOCK = 12    # pixelation cell size (px); larger = more opaque


def _screen_crop_box(laptop_box: list[float], h: int, w: int) -> tuple[int, int, int, int] | None:
    """Upper ~55 % of the laptop bounding box is the screen; lower part is the keyboard."""
    x1, y1, x2, y2 = laptop_box
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    screen_h = int((y2 - y1) * 0.55)
    return (x1, y1, x2, y1 + screen_h) if x2 > x1 and screen_h > 8 else None


def pixelate(frame: np.ndarray, region: tuple[int, int, int, int],
             block: int = PIXEL_BLOCK) -> np.ndarray:
    """Pixelate `region` (x1,y1,x2,y2) of `frame` in-place; returns the same array."""
    x1, y1, x2, y2 = region
    roi = frame[y1:y2, x1:x2]
    rh, rw = roi.shape[:2]
    if rh < 2 or rw < 2:
        return frame
    small = cv2.resize(roi, (max(1, rw // block), max(1, rh // block)),
                       interpolation=cv2.INTER_LINEAR)
    frame[y1:y2, x1:x2] = cv2.resize(small, (rw, rh), interpolation=cv2.INTER_NEAREST)
    return frame


def redact(frame: np.ndarray, laptop_box: list[float] | None) -> np.ndarray:
    """Pixelate the laptop screen region if laptop_box is known. Non-destructive copy."""
    if laptop_box is None:
        return frame
    h, w = frame.shape[:2]
    region = _screen_crop_box(laptop_box, h, w)
    if region is None:
        return frame
    out = frame.copy()
    return pixelate(out, region)

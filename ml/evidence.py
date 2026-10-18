"""Evidence frames: pick 1-3 moments per event, draw boxes, encode as base64 JPEG."""
import base64

import cv2

from .events import Event
from .video import read_frame_with_timestamp

MAX_FRAMES = 3
JPEG_QUALITY = 85


def _nearest_boxes(event: Event, t: float, tol: float = 0.3):
    if not event.boxes:
        return []
    key = min(event.boxes, key=lambda k: abs(k - t))
    return event.boxes[key] if abs(key - t) <= tol else []


def _draw(frame, boxes):
    for x1, y1, x2, y2, label in boxes:
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
        if label:
            cv2.putText(frame, str(label), (int(x1), max(12, int(y1) - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    return frame


def frames_for(video_path: str, event: Event, duration: float) -> list[dict]:
    times = [event.t_start] + [t for t in event.evidence_times if t != event.t_start]
    out = []
    for t in times[:MAX_FRAMES]:
        t = min(max(0.0, t), max(0.0, duration - 0.05))
        decoded = read_frame_with_timestamp(video_path, t)
        if decoded is None:
            continue
        actual_t, frame = decoded
        frame = _draw(frame, _nearest_boxes(event, actual_t))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            out.append({"timestamp_sec": round(actual_t, 4),
                        "image_base64": base64.b64encode(buf.tobytes()).decode("ascii")})
    return out

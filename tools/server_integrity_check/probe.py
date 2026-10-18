"""Seven synthetic before/after cases; no models or bank media."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard import install, self_check
install()
self_check()
sys.path.insert(0, sys.argv[1])
import cv2
import numpy as np
from backend.app import results


def main():
    with tempfile.TemporaryDirectory(prefix="synthetic-probe-") as directory:
        path = str(Path(directory) / "synthetic.mov")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
        if not writer.isOpened():
            raise RuntimeError("synthetic_encoder_unavailable")
        try:
            for i in range(20):
                frame = np.zeros((64, 96, 3), np.uint8)
                frame[:, :, 1] = 60 + i * 5
                frame[8:32, i:i + 20, 2] = 255
                writer.write(frame)
        finally:
            writer.release()
        positive = {"verdict": "violation", "violations": [{"type": "Synthetic event",
                    "type_id": "synthetic", "description": "Generated test pattern",
                    "timecode_sec": 1.0, "evidence_frames": []}]}
        negative_time = deepcopy(positive)
        negative_time["violations"][0]["timecode_sec"] = -1
        cases = {"missing_result": None, "missing_verdict": {"violations": []},
                 "contradictory_result": {"verdict": "violation", "violations": []},
                 "negative_timestamp": negative_time,
                 "valid_negative": {"verdict": "no_violation", "violations": []},
                 "valid_positive": positive}
        outputs = {}
        for name, raw in cases.items():
            try:
                result = results.normalize(raw, path)
                outputs[name] = {"outcome": "accepted", "verdict": result["verdict"]}
            except Exception as exc:
                outputs[name] = {"outcome": "rejected", "exception_class": type(exc).__name__}
        if hasattr(results, "read_frame_at"):
            results.read_frame_at = lambda *a, **k: None
        if hasattr(results, "read_frame_with_timestamp"):
            results.read_frame_with_timestamp = lambda *a, **k: None
        try:
            result = results.normalize(positive, path)
            raw = base64.b64decode(result["violations"][0]["evidence_frames"][0]["image_base64"])
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            outputs["evidence_read_failure"] = {"outcome": "accepted", "verdict": result["verdict"],
                                               "uniform_gray_placeholder": bool(np.all(image == 128))}
        except Exception as exc:
            outputs["evidence_read_failure"] = {"outcome": "rejected", "exception_class": type(exc).__name__}
        print(json.dumps(outputs))


if __name__ == "__main__":
    main()

"""General object detection with RT-DETR v2 (Apache-2.0, COCO classes).

Used for people and the laptop; also keeps a few classes that hint at personal items.
Feasibility: 0.16 s/frame single, 0.18 GB GPU on an RTX 3050 4 GB.
"""
from functools import lru_cache

import numpy as np
import torch

MODEL_ID = "PekingU/rtdetr_v2_r18vd"
KEEP = {"person", "laptop", "tvmonitor", "cell phone", "cup", "bottle",
        "handbag", "backpack", "suitcase"}
MIN_SCORE = 0.4
BATCH = 8


@lru_cache(maxsize=1)
def _model():
    from transformers import AutoImageProcessor, AutoModelForObjectDetection
    device = "cuda" if torch.cuda.is_available() else "cpu"
    proc = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForObjectDetection.from_pretrained(MODEL_ID).to(device).eval()
    if device == "cuda":
        model = model.half()
    return proc, model, device


def warmup():
    _model()


def detect(frames_bgr: list[np.ndarray]) -> list[list[dict]]:
    """Per frame: [{"label", "score", "box": [x1, y1, x2, y2]}] in pixel coords."""
    proc, model, device = _model()
    out: list[list[dict]] = []
    for i in range(0, len(frames_bgr), BATCH):
        batch = [np.ascontiguousarray(f[:, :, ::-1]) for f in frames_bgr[i:i + BATCH]]  # BGR->RGB
        inputs = proc(images=batch, return_tensors="pt").to(device)
        if device == "cuda":
            inputs["pixel_values"] = inputs["pixel_values"].half()
        with torch.no_grad():
            res = model(**inputs)
        sizes = [f.shape[:2] for f in batch]
        posts = proc.post_process_object_detection(res, threshold=MIN_SCORE,
                                                   target_sizes=sizes)
        for p in posts:
            dets = []
            for s, l, b in zip(p["scores"], p["labels"], p["boxes"]):
                label = model.config.id2label[int(l)]
                if label in KEEP:
                    dets.append({"label": label, "score": round(float(s), 3),
                                 "box": [round(float(x), 1) for x in b]})
            out.append(dets)
    return out

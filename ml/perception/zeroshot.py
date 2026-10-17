"""Text-prompted detection with OWLv2 (Apache-2.0), used on small crops only.

Feasibility: on desk crops taken after the teller left, cash cases scored 0.12-0.45 and
clean cases had no detection above 0.05.
"""
from functools import lru_cache

import numpy as np
import torch
from PIL import Image

MODEL_ID = "google/owlv2-base-patch16-ensemble"
MONEY_QUERIES = {
    "banknotes": "наличные деньги",
    "stack of money": "наличные деньги",
    "paper money on a table": "наличные деньги",
    "coin roll": "монеты в упаковке",
    "green cash bag": "инкассаторская сумка",
}


@lru_cache(maxsize=1)
def _model():
    from transformers import Owlv2ForObjectDetection, Owlv2Processor
    device = "cuda" if torch.cuda.is_available() else "cpu"
    proc = Owlv2Processor.from_pretrained(MODEL_ID)
    model = Owlv2ForObjectDetection.from_pretrained(MODEL_ID).to(device).eval()
    return proc, model, device


def warmup():
    _model()


def find(frame_bgr: np.ndarray, box: list[float], queries: list[str],
         threshold: float = 0.05) -> list[dict]:
    """Detect `queries` inside `box` of the frame. Boxes returned in frame coords."""
    proc, model, device = _model()
    h, w = frame_bgr.shape[:2]
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    x2, y2 = min(w, int(box[2])), min(h, int(box[3]))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return []
    crop = Image.fromarray(np.ascontiguousarray(frame_bgr[y1:y2, x1:x2, ::-1]))
    inputs = proc(text=[queries], images=crop, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inputs)
    side = max(crop.size)  # OWLv2 pads to a square
    res = proc.post_process_grounded_object_detection(
        out, threshold=threshold, target_sizes=[(side, side)])[0]
    found = []
    for s, l, b in zip(res["scores"], res["labels"], res["boxes"]):
        bx = [float(b[0]) + x1, float(b[1]) + y1, float(b[2]) + x1, float(b[3]) + y1]
        found.append({"label": queries[int(l)], "score": float(s), "box": bx})
    return sorted(found, key=lambda d: -d["score"])


def find_money(frame_bgr: np.ndarray, box: list[float]) -> dict | None:
    """Best money-like detection in the region, with a Russian description, or None."""
    hits = find(frame_bgr, box, list(MONEY_QUERIES))
    if not hits:
        return None
    best = hits[0]
    return {**best, "what": MONEY_QUERIES[best["label"]]}

"""Run candidate detectors on the feasibility frame set.

    python -m eval.feasibility.detect_test owlv2
    python -m eval.feasibility.detect_test gdino
    python -m eval.feasibility.detect_test rtdetr

Writes out/feasibility/<model>/: detections.json, sheet_XX.jpg (annotated, 12 frames each),
and prints speed (s/frame) and peak GPU memory.
"""
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "feasibility"

# Objects our violation types depend on (see data/rules.json).
QUERIES = [
    "person", "door", "metal safe", "open safe door", "key in a lock", "banknotes",
    "stack of money", "coin roll", "green cash bag", "laptop", "laptop screen",
    "cash counting machine", "handbag", "coat", "cup", "mobile phone",
]
THRESHOLDS = {"owlv2": 0.15, "gdino": 0.30, "rtdetr": 0.50}
COLORS = [tuple(int(c) for c in np.random.default_rng(i).integers(60, 255, 3))
          for i in range(len(QUERIES) + 1)]


def load_frames():
    with open(OUT / "frames.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build(model_name, device):
    if model_name == "owlv2":
        from transformers import Owlv2ForObjectDetection, Owlv2Processor
        mid = "google/owlv2-base-patch16-ensemble"
        proc = Owlv2Processor.from_pretrained(mid)
        model = Owlv2ForObjectDetection.from_pretrained(mid, dtype=torch.float16).to(device)

        def run(img: Image.Image):
            inputs = proc(text=[QUERIES], images=img, return_tensors="pt").to(device)
            inputs["pixel_values"] = inputs["pixel_values"].half()
            with torch.no_grad():
                out = model(**inputs)
            side = max(img.size)  # OWLv2 pads to a square; boxes are in padded coords
            res = proc.post_process_grounded_object_detection(
                out, threshold=THRESHOLDS["owlv2"], target_sizes=[(side, side)])[0]
            return [(QUERIES[int(l)], float(s), [float(x) for x in b])
                    for s, l, b in zip(res["scores"], res["labels"], res["boxes"])]
        return run

    if model_name == "gdino":
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
        mid = "IDEA-Research/grounding-dino-tiny"
        proc = AutoProcessor.from_pretrained(mid)
        model = AutoModelForZeroShotObjectDetection.from_pretrained(mid).to(device)
        text = ". ".join(QUERIES) + "."

        def run(img: Image.Image):
            inputs = proc(images=img, text=text, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model(**inputs)
            res = proc.post_process_grounded_object_detection(
                out, inputs.input_ids, threshold=THRESHOLDS["gdino"], text_threshold=0.25,
                target_sizes=[img.size[::-1]])[0]
            labels = res.get("text_labels", res.get("labels"))
            return [(str(l), float(s), [float(x) for x in b])
                    for s, l, b in zip(res["scores"], labels, res["boxes"])]
        return run

    if model_name == "rtdetr":
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
        mid = "PekingU/rtdetr_v2_r18vd"
        proc = AutoImageProcessor.from_pretrained(mid)
        model = AutoModelForObjectDetection.from_pretrained(mid).to(device)

        def run(img: Image.Image):
            inputs = proc(images=img, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model(**inputs)
            res = proc.post_process_object_detection(
                out, threshold=THRESHOLDS["rtdetr"], target_sizes=[img.size[::-1]])[0]
            return [(model.config.id2label[int(l)], float(s), [float(x) for x in b])
                    for s, l, b in zip(res["scores"], res["labels"], res["boxes"])]
        return run

    raise SystemExit(f"unknown model {model_name}")


def draw(path, dets, caption):
    img = cv2.imread(str(ROOT / path))
    for label, score, (x1, y1, x2, y2) in dets:
        idx = QUERIES.index(label) if label in QUERIES else len(QUERIES)
        c = COLORS[idx]
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), c, 2)
        cv2.putText(img, f"{label} {score:.2f}", (int(x1) + 2, max(12, int(y1) + 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, c, 1, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(img, caption, (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    return img


def main(model_name):
    sys.stdout.reconfigure(encoding="utf-8")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    frames = load_frames()
    run = build(model_name, device)
    run(Image.open(ROOT / frames[0]["path"]).convert("RGB"))  # warm-up
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    results, times = [], []
    for f in frames:
        img = Image.open(ROOT / f["path"]).convert("RGB")
        t0 = time.time()
        dets = run(img)
        if device == "cuda":
            torch.cuda.synchronize()
        times.append(time.time() - t0)
        results.append({**f, "detections": dets})

    out_dir = OUT / model_name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detections.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    tiles = [draw(r["path"], r["detections"],
                  f'{r["video"]} {r["layout"]} {r["role"]} {r["type_id"][:18]}') for r in results]
    for i in range(0, len(tiles), 12):
        chunk = tiles[i:i + 12]
        h, w = chunk[0].shape[:2]
        sheet = np.full((3 * h, 4 * w, 3), 255, np.uint8)
        for j, t in enumerate(chunk):
            r, c = divmod(j, 4)
            sheet[r * h:(r + 1) * h, c * w:(c + 1) * w] = t
        cv2.imwrite(str(out_dir / f"sheet_{i // 12:02d}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])

    peak = torch.cuda.max_memory_allocated() / 2**30 if device == "cuda" else 0
    counts = {}
    for r in results:
        for label in {d[0] for d in r["detections"]}:
            counts[label] = counts.get(label, 0) + 1
    summary = {"model": model_name, "device": device, "frames": len(frames),
               "sec_per_frame": round(float(np.mean(times)), 3),
               "peak_gpu_gb": round(peak, 2),
               "frames_with_label": dict(sorted(counts.items(), key=lambda kv: -kv[1]))}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

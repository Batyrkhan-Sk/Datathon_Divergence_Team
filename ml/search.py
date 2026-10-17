"""Semantic video search with SigLIP2 (Apache-2.0).

Given a text query, finds the N frames in the video whose visual content
best matches the query. Returns (timecode_sec, score, base64_jpeg) triples.

SigLIP2 is loaded lazily on first call — it does not slow down the main
analysis pipeline at all since it's only used by the search endpoint.

python -m ml.search data/raw/X-26.mov "кассир открывает сейф"
"""
import base64
import os
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODEL_ID = os.environ.get("SIGLIP_MODEL", "google/siglip2-base-patch16-224")
SAMPLE_FPS = float(os.environ.get("SIGLIP_SAMPLE_FPS", "2"))
TOP_K = int(os.environ.get("SIGLIP_TOP_K", "3"))


@lru_cache(maxsize=1)
def _model():
    from transformers import AutoModel, AutoProcessor
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device).eval()
    return proc, model, device


def warmup() -> None:
    _model()


def _frames_at_fps(path: str, fps: float):
    """Yield (t_sec, BGR frame) at ~fps."""
    from .video import probe
    info = probe(path)
    step = info.fps / fps
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


def search(video_path: str, query: str, top_k: int = TOP_K) -> list[dict]:
    """Return top_k frames matching `query`.

    Each result: {timecode_sec, score, image_base64}
    """
    import torch
    from PIL import Image

    proc, model, device = _model()

    # Encode all frames
    all_frames = list(_frames_at_fps(video_path, SAMPLE_FPS))
    if not all_frames:
        return []

    pil_images = [Image.fromarray(f[:, :, ::-1]) for _, f in all_frames]
    times = [t for t, _ in all_frames]

    # Batch embed images
    BATCH = 32
    image_embeds = []
    for i in range(0, len(pil_images), BATCH):
        batch = pil_images[i:i + BATCH]
        inp = proc(images=batch, return_tensors="pt", padding="max_length").to(device)
        with torch.no_grad():
            emb = model.get_image_features(**{k: v for k, v in inp.items() if "pixel" in k})
        emb = emb / emb.norm(dim=-1, keepdim=True)
        image_embeds.append(emb.cpu())
    image_embeds = torch.cat(image_embeds, dim=0)  # (N, D)

    # Encode text query
    text_inp = proc(text=[query], return_tensors="pt", padding="max_length").to(device)
    with torch.no_grad():
        text_emb = model.get_text_features(**{k: v for k, v in text_inp.items() if "input" in k})
    text_emb = text_emb / text_emb.norm(dim=-1, keepdim=True)  # (1, D)

    scores = (image_embeds @ text_emb.T).squeeze(1).tolist()  # (N,)

    indexed = sorted(enumerate(scores), key=lambda x: -x[1])[:top_k]
    results = []
    for idx, score in indexed:
        t = times[idx]
        frame = all_frames[idx][1]
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            continue
        results.append({
            "timecode_sec": round(t, 2),
            "score": round(float(score), 4),
            "image_base64": base64.b64encode(buf.tobytes()).decode("ascii"),
        })
    return results


def make_search_router(store) -> "APIRouter":
    from fastapi import APIRouter, HTTPException, Query as Q
    from fastapi.concurrency import run_in_threadpool

    router = APIRouter()

    @router.get("/ui/api/jobs/{job_id}/search")
    async def search_endpoint(
        job_id: str,
        q: str = Q(..., min_length=1, max_length=200),
        top_k: int = Q(3, ge=1, le=10),
    ):
        job = store.get(job_id)
        if job is None or job.source != "ui":
            raise HTTPException(404, "job not found")
        if job.status != "done":
            raise HTTPException(409, "job not finished yet")
        from pathlib import Path
        vpath = job.video_path
        if not Path(vpath).is_file():
            raise HTTPException(404, "video file not found")
        results = await run_in_threadpool(search, vpath, q, top_k)
        return {"query": q, "results": results}

    return router


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    import json
    if len(sys.argv) < 3:
        print("Usage: python -m ml.search <video> <query>", file=sys.stderr)
        sys.exit(1)
    hits = search(sys.argv[1], sys.argv[2])
    for h in hits:
        h_out = {k: v for k, v in h.items() if k != "image_base64"}
        print(json.dumps(h_out, ensure_ascii=False))

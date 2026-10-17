"""Local vision-language model (Qwen3-VL, Apache-2.0) for yes/no state questions on
frames or crops, e.g. "Is the safe door open?".

Model choice (env VLM_MODEL overrides): Qwen3-VL-8B in bf16 on a GPU with >= 20 GB,
otherwise Qwen3-VL-2B in 4-bit (~1.6 GB, fits a 4 GB laptop GPU). `p_yes` uses one
forward pass and compares the next-token logits of "yes" and "no", which is faster
than generating text and gives a usable confidence.
"""
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from PIL import Image

SMALL, LARGE = "Qwen/Qwen3-VL-2B-Instruct", "Qwen/Qwen3-VL-8B-Instruct"
LOCAL_DIRS = {SMALL: Path(__file__).resolve().parents[2] / "weights" / "qwen3-vl-2b"}
MAX_SIDE = int(os.environ.get("VLM_MAX_SIDE", 448))  # downscale long side: fewer tokens


def _choose() -> str:
    if os.environ.get("VLM_MODEL"):
        return os.environ["VLM_MODEL"]
    big = torch.cuda.is_available() and torch.cuda.get_device_properties(0).total_memory > 20 * 2**30
    return LARGE if big else SMALL


@lru_cache(maxsize=1)
def _model():
    from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
    mid = _choose()
    local = LOCAL_DIRS.get(mid)
    src = str(local) if local and (local / "model.safetensors").exists() else mid
    kwargs = {"device_map": os.environ.get("VLM_DEVICE", "cuda:0")}
    if mid == SMALL:
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
    else:
        kwargs["dtype"] = torch.bfloat16
    proc = AutoProcessor.from_pretrained(src)
    model = AutoModelForImageTextToText.from_pretrained(src, **kwargs).eval()
    tok = proc.tokenizer
    yes_ids = {tok.encode(w, add_special_tokens=False)[0] for w in ("yes", "Yes", " yes", " Yes")}
    no_ids = {tok.encode(w, add_special_tokens=False)[0] for w in ("no", "No", " no", " No")}
    return proc, model, sorted(yes_ids), sorted(no_ids)


def warmup():
    _model()


def _to_pil(img) -> Image.Image:
    if isinstance(img, np.ndarray):  # BGR from OpenCV
        img = Image.fromarray(np.ascontiguousarray(img[:, :, ::-1]))
    w, h = img.size
    scale = MAX_SIDE / max(w, h)  # also enlarges small crops: a key is a few pixels
    if abs(scale - 1) > 0.05:
        img = img.resize((round(w * scale), round(h * scale)), Image.BICUBIC)
    return img


def crop(frame_bgr: np.ndarray, box, pad: float = 0.15) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = box
    px, py = pad * (x2 - x1), pad * (y2 - y1)
    return frame_bgr[max(0, int(y1 - py)):min(h, int(y2 + py)),
                     max(0, int(x1 - px)):min(w, int(x2 + px))]


def _inputs(img, question):
    proc, model, _, _ = _model()
    messages = [{"role": "user", "content": [
        {"type": "image", "image": _to_pil(img)},
        {"type": "text", "text": question + " Answer yes or no."}]}]
    return proc.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                    return_dict=True, return_tensors="pt").to(model.device)


def p_yes_pair(img_a, img_b, question: str) -> float:
    """Probability of "yes" for a question about two images (e.g. before / after)."""
    proc, model, yes_ids, no_ids = _model()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Image 1:"}, {"type": "image", "image": _to_pil(img_a)},
        {"type": "text", "text": "Image 2:"}, {"type": "image", "image": _to_pil(img_b)},
        {"type": "text", "text": question + " Answer yes or no."}]}]
    inputs = proc.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                      return_dict=True, return_tensors="pt").to(model.device)
    with torch.no_grad():
        logits = model(**inputs).logits[0, -1].float()
    return float(torch.sigmoid(torch.logsumexp(logits[yes_ids], 0) - torch.logsumexp(logits[no_ids], 0)))


def p_yes(img, question: str) -> float:
    """Probability that the answer is "yes" (0..1)."""
    _, model, yes_ids, no_ids = _model()
    with torch.no_grad():
        logits = model(**_inputs(img, question)).logits[0, -1].float()
    y = torch.logsumexp(logits[yes_ids], 0)
    n = torch.logsumexp(logits[no_ids], 0)
    return float(torch.sigmoid(y - n))


def locate(frame_bgr: np.ndarray, what: str) -> list[float] | None:
    """Bounding box [x1, y1, x2, y2] in frame pixels for `what`, or None.
    Qwen3-VL grounding returns coordinates normalised to 0..1000."""
    import json
    import re
    text = describe(frame_bgr, f'Locate the {what} in the image. Output its bounding box as '
                               f'JSON: [{{"bbox_2d": [x1, y1, x2, y2], "label": "{what}"}}]',
                    max_new_tokens=80)
    m = re.search(r"\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,"
                  r"\s*(\d+(?:\.\d+)?)\s*\]", text)
    if not m:
        return None
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (float(v) for v in m.groups())
    box = [x1 / 1000 * w, y1 / 1000 * h, x2 / 1000 * w, y2 / 1000 * h]
    return box if box[2] > box[0] and box[3] > box[1] else None


def describe(img, question: str = "Describe what is happening in one sentence.",
             max_new_tokens: int = 60) -> str:
    proc, model, _, _ = _model()
    messages = [{"role": "user", "content": [
        {"type": "image", "image": _to_pil(img)}, {"type": "text", "text": question}]}]
    inputs = proc.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                      return_dict=True, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
    return proc.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()

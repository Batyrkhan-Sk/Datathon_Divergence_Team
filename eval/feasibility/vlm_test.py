"""Ask a small local VLM yes/no state questions on the feasibility frames.

    python -m eval.feasibility.vlm_test qwen3vl2b      # Qwen3-VL-2B-Instruct, 4-bit
    python -m eval.feasibility.vlm_test smolvlm2       # SmolVLM2-500M-Video-Instruct, fp16

Uses at_label / after frames of violation videos and one frame per clean video.
Writes out/feasibility/<model>/answers.json and sheet_XX.jpg (answers printed on frames),
prints latency per question, peak GPU memory and agreement on the checks we can
derive from the labels (see CHECKS).
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

QUESTIONS = {
    "people": "How many people are visible in this image? Answer with a single number.",
    "teller_at_desk": "Is a person sitting or standing at the desk with the laptop? Answer yes or no.",
    "cash_on_desk": "Are there banknotes, money or coin rolls lying on the desk? Answer yes or no.",
    "safe_open": "Is the door of the grey metal safe open? Answer yes or no.",
    "key_in_safe": "Is a key inserted in the lock of the grey metal safe? Answer yes or no.",
    "screen_active": "Is the laptop screen on and showing a document or table (not black, not a lock screen)? Answer yes or no.",
    "eat_drink": "Is someone drinking or eating? Answer yes or no.",
    "coat_bag_on_desk": "Is there a coat, jacket or handbag on the desk? Answer yes or no.",
    "phone_in_hand": "Is anyone holding a mobile phone? Answer yes or no.",
    "hand_counting": "Is someone counting banknotes by hand? Answer yes or no.",
}

# (video, role) -> {question: expected answer}. Only facts confirmed by our review.
CHECKS = {
    ("X-20", "at_label"): {"safe_open": "yes"},
    ("X-22", "after"): {"key_in_safe": "yes", "teller_at_desk": "no"},
    ("X-26", "after"): {"cash_on_desk": "yes", "teller_at_desk": "no"},
    ("X-15", "after"): {"teller_at_desk": "no"},
    ("X-24", "after"): {"cash_on_desk": "yes", "teller_at_desk": "no"},
    ("X-28", "after"): {"screen_active": "yes", "teller_at_desk": "no"},
    ("X-46", "after"): {"eat_drink": "yes"},
    ("X-40", "after"): {"coat_bag_on_desk": "yes"},
    ("X-47", "at_label"): {"hand_counting": "yes"},
    ("X-4", "at_label"): {"cash_on_desk": "yes", "people": "2"},
    ("X-18", "at_label"): {"people": "3"},
    ("X-21", "clean_1"): {"safe_open": "no"},
}

MODELS = {
    "qwen3vl2b": ("Qwen/Qwen3-VL-2B-Instruct", True),
    "smolvlm2": ("HuggingFaceTB/SmolVLM2-500M-Video-Instruct", False),
}


def build(name):
    from transformers import AutoModelForImageTextToText, AutoProcessor
    mid, four_bit = MODELS[name]
    kwargs = {"device_map": "cuda:0"}
    if four_bit:
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
    else:
        kwargs["torch_dtype"] = torch.float16
    proc = AutoProcessor.from_pretrained(mid)
    model = AutoModelForImageTextToText.from_pretrained(mid, **kwargs).eval()

    def ask(img: Image.Image, question: str) -> str:
        messages = [{"role": "user", "content": [{"type": "image", "image": img},
                                                 {"type": "text", "text": question}]}]
        inputs = proc.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                          return_dict=True, return_tensors="pt").to(model.device)
        if "pixel_values" in inputs and not four_bit:
            inputs["pixel_values"] = inputs["pixel_values"].to(torch.float16)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=6, do_sample=False)
        text = proc.batch_decode(out[:, inputs["input_ids"].shape[1]:],
                                 skip_special_tokens=True)[0]
        return text.strip().lower().rstrip(".")
    return ask


def norm(ans: str) -> str:
    a = ans.split()[0] if ans else ""
    return {"yes": "yes", "no": "no"}.get(a.strip(",."), a)


def main(name):
    sys.stdout.reconfigure(encoding="utf-8")
    with open(OUT / "frames.csv", encoding="utf-8") as fh:
        frames = [f for f in csv.DictReader(fh) if f["role"] in ("at_label", "after", "clean_1")]
    ask = build(name)
    ask(Image.open(ROOT / frames[0]["path"]).convert("RGB"), "Describe the image in one word.")
    torch.cuda.reset_peak_memory_stats()

    results, lat = [], []
    for f in frames:
        img = Image.open(ROOT / f["path"]).convert("RGB")
        answers = {}
        for key, q in QUESTIONS.items():
            t0 = time.time()
            answers[key] = norm(ask(img, q))
            lat.append(time.time() - t0)
        results.append({**f, "answers": answers})
        print(f'{f["video"]:5} {f["role"]:8} ' + " ".join(f"{k}={v}" for k, v in answers.items()),
              flush=True)

    ok = total = 0
    misses = []
    for r in results:
        for q, exp in CHECKS.get((r["video"], r["role"]), {}).items():
            total += 1
            if r["answers"][q] == exp:
                ok += 1
            else:
                misses.append(f'{r["video"]}/{r["role"]}: {q} expected {exp}, got {r["answers"][q]}')

    out_dir = OUT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "answers.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    tiles = []
    for r in results:
        img = cv2.imread(str(ROOT / r["path"]))
        lines = [f'{r["video"]} {r["role"]}'] + [f"{k}: {v}" for k, v in r["answers"].items()]
        cv2.rectangle(img, (0, 0), (250, 16 * len(lines) + 6), (0, 0, 0), -1)
        for i, line in enumerate(lines):
            cv2.putText(img, line, (4, 15 + 16 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(img)
    for i in range(0, len(tiles), 12):
        chunk = tiles[i:i + 12]
        h, w = chunk[0].shape[:2]
        sheet = np.full((3 * h, 4 * w, 3), 255, np.uint8)
        for j, t in enumerate(chunk):
            rr, cc = divmod(j, 4)
            sheet[rr * h:(rr + 1) * h, cc * w:(cc + 1) * w] = t
        cv2.imwrite(str(out_dir / f"sheet_{i // 12:02d}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])

    summary = {"model": MODELS[name][0], "frames": len(results), "questions": len(QUESTIONS),
               "sec_per_question": round(float(np.mean(lat)), 3),
               "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2),
               "checks_passed": f"{ok}/{total}", "check_misses": misses}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])

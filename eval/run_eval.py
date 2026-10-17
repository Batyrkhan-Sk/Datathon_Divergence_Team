"""Run the pipeline on the labelled training videos and score it.

    python -m eval.run_eval                       # all 42 videos
    python -m eval.run_eval --layouts D E         # only some room layouts
    python -m eval.run_eval --videos X-26 X-29    # specific videos

Metrics follow the case scoring:
  detection      verdict per video; misses and false alarms listed by name
  localisation   |predicted timecode - label| for correctly flagged videos
  classification type match, only on videos whose type is confidently known
  runtime        seconds per video, flagged above the 60 s budget
A JSON report (no images) is written to out/eval/ for comparing runs.
"""
import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from ml.pipeline import analyze

ROOT = Path(__file__).resolve().parent.parent
LABELS = ROOT / "data" / "labels.csv"
VIDEOS = ROOT / "data" / "raw"
OUT = ROOT / "out" / "eval"
RUNTIME_BUDGET = 60.0
TYPE_WINDOW = 3.0   # a predicted event within ±3 s of the label counts for type matching


def load_labels():
    with open(LABELS, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["violation"] = r["violation"] == "1"
        r["label_t"] = float(r["label_t"]) if r["label_t"] else None
    return rows


def score_video(lab, result):
    events = [(v["type_id"], v["timecode_sec"], v["confidence"]) for v in result["violations"]]
    pred = result["verdict"] == "violation"
    rec = {"video": lab["video"], "layout": lab["layout"], "gt": lab["violation"],
           "pred": pred, "label_t": lab["label_t"], "gt_type": lab["type_id"],
           "type_confident": lab["type_confident"] == "yes",
           "events": events, "runtime": result["processing_sec"]}
    if lab["violation"] and pred and lab["label_t"] is not None:
        nearest = min(events, key=lambda e: abs(e[1] - lab["label_t"]))
        rec["t_err"] = abs(nearest[1] - lab["label_t"])
        near = [e for e in events if abs(e[1] - lab["label_t"]) <= TYPE_WINDOW]
        rec["type_ok"] = any(e[0] == lab["type_id"] for e in near)
    return rec


def summarize(recs):
    tp = [r for r in recs if r["gt"] and r["pred"]]
    fn = [r for r in recs if r["gt"] and not r["pred"]]
    fp = [r for r in recs if not r["gt"] and r["pred"]]
    tn = [r for r in recs if not r["gt"] and not r["pred"]]
    n_pos, n_neg = len(tp) + len(fn), len(fp) + len(tn)
    errs = [r["t_err"] for r in tp if "t_err" in r]
    typed = [r for r in tp if r["type_confident"]]
    runtimes = [r["runtime"] for r in recs]
    return {
        "videos": len(recs),
        "accuracy": round((len(tp) + len(tn)) / max(1, len(recs)), 3),
        "recall_violations": round(len(tp) / max(1, n_pos), 3),
        "false_alarm_rate_clean": round(len(fp) / max(1, n_neg), 3),
        "missed": [r["video"] for r in fn],
        "false_alarms": [r["video"] for r in fp],
        "timecode_mean_abs_err": round(statistics.mean(errs), 2) if errs else None,
        "timecode_within_1s": round(sum(e <= 1 for e in errs) / len(errs), 3) if errs else None,
        "timecode_within_2s": round(sum(e <= 2 for e in errs) / len(errs), 3) if errs else None,
        "type_accuracy_confident": (round(sum(r["type_ok"] for r in typed) / len(typed), 3)
                                    if typed else None),
        "type_wrong": [f'{r["video"]}(gt={r["gt_type"]})' for r in typed if not r["type_ok"]],
        "runtime_mean": round(statistics.mean(runtimes), 1) if runtimes else None,
        "runtime_max": round(max(runtimes), 1) if runtimes else None,
        "over_budget": [r["video"] for r in recs if r["runtime"] > RUNTIME_BUDGET],
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", nargs="*")
    ap.add_argument("--layouts", nargs="*")
    ap.add_argument("--tag", default="", help="label for the report file")
    args = ap.parse_args()

    labels = load_labels()
    if args.videos:
        labels = [l for l in labels if l["video"] in set(args.videos)]
    if args.layouts:
        labels = [l for l in labels if l["layout"] in set(args.layouts)]

    recs = []
    for lab in labels:
        result = analyze(str(VIDEOS / f'{lab["video"]}.mov'))
        rec = score_video(lab, result)
        recs.append(rec)
        mark = "OK " if rec["gt"] == rec["pred"] else ("MISS" if rec["gt"] else "FA ")
        ev = ", ".join(f"{t}@{s:.1f}s({c:.2f})" for t, s, c in rec["events"]) or "-"
        print(f'{mark} {lab["video"]:5} [{lab["layout"]}] gt={"V" if rec["gt"] else "-"}'
              f'@{lab["label_t"] or "":<4} {rec["runtime"]:5.1f}s  {ev}', flush=True)

    overall = summarize(recs)
    by_layout = defaultdict(list)
    for r in recs:
        by_layout[r["layout"]].append(r)
    per_layout = {k: summarize(v) for k, v in sorted(by_layout.items())}

    print("\n== overall")
    for k, v in overall.items():
        print(f"  {k:26} {v}")
    print("\n== per layout (recall / false-alarm rate / timecode err)")
    for k, s in per_layout.items():
        print(f'  {k}: n={s["videos"]:2}  recall={s["recall_violations"]}  '
              f'FA={s["false_alarm_rate_clean"]}  t_err={s["timecode_mean_abs_err"]}')

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = OUT / f"{stamp}{'-' + args.tag if args.tag else ''}.json"
    path.write_text(json.dumps({"overall": overall, "per_layout": per_layout, "videos": recs},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

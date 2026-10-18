"""Evaluation denominators and failure semantics; no model or media imports."""
import math
from numbers import Real
import statistics

TIME_WINDOWS = (1, 2, 5)  # Diagnostic tolerances, not jury scoring rules.
TYPE_WINDOW = 3.0
SERVICE_BUDGET_SEC = 300.0


def number(value):
    return (isinstance(value, Real) and not isinstance(value, bool)
            and math.isfinite(value))


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def score_record(sample, result=None, *, status="pending", elapsed_sec=None):
    """Labels stay in the evaluator. None/failed/invalid is never a clean prediction."""
    rec = {"sample_id": sample["sample_id"], "status": status,
           "gt": sample["gt"], "label_t": sample["label_t"],
           "gt_type": sample["gt_type"], "type_confident": sample["type_confident"],
           "pred": None, "events": [], "elapsed_sec": elapsed_sec}
    if status != "completed":
        return rec

    def invalid(reason):
        rec.update(status="invalid", reason=reason)
        return rec

    if not isinstance(result, dict):
        return invalid("result_not_object")
    if result.get("status", "done") == "failed":
        rec.update(status="failed", reason="analyzer_reported_failure")
        return rec
    if result.get("status", "done") != "done" or result.get("error"):
        return invalid("result_not_successful")
    verdict, violations = result.get("verdict"), result.get("violations")
    if verdict not in ("violation", "no_violation") or not isinstance(violations, list):
        return invalid("missing_verdict_or_event_list")
    if (verdict == "violation") != bool(violations):
        return invalid("verdict_event_contradiction")
    events = []
    for event in violations:
        if not isinstance(event, dict):
            return invalid("event_not_object")
        timestamp = event.get("timecode_sec")
        if not number(timestamp) or timestamp < 0:
            return invalid("invalid_event_time")
        duration = result.get("video_duration_sec")
        if number(duration) and timestamp > duration:
            return invalid("event_after_video_end")
        type_id = event.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            return invalid("invalid_event_type")
        events.append({"type_id": type_id, "timecode_sec": float(timestamp)})
    if number(elapsed_sec) and elapsed_sec > SERVICE_BUDGET_SEC:
        rec.update(status="over_budget", late_pred=verdict == "violation", events=events)
        return rec
    rec.update(pred=verdict == "violation", events=events)
    if rec["gt"] is True and rec["pred"] and rec["label_t"] is not None:
        rec["time_error_sec"] = min(abs(e["timecode_sec"] - rec["label_t"]) for e in events)
        rec["type_match"] = bool(rec["gt_type"]) and any(
            e["type_id"] == rec["gt_type"] and abs(e["timecode_sec"] - rec["label_t"]) <= TYPE_WINDOW
            for e in events)
    return rec


def summarize(records):
    """Aggregate only. Unfinished jobs remain in the requested denominator."""
    ids = [r["sample_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate sample records would inflate metrics")
    completed = [r for r in records if r["status"] == "completed"]
    if any(not isinstance(r["pred"], bool) for r in completed):
        raise ValueError("completed records must have a known prediction")
    labelled = [r for r in records if isinstance(r["gt"], bool)]
    valid = [r for r in completed if isinstance(r["gt"], bool)]
    positives = [r for r in labelled if r["gt"]]
    unknown = [r for r in labelled if r["status"] != "completed"]
    tp = sum(r["gt"] and r["pred"] for r in valid)
    fn = sum(r["gt"] and not r["pred"] for r in valid)
    fp = sum(not r["gt"] and r["pred"] for r in valid)
    tn = sum(not r["gt"] and not r["pred"] for r in valid)
    timed = [r for r in positives if r["label_t"] is not None]
    errors = [r["time_error_sec"] for r in timed if "time_error_sec" in r]
    typed = [r for r in timed if r["type_confident"] and r["gt_type"]]
    found_typed = [r for r in typed if r["status"] == "completed" and r["pred"]]
    type_matches = sum(r.get("type_match", False) for r in typed)
    runtimes = [r["elapsed_sec"] for r in records
                if number(r.get("elapsed_sec")) and r["elapsed_sec"] >= 0]
    return {
        "requested_unique_samples": len(records),
        "completed": len(completed), "completion_rate": ratio(len(completed), len(records)),
        "status_counts": {s: sum(r["status"] == s for r in records)
                          for s in sorted({r["status"] for r in records})},
        "binary": {
            "labelled_samples": len(labelled), "unscorable_label_samples": len(records) - len(labelled),
            "tp": tp, "fn_completed": fn, "fp": fp, "tn": tn,
            "unknown_positive": sum(r["gt"] for r in unknown),
            "unknown_negative": sum(not r["gt"] for r in unknown),
            "accuracy_completed": ratio(tp + tn, len(valid)),
            "correct_fraction_all_labelled_requests": ratio(tp + tn, len(labelled)),
            "recall_completed_positives": ratio(tp, tp + fn),
            "detection_recall_all_positives": ratio(tp, len(positives)),
            "false_alarm_rate_completed_negatives": ratio(fp, fp + tn),
        },
        "localization": {
            "scorable_positive_samples": len(timed),
            "positive_samples_without_unambiguous_time": len(positives) - len(timed),
            "found_positive_samples_with_time": len(errors),
            "mean_abs_error_found_only_sec": statistics.mean(errors) if errors else None,
            "diagnostic_windows_sec": list(TIME_WINDOWS),
            "annotated_video_time_recall_all_positives": {
                str(w): ratio(sum(e <= w for e in errors), len(timed)) for w in TIME_WINDOWS},
            "within_window_found_only": {
                str(w): ratio(sum(e <= w for e in errors), len(errors)) for w in TIME_WINDOWS},
            "complete_multi_event_recall_measured": False,
        },
        "classification": {
            "label_origin": "team annotations, not official class labels",
            "scorable_confident_positive_samples": len(typed),
            "matches_within_type_window": type_matches, "diagnostic_window_sec": TYPE_WINDOW,
            "type_recall_all_scorable_positives": ratio(type_matches, len(typed)),
            "type_accuracy_found_only": ratio(type_matches, len(found_typed)),
        },
        "runtime_sec": {
            "measured_samples": len(runtimes),
            "mean": statistics.mean(runtimes) if runtimes else None,
            "median": statistics.median(runtimes) if runtimes else None,
            "max": max(runtimes) if runtimes else None,
            "over_300_sec": sum(t > SERVICE_BUDGET_SEC for t in runtimes),
            "hard_timeout_enforced": False, "includes_api_queue_and_upload": False,
        },
    }

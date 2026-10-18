"""Private, reproducible development evaluation. CLI prints aggregates only.

Prepare a manifest first; run explicitly in an isolated environment with cached
weights. No inference runs when preparing or comparing. Raw logs stay local.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import traceback

from .quality_metrics import score_record, summarize

ROOT = Path(__file__).resolve().parents[1]
CONFIG_KEYS = ("ML_USE_VLM", "ML_SAFE_KEY_RULE", "ML_IGNORE_LAPTOP",
               "ML_OBJECTS_CACHE", "VLM_MODEL", "VLM_DEVICE", "VLM_MAX_SIDE",
               "CUDA_VISIBLE_DEVICES")


class AuditError(ValueError):
    """A public diagnostic with fixed text, free of private input values."""


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def dataset_fingerprint(samples):
    return fingerprint([{k: sample[k] for k in
                         ("sample_id", "sha256", "gt", "label_t", "gt_type", "type_confident")}
                        for sample in samples])


def source_snapshot(root=ROOT):
    paths = [p for folder in ("ml", "backend/app", "eval")
             for p in (root / folder).rglob("*.py")]
    paths += [root / "data/rules.json"]
    hashes = {str(p.relative_to(root)): digest(p) for p in sorted(paths) if p.is_file()}
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    return {"git_head": head, "files_sha256": hashes, "source_digest": fingerprint(hashes)}


def video_key(value):
    match = re.fullmatch(r"[XХxх]\s*[-_]\s*(\d+)", Path(str(value).strip()).stem)
    if match is None:
        raise AuditError("unsupported label identifier format")
    return "X-" + str(int(match.group(1)))


def official_seconds(value):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, bool):
        raise AuditError("invalid official timestamp")
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    match = re.fullmatch(r"(?:(\d+)\s*минут[аы]?\s*)?(\d+(?:[.,]\d+)?)\s*секунд[аы]?", text)
    if match is None:
        raise AuditError("unsupported official timestamp format")
    return int(match.group(1) or 0) * 60 + float(match.group(2).replace(",", "."))


def load_labels(csv_path, official_path):
    """Verify binary/time CSV fields against the official XLSX; types remain team labels."""
    from openpyxl import load_workbook
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    parsed = {}
    for row in rows:
        key = video_key(row["video"])
        if key in parsed or row["violation"] not in ("0", "1"):
            raise AuditError("duplicate identifier or invalid binary label")
        timestamp = float(row["label_t"]) if row["label_t"] else None
        if timestamp is not None and (not math.isfinite(timestamp) or timestamp < 0):
            raise AuditError("invalid CSV timestamp")
        parsed[key] = {"video": key, "gt": row["violation"] == "1", "label_t": timestamp,
                       "gt_type": row["type_id"] or None,
                       "type_confident": row["type_confident"] == "yes", "layout": row["layout"]}
    book = load_workbook(official_path, read_only=True, data_only=True)
    official = {}
    try:
        for row in list(book.active.values)[1:]:
            if not any(x is not None for x in row):
                continue
            key = video_key(row[0])
            verdict = str(row[2]).strip().lower()
            if key in official or verdict not in ("нарушение", "без нарушения"):
                raise AuditError("duplicate identifier or unknown official verdict")
            official[key] = (verdict == "нарушение", official_seconds(row[1]))
    finally:
        book.close()
    if set(parsed) != set(official) or any(
            (row["gt"], row["label_t"]) != official[key] for key, row in parsed.items()):
        raise AuditError("CSV binary/time labels differ from official XLSX; resolve before evaluation")
    return list(parsed.values())


def build_manifest(labels, video_dir, *, source=None):
    """Deduplicate by bytes; conflicting annotations stay unknown for that metric."""
    files = defaultdict(list)
    for path in Path(video_dir).rglob("*"):
        if path.is_file() and path.suffix.lower() == ".mov":
            try:
                files[video_key(path.name)].append(path.resolve())
            except ValueError:
                continue
    groups = defaultdict(list)
    missing = []
    for label in labels:
        matches = files.get(label["video"], [])
        if len(matches) > 1:
            raise AuditError("multiple paths match one label identifier; choose an unambiguous input directory")
        if not matches:
            missing.append((label, None, None))
            continue
        path = matches[0]
        sha = digest(path)
        groups[sha].append((label, path, sha))
    grouped = list(groups.values()) + [[entry] for entry in missing]
    samples = []
    for entries in grouped:
        entries.sort(key=lambda x: x[0]["video"])
        first, path, sha = entries[0]
        conflicts = []
        merged = {}
        for field in ("gt", "label_t", "gt_type"):
            values = {row[field] for row, _, _ in entries}
            if len(values) > 1:
                conflicts.append(field)
            merged[field] = next(iter(values)) if len(values) == 1 else None
        samples.append({"sample_id": sha or "missing-" + first["video"],
                        "path": str(path) if path else None, "sha256": sha,
                        "aliases": [row["video"] for row, _, _ in entries],
                        "layouts": sorted({row["layout"] for row, _, _ in entries}),
                        **merged, "label_conflicts": conflicts,
                        "type_confident": merged["gt_type"] is not None
                        and all(row["type_confident"] for row, _, _ in entries)})
    samples.sort(key=lambda s: s["sample_id"])
    return {"schema_version": 1, "kind": "quality_manifest", "source": source or source_snapshot(),
            "dataset_digest": dataset_fingerprint(samples), "samples": samples,
            "independent_test_claimed": False,
            "split_note": "development data; C and E have prior development/evaluation exposure",
            "data_summary": {"requested_label_rows": len(labels), "unique_samples": len(samples),
                             "missing_files": len(missing),
                             "duplicate_files_removed": len(labels) - len(samples),
                             "conflicting_groups": sum(bool(s["label_conflicts"]) for s in samples),
                             "conflicts_by_field": dict(Counter(f for s in samples for f in s["label_conflicts"]))}}


def save_private(path, data, *, create=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if create:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as dest:
            dest.write(payload)
    else:
        fd, temporary = tempfile.mkstemp(prefix=".audit-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as dest:
                dest.write(payload)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


@contextmanager
def private_output(log):
    """Capture Python and native model diagnostics in a private local file."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved = [os.dup(fd) for fd in (1, 2)]
    try:
        os.dup2(log.fileno(), 1)
        os.dup2(log.fileno(), 2)
        with redirect_stdout(log), redirect_stderr(log):
            yield
    finally:
        log.flush()
        for fd, previous in zip((1, 2), saved):
            os.dup2(previous, fd)
            os.close(previous)


def run_manifest(manifest, output, *, analyzer=None, enforce_snapshot=True):
    """Direct-pipeline development evaluation, not an API load test or a hard deadline."""
    if manifest.get("kind") != "quality_manifest" or manifest.get("schema_version") != 1:
        raise AuditError("unsupported manifest format")
    if not manifest.get("samples"):
        raise AuditError("manifest has no requested samples")
    if os.environ.get("ML_OBJECTS_CACHE"):
        raise AuditError("cached detections have no verified provenance; unset ML_OBJECTS_CACHE")
    if manifest["dataset_digest"] != dataset_fingerprint(manifest["samples"]):
        raise AuditError("manifest inputs or labels changed; prepare a new manifest")
    current_source = source_snapshot()
    if enforce_snapshot and manifest["source"]["source_digest"] != current_source["source_digest"]:
        raise AuditError("source changed after preparation; prepare a new manifest")
    records = [score_record(s, status="missing" if s["path"] is None else "pending")
               for s in manifest["samples"]]
    report = {"schema_version": 1, "kind": "quality_report", "manifest": manifest,
              "source_at_run": current_source, "records": records, "overall": summarize(records),
              "model_config_requested": {k: os.environ.get(k) for k in CONFIG_KEYS},
              "runtime_model_and_weights_verified": False, "independent_test_claimed": False,
              "run_finished": False, "model_load_sec": None}
    save_private(output, report, create=True)
    log_path = Path(output).with_suffix(".private.log")
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as log:
        load_error = None
        started = time.perf_counter()
        try:
            with private_output(log):
                if analyzer is None:
                    os.environ["HF_HUB_OFFLINE"] = "1"
                    os.environ["TRANSFORMERS_OFFLINE"] = "1"
                    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
                    from ml.pipeline import analyze, warmup
                    warmup()
                    analyzer = analyze
        except Exception as exc:
            load_error = type(exc).__name__
            traceback.print_exc(file=log)
        report["model_load_sec"] = time.perf_counter() - started
        try:
            for index, sample in enumerate(manifest["samples"]):
                if sample["path"] is None:
                    continue
                started = time.perf_counter()
                try:
                    if load_error:
                        records[index] = score_record(sample, status="failed")
                        records[index]["reason"] = "model_load_failed"
                        continue
                    if digest(sample["path"]) != sample["sha256"]:
                        records[index] = score_record(sample, status="invalid")
                        records[index]["reason"] = "input_changed_after_manifest"
                        continue
                    with private_output(log):
                        # Only the video path is passed. No labels, event classes or seconds.
                        result = analyzer(sample["path"])
                    elapsed = time.perf_counter() - started
                    records[index] = score_record(sample, result, status="completed", elapsed_sec=elapsed)
                except Exception as exc:
                    traceback.print_exc(file=log)
                    records[index] = score_record(sample, status="failed",
                                                  elapsed_sec=time.perf_counter() - started)
                    records[index]["reason"] = "analyzer_or_input_exception"
                    records[index]["exception_class"] = type(exc).__name__
                finally:
                    report["overall"] = summarize(records)
                    save_private(output, report)
            report["run_finished"] = True
        finally:
            report["overall"] = summarize(records)
            report["model_load_error_class"] = load_error
            save_private(output, report)
    return report


def compare_reports(left, right):
    for report in (left, right):
        if report.get("kind") != "quality_report" or report.get("schema_version") != 1:
            raise AuditError("only quality_report v1 reports can be compared; historical reports lack this contract")
        if report["overall"] != summarize(report["records"]):
            raise AuditError("stored summary differs from saved records")
        if report["manifest"]["dataset_digest"] != dataset_fingerprint(report["manifest"]["samples"]):
            raise AuditError("saved manifest inputs or labels changed")
        samples = {s["sample_id"]: s for s in report["manifest"]["samples"]}
        if (len(samples) != len(report["manifest"]["samples"])
                or set(samples) != {r["sample_id"] for r in report["records"]}):
            raise AuditError("saved records do not cover the requested samples")
        for rec in report["records"]:
            sample = samples[rec["sample_id"]]
            if any(rec[k] != sample[k] for k in ("gt", "label_t", "gt_type", "type_confident")):
                raise AuditError("record labels differ from the prepared manifest")
            if rec["status"] not in ("completed", "over_budget", "pending", "missing", "failed", "invalid"):
                raise AuditError("unknown saved processing status")
            completed = rec["status"] in ("completed", "over_budget")
            pred = rec.get("late_pred") if rec["status"] == "over_budget" else rec["pred"]
            result = {"verdict": "violation" if pred else "no_violation", "violations": rec["events"]}
            expected = score_record(sample, result, status="completed" if completed else rec["status"],
                                    elapsed_sec=rec["elapsed_sec"])
            if any(rec.get(k) != expected.get(k) for k in
                   ("status", "pred", "events", "time_error_sec", "type_match", "late_pred")):
                raise AuditError("saved per-sample metrics disagree with predictions")
    same_data = left["manifest"]["dataset_digest"] == right["manifest"]["dataset_digest"]
    left_metric = left["source_at_run"]["files_sha256"].get("eval/quality_metrics.py")
    right_metric = right["source_at_run"]["files_sha256"].get("eval/quality_metrics.py")
    same_metric_code = bool(left_metric and right_metric and left_metric == right_metric)
    comparable = same_data and same_metric_code
    return {"same_inputs_and_labels": same_data, "same_metric_code": same_metric_code,
            "comparable": comparable, "independent_test_claimed": False,
            "both_runs_finished": bool(left["run_finished"] and right["run_finished"]),
            "runtime_weights_verified_for_both": bool(left["runtime_model_and_weights_verified"]
                                                      and right["runtime_model_and_weights_verified"]),
            "left": left["overall"], "right": right["overall"],
            "detection_recall_change": (right["overall"]["binary"]["detection_recall_all_positives"]
                                        - left["overall"]["binary"]["detection_recall_all_positives"])
            if comparable and all(r["overall"]["binary"]["detection_recall_all_positives"] is not None
                                  for r in (left, right)) else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="verify labels and hash inputs; no model imports")
    prepare.add_argument("--video-dir", required=True, type=Path)
    prepare.add_argument("--labels", type=Path, default=ROOT / "data/labels.csv")
    prepare.add_argument("--official-labels", type=Path, default=ROOT / "data/open_labels.xlsx")
    prepare.add_argument("--output", required=True, type=Path)
    run = commands.add_parser("run", help="run cached local models explicitly; keep raw logs private")
    run.add_argument("--manifest", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    compare = commands.add_parser("compare", help="compare aggregate results on matching inputs and labels")
    compare.add_argument("--left", required=True, type=Path)
    compare.add_argument("--right", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            labels = load_labels(args.labels, args.official_labels)
            manifest = build_manifest(labels, args.video_dir)
            manifest["label_sources"] = {
                "csv_sha256": digest(args.labels), "official_xlsx_sha256": digest(args.official_labels),
                "binary_and_time_match_official": True, "event_types_are_team_annotations": True}
            save_private(args.output, manifest, create=True)
            summary = manifest["data_summary"]
        elif args.command == "run":
            report = run_manifest(json.loads(args.manifest.read_text()), args.output)
            summary = report["overall"]
        else:
            summary = compare_reports(json.loads(args.left.read_text()), json.loads(args.right.read_text()))
        print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
        if args.command == "run" and report["overall"]["completed"] != len(report["records"]):
            return 1
        if args.command == "compare" and not summary["comparable"]:
            return 1
        return 0
    except (ValueError, OSError, KeyError, ImportError) as exc:
        # Do not print raw exception text; it may contain private input identifiers.
        diagnostic = {"audit_error": type(exc).__name__, "completed": False}
        if isinstance(exc, AuditError):
            diagnostic["reason"] = str(exc)
        elif isinstance(exc, FileExistsError):
            diagnostic["reason"] = "output already exists; choose a new path"
        print(json.dumps(diagnostic))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Quality-audit tests use synthetic labels and local dummy bytes, never models."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from eval import quality_audit as audit
from eval.quality_metrics import score_record, summarize


def sample(index=0, positive=True, timestamp=1.0):
    return {"sample_id": str(index), "gt": positive,
            "label_t": timestamp if positive else None,
            "gt_type": "synthetic" if positive else None, "type_confident": positive}


def prediction(positive=True, timestamp=1.0):
    return {"verdict": "violation" if positive else "no_violation",
            "violations": [{"type_id": "synthetic", "timecode_sec": timestamp}] if positive else []}


def test_processing_failure_on_negative_is_not_a_true_negative():
    record = score_record(sample(positive=False), status="failed")
    result = summarize([record])
    assert record["pred"] is None
    assert result["binary"]["tn"] == 0
    assert result["binary"]["unknown_negative"] == 1
    assert result["binary"]["accuracy_completed"] is None
    assert result["completion_rate"] == 0


@pytest.mark.parametrize("bad", [
    None, {}, {"verdict": None, "violations": []},
    {"verdict": "no_violation", "violations": [{}]},
    {"verdict": "violation", "violations": []},
    {"verdict": "violation", "violations": [None]},
    prediction(timestamp=float("nan")), prediction(timestamp=-1),
    prediction(timestamp=True), prediction(timestamp="1"),
    {**prediction(), "video_duration_sec": 0.5},
    {**prediction(False), "status": "processing"},
    {**prediction(False), "error": "synthetic"},
])
def test_invalid_prediction_remains_unknown(bad):
    record = score_record(sample(), bad, status="completed")
    assert record["status"] == "invalid" and record["pred"] is None
    summary = summarize([record])
    assert summary["binary"]["fn_completed"] == 0
    assert summary["binary"]["unknown_positive"] == 1


def test_api_failed_status_stays_failed():
    record = score_record(sample(), {"status": "failed", "verdict": None}, status="completed")
    assert record["status"] == "failed" and record["pred"] is None


def test_time_recall_includes_misses():
    records = [score_record(sample(i), prediction(i == 0), status="completed") for i in range(10)]
    result = summarize(records)
    assert result["localization"]["within_window_found_only"]["2"] == 1.0
    assert result["localization"]["annotated_video_time_recall_all_positives"]["2"] == 0.1
    assert result["classification"]["type_accuracy_found_only"] == 1.0
    assert result["classification"]["type_recall_all_scorable_positives"] == 0.1


def test_pending_and_missing_jobs_are_in_denominators():
    records = [score_record(sample(0), prediction(), status="completed"),
               score_record(sample(1), status="pending"), score_record(sample(2), status="missing")]
    result = summarize(records)
    assert result["completion_rate"] == pytest.approx(1 / 3)
    assert result["binary"]["recall_completed_positives"] == 1
    assert result["binary"]["detection_recall_all_positives"] == pytest.approx(1 / 3)


def test_false_alarms_and_misses_are_counted_separately():
    records = [score_record(sample(0, True), prediction(False), status="completed"),
               score_record(sample(1, False), prediction(True), status="completed"),
               score_record(sample(2, False), prediction(False), status="completed")]
    result = summarize(records)["binary"]
    assert (result["tp"], result["fn_completed"], result["fp"], result["tn"]) == (0, 1, 1, 1)
    assert result["false_alarm_rate_completed_negatives"] == 0.5


def test_conflicting_time_does_not_become_zero_error():
    row = sample(timestamp=None)
    result = summarize([score_record(row, prediction(), status="completed")])
    assert result["localization"]["scorable_positive_samples"] == 0
    assert result["localization"]["annotated_video_time_recall_all_positives"]["2"] is None
    assert result["classification"]["scorable_confident_positive_samples"] == 0
    assert result["binary"]["tp"] == 1


def test_duplicate_score_records_are_rejected():
    row = score_record(sample(), prediction(), status="completed")
    with pytest.raises(ValueError):
        summarize([row, row])


def test_runtime_uses_measured_wall_time_and_300_second_budget():
    result = summarize([score_record(sample(), {**prediction(), "processing_sec": 0},
                                     status="completed", elapsed_sec=301)])
    assert result["runtime_sec"]["max"] == 301
    assert result["runtime_sec"]["over_300_sec"] == 1
    assert result["runtime_sec"]["hard_timeout_enforced"] is False
    assert result["completed"] == 0
    assert result["status_counts"] == {"over_budget": 1}
    assert result["binary"]["unknown_positive"] == 1


def label(index, **updates):
    return {"video": f"X-{index}", "gt": True, "label_t": 1.0,
            "gt_type": "synthetic", "type_confident": True, "layout": "C", **updates}


def test_byte_duplicates_keep_binary_but_mask_conflicting_time_and_type(tmp_path):
    (tmp_path / "X-1.mov").write_bytes(b"synthetic identical bytes")
    (tmp_path / "X-2.mov").write_bytes(b"synthetic identical bytes")
    manifest = audit.build_manifest([label(1), label(2, label_t=2.0, gt_type="other")], tmp_path)
    assert len(manifest["samples"]) == 1
    row = manifest["samples"][0]
    assert row["gt"] is True and row["label_t"] is None and row["gt_type"] is None
    assert row["type_confident"] is False
    assert manifest["data_summary"]["duplicate_files_removed"] == 1
    assert manifest["independent_test_claimed"] is False


def test_missing_file_remains_in_manifest(tmp_path):
    manifest = audit.build_manifest([label(1)], tmp_path)
    assert manifest["samples"][0]["path"] is None
    assert manifest["data_summary"]["missing_files"] == 1


@pytest.mark.parametrize("value,expected", [(None, None), ("1минута 5 секунда", 65),
                                           ("11 секунда", 11), ("0", 0), (2.5, 2.5)])
def test_official_time_formats(value, expected):
    assert audit.official_seconds(value) == expected


def test_unknown_official_time_is_not_zero():
    with pytest.raises(ValueError):
        audit.official_seconds("not a timestamp")


def make_manifest(tmp_path, count=2):
    for i in range(count):
        (tmp_path / f"X-{i}.mov").write_bytes(f"synthetic input {i}".encode())
    return audit.build_manifest([label(i) for i in range(count)], tmp_path)


def test_runner_passes_only_video_path_and_keeps_diagnostics_private(tmp_path, capfd):
    manifest = make_manifest(tmp_path)
    calls = []
    def analyzer(*args, **kwargs):
        calls.append((args, kwargs))
        print("PRIVATE_MODEL_OUTPUT_SENTINEL")
        os.write(2, b"PRIVATE_NATIVE_OUTPUT_SENTINEL\n")
        if len(calls) == 1:
            raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")
        return prediction()
    output = tmp_path / "out/report.json"
    report = audit.run_manifest(manifest, output, analyzer=analyzer)
    assert len(calls) == 2
    assert all(len(args) == 1 and isinstance(args[0], str) and not kwargs for args, kwargs in calls)
    assert report["overall"]["completed"] == 1
    assert report["overall"]["status_counts"]["failed"] == 1
    assert report["run_finished"] is True
    captured = capfd.readouterr()
    assert "PRIVATE_" not in captured.out + captured.err
    saved = output.read_text()
    assert "PRIVATE_" not in saved
    log = output.with_suffix(".private.log").read_text()
    assert "PRIVATE_MODEL_OUTPUT_SENTINEL" in log
    assert "PRIVATE_NATIVE_OUTPUT_SENTINEL" in log and "PRIVATE_EXCEPTION_SENTINEL" in log
    assert output.stat().st_mode & 0o777 == 0o600


def test_changed_video_is_not_silently_evaluated(tmp_path):
    manifest = make_manifest(tmp_path, 1)
    Path(manifest["samples"][0]["path"]).write_bytes(b"changed synthetic bytes")
    called = []
    report = audit.run_manifest(manifest, tmp_path / "out.json", analyzer=lambda p: called.append(p))
    assert not called
    assert report["records"][0]["status"] == "invalid"
    assert report["overall"]["completion_rate"] == 0


def test_checkpoint_keeps_interrupted_jobs_pending(tmp_path):
    manifest = make_manifest(tmp_path)
    output = tmp_path / "report.json"
    def interrupted(path):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        audit.run_manifest(manifest, output, analyzer=interrupted)
    report = json.loads(output.read_text())
    assert report["run_finished"] is False
    assert report["overall"]["status_counts"] == {"pending": 2}


def test_source_changes_require_new_manifest(tmp_path):
    manifest = make_manifest(tmp_path)
    manifest["source"]["source_digest"] = "stale"
    with pytest.raises(ValueError):
        audit.run_manifest(manifest, tmp_path / "report.json", analyzer=lambda p: prediction())
    assert not (tmp_path / "report.json").exists()


def test_comparison_refuses_changed_dataset_and_recomputes_summaries(tmp_path):
    manifest = make_manifest(tmp_path, 1)
    report = audit.run_manifest(manifest, tmp_path / "report.json", analyzer=lambda p: prediction())
    same = audit.compare_reports(report, deepcopy(report))
    assert same["comparable"] and same["detection_recall_change"] == 0
    different_manifest = deepcopy(manifest)
    different_manifest["samples"][0]["gt_type"] = "different"
    different_manifest["dataset_digest"] = audit.dataset_fingerprint(different_manifest["samples"])
    different = audit.run_manifest(different_manifest, tmp_path / "different.json", analyzer=lambda p: prediction())
    assert audit.compare_reports(report, different)["detection_recall_change"] is None
    assert not audit.compare_reports(report, different)["comparable"]
    corrupt = deepcopy(report)
    corrupt["overall"]["binary"]["tp"] = 999
    with pytest.raises(ValueError):
        audit.compare_reports(report, corrupt)


def test_existing_reports_are_never_overwritten(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("original")
    with pytest.raises(FileExistsError):
        audit.save_private(path, {"test": True}, create=True)
    assert path.read_text() == "original"


def test_official_binary_and_time_fields_are_checked_but_types_are_not_official(tmp_path, monkeypatch):
    csv = tmp_path / "labels.csv"
    csv.write_text("video,violation,label_t,type_id,type_confident,layout\nX-1,1,11,team_type,yes,C\n")
    def workbook(*args, **kwargs):
        return SimpleNamespace(active=SimpleNamespace(values=[
            ("filename", "time", "verdict"), ("X-1.mov", "11 секунда", "нарушение")]), close=lambda: None)
    monkeypatch.setitem(sys.modules, "openpyxl", SimpleNamespace(load_workbook=workbook))
    labels = audit.load_labels(csv, tmp_path / "official.xlsx")
    assert labels[0]["gt"] is True and labels[0]["label_t"] == 11
    assert labels[0]["gt_type"] == "team_type"
    csv.write_text(csv.read_text().replace(",11,", ",12,"))
    with pytest.raises(audit.AuditError, match="differ from official"):
        audit.load_labels(csv, tmp_path / "official.xlsx")


def test_changed_manifest_labels_are_rejected(tmp_path):
    manifest = make_manifest(tmp_path, 1)
    manifest["samples"][0]["label_t"] = 999
    with pytest.raises(audit.AuditError, match="inputs or labels changed"):
        audit.run_manifest(manifest, tmp_path / "report.json", analyzer=lambda p: prediction())


@pytest.mark.parametrize("change", ["missing_record", "label", "time_error"])
def test_comparison_rejects_inconsistent_records_even_with_updated_totals(tmp_path, change):
    manifest = make_manifest(tmp_path, 1)
    report = audit.run_manifest(manifest, tmp_path / "report.json", analyzer=lambda p: prediction())
    corrupt = deepcopy(report)
    if change == "missing_record":
        corrupt["records"] = []
    elif change == "label":
        corrupt["records"][0]["label_t"] = 99
    else:
        corrupt["records"][0]["time_error_sec"] = 99
    corrupt["overall"] = summarize(corrupt["records"])
    with pytest.raises(audit.AuditError):
        audit.compare_reports(report, corrupt)


def test_unverified_detection_cache_is_rejected(tmp_path, monkeypatch):
    manifest = make_manifest(tmp_path, 1)
    monkeypatch.setenv("ML_OBJECTS_CACHE", "synthetic-cache")
    with pytest.raises(audit.AuditError, match="cached detections"):
        audit.run_manifest(manifest, tmp_path / "report.json", analyzer=lambda p: prediction())
    assert not (tmp_path / "report.json").exists()

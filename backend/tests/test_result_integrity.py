"""Source evidence and failure semantics using generated media only."""
import base64
import time
from copy import deepcopy

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import results
from backend.app.api import create_app
from backend.app.config import Settings
from backend.tests.integrity_stubs import valid
from ml import video
from ml.evidence import frames_for
from ml.events import Event


@pytest.mark.parametrize("raw", [
    None, [], {}, {"status": "failed"},
    {"verdict": None, "violations": []},
    {"verdict": "no_violation"},
    {"verdict": "violation", "violations": []},
    {"verdict": "no_violation", "violations": [{}]},
    {"verdict": "no_violation", "violations": [], "status": "processing"},
    {"verdict": "no_violation", "violations": [], "error": "synthetic error"},
    {"verdict": "violation", "violations": ["garbage"]},
])
def test_unknown_or_inconsistent_result_is_not_clean(raw, synthetic_video):
    with pytest.raises(results.InvalidResult):
        results.normalize(raw, str(synthetic_video))


def test_explicit_successful_clean_result_is_preserved(synthetic_video):
    raw = {"verdict": "no_violation", "violations": []}
    assert results.normalize(raw, str(synthetic_video)) == raw


@pytest.mark.parametrize("field,value", [
    ("timecode_sec", -1), ("timecode_sec", float("nan")),
    ("timecode_sec", float("inf")), ("timecode_sec", 50),
    ("timecode_sec", True), ("timecode_sec", "0.5"),
    ("description", ""), ("description", None), ("type", ""),
    ("confidence", 1.1), ("confidence", float("nan")),
    ("evidence_frames", None), ("evidence_frames", ["garbage"]),
    ("evidence_frames", [{"timestamp_sec": float("nan")}]),
    ("evidence_frames", [{"timestamp_sec": -1}]),
])
def test_invalid_event_values_are_rejected(field, value, synthetic_video):
    raw = valid(str(synthetic_video))
    raw["violations"][0][field] = value
    with pytest.raises(results.InvalidResult):
        results.normalize(raw, str(synthetic_video))


def test_evidence_comes_from_source_and_reports_actual_time(synthetic_video):
    raw = valid(str(synthetic_video))
    original = deepcopy(raw)
    evidence = results.normalize(raw, str(synthetic_video))["violations"][0]["evidence_frames"][0]
    actual_t, actual_frame = video.read_frame_with_timestamp(str(synthetic_video), 0.53)
    assert evidence["timestamp_sec"] == round(actual_t, 4)
    assert evidence["timestamp_sec"] != 0.53
    assert evidence["image_base64"] == results._encode(actual_frame)
    assert raw == original
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(evidence["image_base64"]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (64, 96, 3)
    assert decoded.std() > 1


def test_direct_ml_evidence_also_uses_decoder_timestamp(synthetic_video):
    event = Event("synthetic", 0.53, confidence=1.0, observation="Generated pattern")
    frame = frames_for(str(synthetic_video), event, 2)[0]
    assert frame["timestamp_sec"] == pytest.approx(0.5)


def test_missing_evidence_is_extracted_at_event_time(synthetic_video):
    raw = valid(str(synthetic_video))
    raw["violations"][0]["evidence_frames"] = []
    ev = results.normalize(raw, str(synthetic_video))["violations"][0]["evidence_frames"]
    assert len(ev) == 1 and ev[0]["timestamp_sec"] == pytest.approx(0.5)


def test_decode_failure_has_no_placeholder_or_first_frame_fallback(monkeypatch):
    requested = []
    def missing(path, timestamp):
        requested.append(timestamp)
        return None
    monkeypatch.setattr(results, "read_frame_with_timestamp", missing)
    with pytest.raises(results.EvidenceUnavailable):
        results.frame_at("synthetic", 10, 20)
    assert requested == [10]


def test_encode_failure_is_an_error(synthetic_video, monkeypatch):
    monkeypatch.setattr(results, "_encode", lambda frame: None)
    with pytest.raises(results.EvidenceUnavailable):
        results.frame_at(str(synthetic_video), 0.5, 2)


def test_jpeg_magic_bytes_do_not_prove_decodability():
    assert results.as_jpeg_base64(base64.b64encode(b"\xff\xd8invalid").decode()) is None


def test_source_failure_is_not_successful_clean_result(monkeypatch):
    def fail(path):
        raise ValueError("synthetic missing video")
    monkeypatch.setattr(results, "probe", fail)
    with pytest.raises(ValueError):
        results.normalize({"verdict": "no_violation", "violations": []}, "synthetic")


def test_no_frame_beyond_video_end(synthetic_video):
    assert video.read_frame_with_timestamp(str(synthetic_video), 50) is None


def test_sampling_covers_generated_video(synthetic_video):
    samples = list(video.iter_frames(str(synthetic_video), 2))
    assert [t for t, _ in samples] == pytest.approx([0, 0.5, 1, 1.5])


class FakeCapture:
    def __init__(self, times, expected=None, retrieved=True):
        self.times, self.index, self.released = times, -1, False
        self.expected = expected if expected is not None else len(times)
        self.retrieved = retrieved

    def isOpened(self):
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FPS:
            return 10.0
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return self.expected
        if prop == cv2.CAP_PROP_POS_MSEC:
            return self.times[max(0, self.index)] * 1000
        return 0

    def set(self, *args):
        return True

    def read(self):
        self.index = 0
        return self.retrieve()

    def grab(self):
        self.index += 1
        return self.index < len(self.times)

    def retrieve(self):
        return (True, np.zeros((2, 2, 3), np.uint8)) if self.retrieved else (False, None)

    def release(self):
        self.released = True


def test_variable_timestamps_use_actual_frame_time(monkeypatch):
    captures = [FakeCapture([0.4]), FakeCapture([0, 0.6, 1.7, 1.9])]
    pending = iter(captures)
    monkeypatch.setattr(video.cv2, "VideoCapture", lambda _: next(pending))
    at, _ = video.read_frame_with_timestamp("synthetic", 1.3)
    assert at == 1.7
    assert all(c.released for c in captures)


def test_failed_sequential_search_does_not_return_inaccurate_seek_frame(monkeypatch):
    captures = iter([FakeCapture([0.4]), FakeCapture([0, 0.6, 1.7])])
    monkeypatch.setattr(video.cv2, "VideoCapture", lambda _: next(captures))
    assert video.read_frame_with_timestamp("synthetic", 1.9) is None


@pytest.mark.parametrize("capture", [
    FakeCapture([], expected=20),
    FakeCapture([0, 0.1, 0.2], expected=100),
    FakeCapture([0, 0.1], retrieved=False),
])
def test_empty_or_partial_decode_fails(capture, monkeypatch):
    monkeypatch.setattr(video.cv2, "VideoCapture", lambda _: capture)
    with pytest.raises(ValueError):
        list(video.iter_frames("synthetic", 2))
    assert capture.released


def _settings(tmp_path, analyzer, strict):
    return Settings(api_key="synthetic-test-key", analyzer=analyzer,
                    job_timeout_sec=10, load_timeout_sec=20, strict_schema=strict,
                    storage_dir=tmp_path / "storage", frontend_dir=tmp_path / "frontend",
                    max_upload_mb=10, ui_uploads_per_min=100, upload_ttl_hours=24)


def _submit_and_wait(client, path):
    headers = {"X-API-Key": "synthetic-test-key"}
    submitted = client.post("/api/v1/analyze", headers=headers,
                            files={"file": ("synthetic.mov", path.read_bytes())})
    assert submitted.status_code == 200
    job_id = submitted.json()["job_id"]
    until = time.monotonic() + 15
    while time.monotonic() < until:
        response = client.get("/api/v1/jobs/" + job_id, headers=headers)
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "processing":
            return body
        time.sleep(0.05)
    pytest.fail("synthetic job did not finish within 15 seconds")


@pytest.mark.parametrize("strict", [False, True])
def test_worker_keeps_failure_unknown_and_processes_next_job(tmp_path, synthetic_video, strict):
    settings = _settings(tmp_path, "backend.tests.integrity_stubs:invalid_then_valid", strict)
    with TestClient(create_app(settings)) as client:
        failed = _submit_and_wait(client, synthetic_video)
        assert failed["status"] == "failed"
        assert failed["verdict"] is None and failed["violations"] == []
        successful = _submit_and_wait(client, synthetic_video)
        assert successful["status"] == "done" and successful["verdict"] == "violation"
        ev = successful["violations"][0]["evidence_frames"][0]
        assert ev["timestamp_sec"] == pytest.approx(0.5)
        if strict:
            assert set(failed) == {"job_id", "status", "verdict", "violations"}


def test_missing_source_evidence_fails_through_api(tmp_path, synthetic_video):
    settings = _settings(tmp_path, "backend.tests.integrity_stubs:absent_frame", False)
    with TestClient(create_app(settings)) as client:
        body = _submit_and_wait(client, synthetic_video)
        assert body["status"] == "failed" and body["verdict"] is None
        assert "EvidenceUnavailable" in body["error"]


def test_explicit_clean_result_completes_through_api(tmp_path, synthetic_video):
    settings = _settings(tmp_path, "backend.tests.integrity_stubs:clean", True)
    with TestClient(create_app(settings)) as client:
        body = _submit_and_wait(client, synthetic_video)
        assert body["status"] == "done" and body["verdict"] == "no_violation"
        assert body["violations"] == []

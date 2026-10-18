"""API tests against the case contract. Run from the repo root:

    .venv/Scripts/python -m pytest backend/tests -v
"""
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api import create_app
from backend.app.config import ROOT, Settings
from backend.check_api_contract import validate_result

KEY = "test-key-123"
H = {"X-API-Key": KEY}
VIOLATION_VIDEO = ROOT / "data" / "raw" / "X-26.mov"   # 19.8 s
CLEAN_VIDEO = ROOT / "data" / "raw" / "X-29.mov"       # 17.3 s

pytestmark = pytest.mark.skipif(not CLEAN_VIDEO.exists(), reason="sample videos missing")


def settings(tmp: Path, analyzer: str = "demo", **kw) -> Settings:
    base = dict(api_key=KEY, analyzer=analyzer, job_timeout_sec=60, load_timeout_sec=120,
                strict_schema=False, storage_dir=tmp, frontend_dir=tmp / "no-frontend",
                max_upload_mb=300, ui_uploads_per_min=100, upload_ttl_hours=24)
    return Settings(**(base | kw))


@contextmanager
def client(tmp: Path, analyzer: str = "demo", **kw):
    with TestClient(create_app(settings(tmp, analyzer, **kw))) as c:
        yield c


def upload(c: TestClient, video: Path = CLEAN_VIDEO, path="/api/v1/analyze", headers=H,
           field="file", name: str | None = None, data: bytes | None = None):
    content = data if data is not None else video.read_bytes()
    return c.post(path, headers=headers, files={field: (name or video.name, content)})


def wait(c: TestClient, job_id: str, path="/api/v1/jobs/", headers=H, timeout=120) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(path + job_id, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] in ("processing", "done", "failed")
        if body["status"] != "processing":
            return body
        assert body["verdict"] is None and body["violations"] == []
        assert 0 <= body.get("progress", 0) <= 1
        time.sleep(0.3)
    raise AssertionError(f"job {job_id} still processing after {timeout} s")


def assert_contract(body: dict, job_id: str) -> None:
    failed = [(name, detail) for ok, name, detail in validate_result(body, job_id) if not ok]
    assert not failed, failed


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    with client(tmp_path_factory.mktemp("demo")) as c:
        yield c


# -- auth --------------------------------------------------------------------------
def test_health_needs_no_key(demo):
    r = demo.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["worker"] in ("alive", "loading")


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""},
                                     {"Authorization": f"Bearer {KEY}"}])
def test_requests_without_correct_key_are_rejected(demo, headers):
    r = upload(demo, headers=headers)
    assert r.status_code == 401 and "detail" in r.json()
    assert demo.get("/api/v1/jobs/abc", headers=headers).status_code == 401


def test_right_key_is_accepted(demo):
    r = upload(demo)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert isinstance(job_id, str) and all(ch in "0123456789abcdef" for ch in job_id)


def test_unset_api_key_rejects_everything(tmp_path):
    with client(tmp_path, api_key="") as c:
        assert upload(c, headers={"X-API-Key": ""}).status_code == 401
        assert upload(c, headers={"X-API-Key": "anything"}).status_code == 401


# -- uploads -----------------------------------------------------------------------
def test_wrong_field_name(demo):
    r = upload(demo, field="video")
    assert r.status_code == 422 and "'file'" in r.json()["detail"]


def test_not_multipart(demo):
    r = demo.post("/api/v1/analyze", headers=H, json={"file": "x"})
    assert r.status_code == 422


@pytest.mark.parametrize("name,data,code", [
    ("video.txt", b"hello", 400),
    ("video", b"hello", 400),
    ("empty.mov", b"", 400),
    ("garbage.mov", bytes(range(256)) * 200, 400),
], ids=["txt", "no-extension", "empty", "garbage"])
def test_bad_uploads(demo, name, data, code):
    r = upload(demo, name=name, data=data)
    assert r.status_code == code and r.json()["detail"]


def test_extension_case_insensitive_and_mp4(demo):
    assert upload(demo, name="CLIP.MOV").status_code == 200
    assert upload(demo, name="clip.mp4").status_code == 200


def test_too_large(tmp_path):
    with client(tmp_path, max_upload_mb=1) as c:
        r = upload(c)
        assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_unknown_job_is_404(demo):
    assert demo.get("/api/v1/jobs/deadbeef", headers=H).status_code == 404
    assert demo.get("/ui/api/jobs/deadbeef").status_code == 404


# -- full flows ----------------------------------------------------------------------
def test_demo_flow_full_schema(demo):
    job_id = upload(demo, VIOLATION_VIDEO).json()["job_id"]
    body = wait(demo, job_id)
    assert_contract(body, job_id)
    assert list(body)[:4] == ["job_id", "status", "verdict", "violations"]
    assert body["verdict"] == "violation" and 1 <= len(body["violations"]) <= 2
    assert "processing_sec" in body
    for v in body["violations"]:
        assert list(v)[:4] == ["type", "timecode_sec", "description", "evidence_frames"]
        assert v["type_id"] in ("cash_unattended", "safe_left_open")
        assert 0 <= v["confidence"] <= 1 and v["rule"]["url"].startswith("http")
        assert 0 <= v["timecode_sec"] <= 19.8


def test_strict_schema(tmp_path):
    with client(tmp_path, strict_schema=True) as c:
        job_id = upload(c, VIOLATION_VIDEO).json()["job_id"]
        r = c.get(f"/api/v1/jobs/{job_id}", headers=H).json()
        assert set(r) == {"job_id", "status", "verdict", "violations"}   # while processing
        body = wait(c, job_id) if r["status"] == "processing" else r
        assert_contract(body, job_id)
        assert set(body) == {"job_id", "status", "verdict", "violations"}
        for v in body["violations"]:
            assert set(v) == {"type", "timecode_sec", "description", "evidence_frames"}
            for f in v["evidence_frames"]:
                assert set(f) == {"timestamp_sec", "image_base64"}


def test_real_analyzer_clean_video(tmp_path):
    with client(tmp_path, analyzer="real") as c:
        job_id = upload(c, CLEAN_VIDEO).json()["job_id"]
        body = wait(c, job_id, timeout=240)
        assert_contract(body, job_id)
        assert body["verdict"] == "no_violation" and body["violations"] == []


def test_ui_endpoints(tmp_path):
    with client(tmp_path, ui_uploads_per_min=2) as c:
        r = upload(c, path="/ui/api/analyze", headers={})
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        body = wait(c, job_id, path="/ui/api/jobs/", headers={})
        assert_contract(body, job_id)
        assert c.get(f"/ui/api/jobs/{job_id}/video").status_code == 200
        # keyed jobs are not visible through the keyless UI API, UI jobs are via the key
        api_id = upload(c).json()["job_id"]
        assert c.get(f"/ui/api/jobs/{api_id}").status_code == 404
        assert c.get(f"/api/v1/jobs/{job_id}", headers=H).status_code == 200
        # rate limit: 2 per minute per IP
        assert upload(c, path="/ui/api/analyze", headers={}).status_code == 200
        assert upload(c, path="/ui/api/analyze", headers={}).status_code == 429


# -- failures ----------------------------------------------------------------------
def test_timeout_marks_failed_and_restarts_worker(tmp_path):
    with client(tmp_path, analyzer="backend.tests.stubs:slow_on_long_video",
                job_timeout_sec=3) as c:
        slow = upload(c, VIOLATION_VIDEO).json()["job_id"]
        fast = upload(c, CLEAN_VIDEO).json()["job_id"]
        t0 = time.time()
        body = wait(c, slow, timeout=30)
        assert body["status"] == "failed" and "timeout" in body["error"]
        assert body["verdict"] is None and body["violations"] == []
        assert time.time() - t0 < 15
        body = wait(c, fast, timeout=60)        # served by the restarted worker
        assert body["status"] == "done" and body["verdict"] == "no_violation"


def test_worker_crash_marks_failed(tmp_path):
    with client(tmp_path, analyzer="backend.tests.stubs:crash") as c:
        job_id = upload(c).json()["job_id"]
        body = wait(c, job_id, timeout=60)
        assert body["status"] == "failed" and "crash" in body["error"]


def test_analyzer_exception_marks_failed(tmp_path):
    with client(tmp_path, analyzer="backend.tests.stubs:error") as c:
        body = wait(c, upload(c).json()["job_id"], timeout=60)
        assert body["status"] == "failed" and "detector exploded" in body["error"]


def test_analyzer_load_failure_does_not_hang(tmp_path):
    with client(tmp_path, analyzer="no_such_module:analyze") as c:
        body = wait(c, upload(c).json()["job_id"], timeout=60)
        assert body["status"] == "failed" and "load" in body["error"]


def test_messy_output_fails_instead_of_inventing_result(tmp_path):
    with client(tmp_path, analyzer="backend.tests.stubs:messy") as c:
        job_id = upload(c, CLEAN_VIDEO).json()["job_id"]
        body = wait(c, job_id, timeout=60)
        assert body["status"] == "failed"
        assert body["verdict"] is None and body["violations"] == []
        assert "InvalidResult" in body["error"]


# -- persistence -------------------------------------------------------------------
def test_results_survive_restart_and_running_jobs_are_requeued(tmp_path):
    with client(tmp_path) as c:
        job_id = upload(c).json()["job_id"]
        assert wait(c, job_id)["status"] == "done"
    db = sqlite3.connect(tmp_path / "jobs.db")
    db.execute("INSERT INTO jobs (id, source, priority, status, video_path, filename,"
               " created_at, attempts) SELECT 'interrupted', source, priority, 'running',"
               " video_path, filename, created_at, 1 FROM jobs WHERE id = ?", (job_id,))
    db.commit()
    db.close()
    with client(tmp_path) as c:
        assert c.get(f"/api/v1/jobs/{job_id}", headers=H).json()["status"] == "done"
        assert wait(c, "interrupted")["status"] == "done"


def test_old_uploads_are_deleted_on_startup(tmp_path):
    old = tmp_path / "uploads" / "old.mov"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 25 * 3600,) * 2)
    fresh = tmp_path / "uploads" / "fresh.mov"
    fresh.write_bytes(b"x")
    with client(tmp_path):
        assert not old.exists() and fresh.exists()

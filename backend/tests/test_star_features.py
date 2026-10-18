"""Unit tests for all 14 star-task modules.
No video files required — synthetic data only.
"""
import base64
import hashlib
import hmac
import json
import tempfile
import time
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# ★14 ml/risk.py
# ---------------------------------------------------------------------------
class TestRisk:
    def test_known_high_types(self):
        from ml.risk import add_risk, RISK_MAP
        for tid in ("unauthorized_access", "safe_left_open", "cash_unattended",
                    "collector_handover", "camera_tamper"):
            assert RISK_MAP[tid] == "high"

    def test_known_medium_types(self):
        from ml.risk import RISK_MAP
        assert RISK_MAP["workstation_unlocked"] == "medium"

    def test_known_low_types(self):
        from ml.risk import RISK_MAP
        assert RISK_MAP["personal_items"] == "low"

    def test_add_risk_mutates_violations(self):
        from ml.risk import add_risk
        result = {"violations": [
            {"type_id": "cash_unattended"},
            {"type_id": "personal_items"},
            {"type_id": "unknown_type"},
        ]}
        add_risk(result)
        assert result["violations"][0]["risk_level"] == "high"
        assert result["violations"][1]["risk_level"] == "low"
        assert result["violations"][2]["risk_level"] == "medium"  # fallback

    def test_empty_violations(self):
        from ml.risk import add_risk
        result = {"violations": []}
        add_risk(result)  # should not raise

    def test_missing_type_id(self):
        from ml.risk import add_risk
        result = {"violations": [{}]}
        add_risk(result)
        assert result["violations"][0]["risk_level"] == "medium"


# ---------------------------------------------------------------------------
# ★16 ml/quality.py
# ---------------------------------------------------------------------------
class TestQuality:
    def _make_video(self, tmp_path, luma=128, frozen=False):
        """Write a tiny synthetic MP4 using OpenCV."""
        import cv2
        path = str(tmp_path / "test.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        w = cv2.VideoWriter(path, fourcc, 10.0, (320, 240))
        rng = np.random.default_rng(42)
        base = np.full((240, 320, 3), luma, dtype=np.uint8)
        for i in range(30):
            frame = base if frozen else (base + rng.integers(-10, 10, base.shape, dtype=np.int16)).clip(0, 255).astype(np.uint8)
            w.write(frame)
        w.release()
        return path

    def test_good_video_is_ok(self, tmp_path):
        from ml.quality import check
        path = self._make_video(tmp_path, luma=120)
        r = check(path)
        assert r.ok
        assert not any(i.code == "dark" for i in r.issues)

    def test_dark_video_flagged(self, tmp_path):
        from ml.quality import check
        path = self._make_video(tmp_path, luma=5)
        r = check(path)
        assert not r.ok
        assert any(i.code == "dark" for i in r.issues)

    def test_frozen_video_flagged(self, tmp_path):
        from ml.quality import check
        path = self._make_video(tmp_path, frozen=True, luma=120)
        r = check(path)
        assert any(i.code == "frozen" for i in r.issues)

    def test_report_to_dict(self, tmp_path):
        from ml.quality import check
        path = self._make_video(tmp_path, luma=120)
        d = check(path).to_dict()
        assert "ok" in d and "issues" in d and "notes" in d
        assert isinstance(d["issues"], list)


# ---------------------------------------------------------------------------
# ★10 ml/tamper.py
# ---------------------------------------------------------------------------
class TestTamper:
    def _stable_frames(self, n=20):
        """Frames that look like a real scene: textured background (std > 30) + tiny jitter."""
        rng = np.random.default_rng(42)
        # Build a textured base (desk scene: top half dark, bottom half light, objects)
        base = rng.integers(60, 180, (240, 320, 3), dtype=np.uint8)
        # Add some structure so std_y >> COVERED_UNIFORM_THRESHOLD (12)
        base[:120, :, :] = rng.integers(40, 100, (120, 320, 3), dtype=np.uint8)
        base[120:, :, :] = rng.integers(100, 200, (120, 320, 3), dtype=np.uint8)
        frames = []
        for _ in range(n):
            jitter = rng.integers(-4, 5, base.shape, dtype=np.int16)
            f = np.clip(base.astype(np.int16) + jitter, 0, 255).astype(np.uint8)
            frames.append(f)
        return frames

    def test_normal_video_no_tamper(self):
        from ml.tamper import detect_tamper
        times = [i * 0.5 for i in range(20)]
        frames = self._stable_frames(20)
        # Verify our synthetic scene is non-trivial (std > threshold)
        import cv2
        gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        assert float(gray.std()) > 15, "test fixture too uniform"
        events = detect_tamper(times, frames, ref_frame=frames[0])
        assert events == [], f"false tamper events: {events}"

    def test_black_frames_detected(self):
        from ml.tamper import detect_tamper, KIND_BLACK
        # Start with 4 normal frames (so we have a valid ref), then all black
        times = [i * 0.5 for i in range(20)]
        normal = self._stable_frames(4)
        black = [np.zeros((240, 320, 3), np.uint8)] * 16
        events = detect_tamper(times, normal + black, ref_frame=normal[0])
        assert any(e.kind == KIND_BLACK for e in events)

    def test_uniform_covered_frames(self):
        from ml.tamper import detect_tamper, KIND_COVER
        # Start with 4 normal frames, then uniform grey (covered)
        times = [i * 0.5 for i in range(20)]
        normal = self._stable_frames(4)
        covered = [np.full((240, 320, 3), 100, np.uint8)] * 16
        events = detect_tamper(times, normal + covered, ref_frame=normal[0])
        assert any(e.kind == KIND_COVER for e in events)

    def test_empty_input_no_crash(self):
        from ml.tamper import detect_tamper
        assert detect_tamper([], []) == []


# ---------------------------------------------------------------------------
# ★13 ml/privacy.py
# ---------------------------------------------------------------------------
class TestPrivacy:
    def test_redact_with_box(self):
        from ml.privacy import redact, pixelate
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        laptop_box = [100.0, 50.0, 400.0, 300.0]
        out = redact(frame, laptop_box)
        assert out.shape == frame.shape
        assert not np.array_equal(frame, out)  # something was changed

    def test_redact_no_box(self):
        from ml.privacy import redact
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        out = redact(frame, None)
        assert np.array_equal(frame, out)  # unchanged

    def test_pixelate_region(self):
        from ml.privacy import pixelate
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        frame[20:80, 20:80] = 200
        result = pixelate(frame.copy(), (20, 20, 80, 80))
        assert result.shape == frame.shape

    def test_original_not_mutated(self):
        from ml.privacy import redact
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        orig = frame.copy()
        redact(frame, [10.0, 10.0, 90.0, 90.0])
        assert np.array_equal(frame, orig)


# ---------------------------------------------------------------------------
# ★18 ml/timeline.py
# ---------------------------------------------------------------------------
class TestTimeline:
    def _ctx(self, n=10):
        # Build a minimal Context-like object without importing ml.detectors
        # (which transitively imports torch via workplace -> zeroshot)
        from dataclasses import dataclass, field as dc_field
        from ml.video import VideoInfo

        @dataclass
        class _StubCtx:
            info: object
            frames: list
            extras: dict = dc_field(default_factory=dict)

        info = VideoInfo(path="fake.mov", fps=2.0, n_frames=n * 2, width=640, height=480)
        frames = [(i * 0.5, np.zeros((480, 640, 3), np.uint8)) for i in range(n)]
        ctx = _StubCtx(info=info, frames=frames)
        ctx.extras["times"] = [i * 0.5 for i in range(n)]
        ctx.extras["people"] = [[]] * n
        ctx.extras["objects"] = [[]] * n
        ctx.extras["laptop"] = None
        return ctx

    def test_build_returns_list(self):
        from ml.timeline import build
        ctx = self._ctx()
        tl = build(ctx, [])
        assert isinstance(tl, list) and len(tl) == 10

    def test_frame_keys(self):
        from ml.timeline import build
        ctx = self._ctx()
        tl = build(ctx, [])
        assert all({"t", "people", "laptop", "cash", "violations"} <= set(f) for f in tl)

    def test_violation_active_at_timecode(self):
        from ml.timeline import build
        ctx = self._ctx()
        violations = [{"type_id": "cash_unattended", "timecode_sec": 2.0}]
        tl = build(ctx, violations)
        near = [f for f in tl if abs(f["t"] - 2.0) <= 4.0]
        assert any(f["violations"] for f in near)


# ---------------------------------------------------------------------------
# ★9 ml/trajectory.py
# ---------------------------------------------------------------------------
class TestTrajectory:
    def _people(self, n=20):
        """Simulate a person walking across the frame."""
        people = []
        for i in range(n):
            x = 50 + i * 15.0
            box = [x, 100.0, x + 60, 300.0]
            people.append([box])
        return people

    def test_build_map_returns_b64(self):
        from ml.trajectory import build_map
        frame = np.zeros((480, 640, 3), np.uint8)
        times = [i * 0.5 for i in range(20)]
        people = self._people(20)
        b64 = build_map(frame, times, people)
        assert b64 is not None
        raw = base64.b64decode(b64)
        assert raw[:2] == b"\xff\xd8"  # JPEG magic

    def test_empty_people_returns_none(self):
        from ml.trajectory import build_map
        frame = np.zeros((480, 640, 3), np.uint8)
        assert build_map(frame, [], []) is None

    def test_too_few_detections_returns_none(self):
        from ml.trajectory import build_map
        frame = np.zeros((480, 640, 3), np.uint8)
        times = [0.0, 0.5]
        people = [[[10, 10, 70, 200]], [[10, 10, 70, 200]]]
        # Only 2 points per track — below min of 3
        result = build_map(frame, times, people)
        assert result is None


# ---------------------------------------------------------------------------
# ★12 backend/app/audit.py
# ---------------------------------------------------------------------------
class TestAudit:
    def test_seal_and_verify(self, tmp_path):
        from backend.app.audit import AuditLog
        al = AuditLog(tmp_path / "audit.db", "secret")
        result = {"verdict": "violation", "violations": [{"type": "test"}]}
        digest = al.seal("job1", result)
        assert len(digest) == 64  # sha256 hex
        ok, stored, ts = al.verify("job1", result)
        assert ok and stored == digest and ts is not None
        al.close()

    def test_tampered_result_fails(self, tmp_path):
        from backend.app.audit import AuditLog
        al = AuditLog(tmp_path / "audit.db", "secret")
        result = {"verdict": "violation", "violations": []}
        al.seal("job2", result)
        tampered = {"verdict": "no_violation", "violations": []}
        ok, _, _ = al.verify("job2", tampered)
        assert not ok
        al.close()

    def test_missing_job_returns_false(self, tmp_path):
        from backend.app.audit import AuditLog
        al = AuditLog(tmp_path / "audit.db", "secret")
        ok, digest, ts = al.verify("nonexistent", {})
        assert not ok and digest is None
        al.close()

    def test_attach_seals_on_finish(self, tmp_path):
        from backend.app.audit import AuditLog
        from backend.app.store import Store

        store = Store(tmp_path / "jobs.db")
        al = AuditLog(tmp_path / "audit.db", "secret")
        al.attach(store)

        job_id = store.new_id()
        store.create(job_id, "ui", str(tmp_path / "fake.mov"), "fake.mov")
        store.claim_next()
        result = {"verdict": "no_violation", "violations": []}
        store.finish(job_id, result)

        ok, _, _ = al.verify(job_id, result)
        assert ok
        store.close()
        al.close()

    def test_router_verify_endpoint(self, tmp_path):
        from fastapi.testclient import TestClient
        from backend.app.api import create_app
        from backend.app.config import Settings

        s = Settings(api_key="key", analyzer="demo", job_timeout_sec=60,
                     load_timeout_sec=120, strict_schema=False,
                     storage_dir=tmp_path, frontend_dir=tmp_path / "no-fe",
                     max_upload_mb=300, ui_uploads_per_min=100, upload_ttl_hours=24)
        with TestClient(create_app(s)) as c:
            # 404 for unknown job
            r = c.get("/ui/api/jobs/deadbeef/audit")
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# ★11 backend/app/clips.py
# ---------------------------------------------------------------------------
class TestClips:
    def test_router_registered(self, tmp_path):
        from fastapi.testclient import TestClient
        from backend.app.api import create_app
        from backend.app.config import Settings

        s = Settings(api_key="key", analyzer="demo", job_timeout_sec=60,
                     load_timeout_sec=120, strict_schema=False,
                     storage_dir=tmp_path, frontend_dir=tmp_path / "no-fe",
                     max_upload_mb=300, ui_uploads_per_min=100, upload_ttl_hours=24)
        with TestClient(create_app(s)) as c:
            r = c.get("/ui/api/jobs/nope/clip?t=5")
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# ★20 tools/offline_check.py
# ---------------------------------------------------------------------------
class TestOfflineCheck:
    def test_module_importable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "offline_check",
            Path(__file__).resolve().parents[2] / "tools" / "offline_check.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.run)

    def test_missing_file_exits_2(self):
        import subprocess, sys
        r = subprocess.run(
            [sys.executable, "tools/offline_check.py", "nonexistent.mov"],
            capture_output=True, cwd=Path(__file__).resolve().parents[2])
        assert r.returncode == 2


# ---------------------------------------------------------------------------
# ★19 / ★17 frontend format.js — normalizeResult passes new fields
# ---------------------------------------------------------------------------
class TestFormatJsFields:
    """Run format.js under Node.js and verify the new fields survive normalizeResult."""

    def _run_node(self, script: str) -> dict:
        import subprocess, sys
        r = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                           cwd=Path(__file__).resolve().parents[2])
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def test_risk_level_passed_through(self):
        script = """
const Fmt = require('./frontend/format.js');
const job = {
  verdict: 'violation',
  violations: [{
    type: 'Тест', type_id: 'cash_unattended', timecode_sec: 5,
    confidence: 0.8, description: 'desc', risk_level: 'high',
    evidence_frames: [{ timestamp_sec: 5, image_base64: '/9j/AA==' }]
  }],
  processing_sec: 12.3, video_duration_sec: 60.0
};
const r = Fmt.normalizeResult(job);
console.log(JSON.stringify({
  riskLevel: r.violations[0].riskLevel,
  videoDurationSec: r.videoDurationSec
}));
"""
        data = self._run_node(script)
        assert data["riskLevel"] == "high"
        assert data["videoDurationSec"] == 60.0

    def test_video_duration_sec_passed(self):
        script = """
const Fmt = require('./frontend/format.js');
const job = { verdict: 'no_violation', violations: [], video_duration_sec: 45.5, processing_sec: 8.2 };
const r = Fmt.normalizeResult(job);
console.log(JSON.stringify({ dur: r.videoDurationSec }));
"""
        data = self._run_node(script)
        assert data["dur"] == 45.5

    def test_timeline_passed(self):
        script = """
const Fmt = require('./frontend/format.js');
const job = { verdict: 'no_violation', violations: [],
              timeline: [{t:0,people:1,laptop:true,cash:false,violations:[]}] };
const r = Fmt.normalizeResult(job);
console.log(JSON.stringify({ tl: r.timeline }));
"""
        data = self._run_node(script)
        assert isinstance(data["tl"], list) and len(data["tl"]) == 1


# ---------------------------------------------------------------------------
# ★16 results.py — quality + video_duration_sec + risk_level flow
# ---------------------------------------------------------------------------
class TestResultsNormalize:
    def _norm(self, raw: dict) -> dict:
        import cv2
        from backend.app.results import normalize
        # Create a tiny real video so probe() works
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            path = f.name
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        w = cv2.VideoWriter(path, fourcc, 10.0, (320, 240))
        for _ in range(10):
            w.write(np.zeros((240, 320, 3), dtype=np.uint8))
        w.release()
        return normalize(raw, path)

    def test_video_duration_passed_through(self):
        raw = {"verdict": "no_violation", "violations": [], "video_duration_sec": 42.5}
        r = self._norm(raw)
        assert r.get("video_duration_sec") == 42.5

    def test_quality_passed_through(self):
        raw = {"verdict": "no_violation", "violations": [],
               "quality": {"ok": True, "issues": [], "notes": []}}
        r = self._norm(raw)
        assert r.get("quality") == {"ok": True, "issues": [], "notes": []}

    def test_risk_level_on_violation(self):
        import cv2
        from backend.app.results import normalize
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            path = f.name
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        w = cv2.VideoWriter(path, fourcc, 10.0, (320, 240))
        for _ in range(10):
            w.write(np.zeros((240, 320, 3), dtype=np.uint8))
        w.release()

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", frame)
        b64 = base64.b64encode(buf.tobytes()).decode()

        raw = {
            "verdict": "violation",
            "violations": [{
                "type": "Тест", "type_id": "cash_unattended", "timecode_sec": 1.0,
                "confidence": 0.9, "description": "test",
                "risk_level": "high",
                "evidence_frames": [{"timestamp_sec": 1.0, "image_base64": b64}]
            }]
        }
        r = normalize(raw, path)
        assert r["violations"][0].get("risk_level") == "high"

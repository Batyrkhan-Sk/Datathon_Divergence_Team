"""Run the jury flow against a running server and validate it against the case contract.

    python backend/check_api_contract.py --base-url http://localhost:8000 --key KEY \\
        --video data/raw/X-26.mov --video data/raw/X-29.mov [--concurrent 5]

Like the jury: multipart POST with field `file` (as `curl -F "file=@video.mov"`), then
GET the job every 2 s for at most 5 minutes. Standard library only. Exit code 1 on FAIL.
"""
import argparse
import base64
import binascii
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

LIMIT_SEC = 300
POLL_SEC = 2.0
STATUSES = {"processing", "done", "failed"}
VERDICTS = {"violation", "no_violation"}

Check = tuple[bool, str, str]   # (ok, name, detail)


def request(method: str, url: str, key: str | None = None, body: bytes | None = None,
            content_type: str | None = None, timeout: float = 120) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=body, method=method)
    if key is not None:
        req.add_header("X-API-Key", key)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        try:
            status, raw = e.code, e.read()
        except OSError as err:          # server answered, then dropped the connection
            return e.code, f"(body unreadable: {err})"
    except OSError as e:                # refused, reset, timed out
        return 0, f"connection error: {e}"
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def multipart(path: Path, field: str = "file") -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\";"
            f" filename=\"{path.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n")
    body = head.encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _jpeg(b64) -> str | None:
    """None if `b64` is a raw base64 JPEG, else the reason it is not."""
    if not isinstance(b64, str) or not b64:
        return "not a non-empty string"
    if b64.startswith("data:"):
        return "has a data: URI prefix"
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return "not valid base64"
    return None if raw[:3] == b"\xff\xd8\xff" else "decoded bytes are not a JPEG"


def validate_result(body, job_id: str | None = None) -> list[Check]:
    """Checks a final GET /api/v1/jobs/{id} body against the documented contract."""
    if not isinstance(body, dict):
        return [(False, "response is a JSON object", repr(body)[:200])]
    out: list[Check] = []
    add = lambda ok, name, detail="": out.append((bool(ok), name, detail))  # noqa: E731
    add(isinstance(body.get("job_id"), str) and (job_id is None or body["job_id"] == job_id),
        "job_id echoed", repr(body.get("job_id")))
    add(body.get("status") in STATUSES, "status in {processing, done, failed}",
        repr(body.get("status")))
    add(body.get("status") == "done", "status is done", body.get("error", ""))
    if body.get("status") != "done":
        return out
    verdict, vs = body.get("verdict"), body.get("violations")
    add(verdict in VERDICTS, "verdict in {violation, no_violation}", repr(verdict))
    add(isinstance(vs, list), "violations is a list", type(vs).__name__)
    if not isinstance(vs, list):
        return out
    add((verdict == "no_violation") == (len(vs) == 0), "violations empty iff no_violation",
        f"verdict={verdict}, {len(vs)} violation(s)")
    for i, v in enumerate(vs):
        p = f"violations[{i}]"
        if not isinstance(v, dict):
            add(False, f"{p} is an object")
            continue
        add(isinstance(v.get("type"), str) and v["type"].strip(), f"{p}.type is a string",
            repr(v.get("type"))[:80])
        add(_is_num(v.get("timecode_sec")) and v["timecode_sec"] >= 0,
            f"{p}.timecode_sec is a number >= 0", repr(v.get("timecode_sec")))
        add(isinstance(v.get("description"), str) and v["description"].strip(),
            f"{p}.description is a string", repr(v.get("description"))[:80])
        frames = v.get("evidence_frames")
        n = len(frames) if isinstance(frames, list) else -1
        add(1 <= n <= 3, f"{p}.evidence_frames has 1-3 frames", f"{n}")
        for j, f in enumerate(frames if isinstance(frames, list) else []):
            q = f"{p}.evidence_frames[{j}]"
            ok = isinstance(f, dict) and _is_num(f.get("timestamp_sec"))
            add(ok, f"{q}.timestamp_sec is a number",
                repr(f.get("timestamp_sec")) if isinstance(f, dict) else "")
            why = _jpeg(f.get("image_base64")) if isinstance(f, dict) else "not an object"
            add(why is None, f"{q}.image_base64 is base64 JPEG", why or "")
    return out


def check_auth(base: str, key: str, video: Path) -> list[Check]:
    body, ctype = multipart(video)
    out: list[Check] = []
    for label, k in (("without key", None), ("with a wrong key", key + "-wrong")):
        st, _ = request("POST", f"{base}/api/v1/analyze", k, body, ctype)
        out.append((400 <= st < 500, f"POST /analyze {label} is rejected", f"HTTP {st}"))
    st, _ = request("GET", f"{base}/api/v1/jobs/00000000", None)
    out.append((400 <= st < 500, "GET /jobs without key is rejected", f"HTTP {st}"))
    st, _ = request("GET", f"{base}/api/v1/jobs/does-not-exist", key)
    out.append((st == 404, "GET unknown job is 404", f"HTTP {st}"))
    return out


def run_flow(base: str, key: str, video: Path) -> tuple[list[Check], float]:
    """POST the video, poll until done/failed or 5 min; returns checks and seconds."""
    body, ctype = multipart(video)
    t0 = time.time()
    st, resp = request("POST", f"{base}/api/v1/analyze", key, body, ctype)
    job_id = resp.get("job_id") if isinstance(resp, dict) else None
    out: list[Check] = [
        (st == 200, "POST /analyze with key -> 200", f"HTTP {st}"),
        (isinstance(job_id, str) and bool(job_id), "response has job_id",
         repr(resp)[:200] if not job_id else job_id),
    ]
    if not job_id:
        return out, time.time() - t0
    seen, last = set(), None
    while time.time() - t0 < LIMIT_SEC:
        st, last = request("GET", f"{base}/api/v1/jobs/{job_id}", key, timeout=30)
        status = last.get("status") if isinstance(last, dict) else None
        seen.add(status)
        if st != 200 or status in ("done", "failed"):
            break
        time.sleep(POLL_SEC)
    elapsed = time.time() - t0
    out.append((st == 200, "GET /jobs/{id} -> 200", f"HTTP {st}"))
    out.append((seen <= STATUSES, "every polled status is valid", ", ".join(map(str, seen))))
    out += validate_result(last, job_id)
    out.append((elapsed < LIMIT_SEC, "finished within 5 minutes", f"{elapsed:.1f} s"))
    return out, elapsed


def _print(title: str, checks: list[Check]) -> int:
    print(f"\n== {title}")
    for ok, name, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return sum(not ok for ok, _, _ in checks)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--video", action="append", required=True, type=Path,
                    help="repeat for several videos")
    ap.add_argument("--concurrent", type=int, default=0,
                    help="also submit N videos at once (cycling --video) and time them")
    a = ap.parse_args()
    base = a.base_url.rstrip("/")

    failed = _print("auth and errors", check_auth(base, a.key, a.video[0]))
    for v in a.video:
        checks, sec = run_flow(base, a.key, v)
        failed += _print(f"{v.name} ({sec:.1f} s)", checks)

    if a.concurrent:
        results: dict[int, tuple[list[Check], float]] = {}
        vids = [a.video[i % len(a.video)] for i in range(a.concurrent)]
        t0 = time.time()
        threads = [threading.Thread(target=lambda i=i, v=v: results.__setitem__(
            i, run_flow(base, a.key, v))) for i, v in enumerate(vids)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.time() - t0
        for i, v in enumerate(vids):
            checks, sec = results[i]
            failed += _print(f"concurrent #{i + 1}: {v.name} ({sec:.1f} s)", checks)
        times = sorted(results[i][1] for i in results)
        print(f"\n== concurrency: {a.concurrent} videos, wall {wall:.1f} s, per job"
              f" min {times[0]:.1f} / max {times[-1]:.1f} s (limit {LIMIT_SEC} s)")

    print(f"\nRESULT: {'PASS' if not failed else f'FAIL ({failed} failed check(s))'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

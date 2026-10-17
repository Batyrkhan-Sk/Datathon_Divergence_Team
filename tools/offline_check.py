"""
Offline check — ensures the ML pipeline never makes outbound network calls
during analysis. Run before submission:

    python tools/offline_check.py data/raw/X-26.mov

Exit 0 = no network calls detected.
Exit 1 = at least one outbound call was made (fail).
"""
import socket
import sys
import threading
import traceback
from pathlib import Path
from unittest.mock import patch

CALLS: list[str] = []
_lock = threading.Lock()


def _intercept(original):
    def patched(*args, **kwargs):
        with _lock:
            host = args[0] if args else kwargs.get("address", ("?", 0))[0]
            caller = "".join(traceback.format_stack()[:-1][-4:]).strip().replace("\n", " | ")
            CALLS.append(f"{host}  —  {caller}")
        raise OSError("Network call blocked by offline_check.py")
    return patched


def run(video_path: str) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ml.pipeline as pipeline  # noqa: E402 — imported after sys.path patch

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_create_connection = socket.create_connection

    with (
        patch.object(socket.socket, "connect", _intercept(orig_connect)),
        patch.object(socket.socket, "connect_ex", _intercept(orig_connect_ex)),
        patch("socket.create_connection", _intercept(orig_create_connection)),
    ):
        try:
            pipeline.analyze(video_path)
        except Exception as exc:
            print(f"[offline_check] pipeline raised: {exc}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/offline_check.py <video>", file=sys.stderr)
        sys.exit(2)

    video = sys.argv[1]
    if not Path(video).is_file():
        print(f"File not found: {video}", file=sys.stderr)
        sys.exit(2)

    print(f"[offline_check] analysing {video} with network blocked…")
    run(video)

    if CALLS:
        print(f"\n[offline_check] FAIL — {len(CALLS)} outbound call(s) detected:")
        for c in CALLS:
            print(f"  {c}")
        sys.exit(1)
    else:
        print("[offline_check] OK — no network calls detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()

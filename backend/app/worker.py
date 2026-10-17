"""One persistent analysis process (one GPU) fed by a supervisor thread.

The worker loads the analyzer once and runs jobs one at a time. The supervisor claims
queued jobs from the store, forwards progress, and enforces the per-job timeout: on
timeout or crash the job is marked failed and the worker is killed and restarted.
"""
import logging
import multiprocessing as mp
import os
import queue
import threading
import time

from .store import Store

log = logging.getLogger("backend.worker")
_ctx = mp.get_context("spawn")
POLL_SEC = 0.25


def _exit_with_parent() -> None:
    # If the server is killed hard, don't stay alive holding the GPU.
    parent = mp.parent_process()
    while parent is not None and parent.is_alive():
        time.sleep(1.0)
    os._exit(0)


def worker_main(spec: str, tasks, events) -> None:
    """Child process entry point."""
    threading.Thread(target=_exit_with_parent, daemon=True).start()
    try:
        from .analyzers import load
        from .results import normalize
        analyze = load(spec)
    except BaseException as e:  # noqa: BLE001 - report anything, incl. import errors
        events.put(("load_error", None, f"{type(e).__name__}: {e}"))
        return
    events.put(("ready", None, None))
    while (task := tasks.get()) is not None:
        job_id, path = task
        last = [-1.0]

        def progress(p: float, job_id=job_id) -> None:
            p = float(p)
            if p - last[0] >= 0.01 or p >= 1.0:
                last[0] = p
                events.put(("progress", job_id, p))

        try:
            events.put(("done", job_id, normalize(analyze(path, progress), path)))
        except Exception as e:  # noqa: BLE001
            events.put(("error", job_id, f"{type(e).__name__}: {e}"))


class Supervisor:
    def __init__(self, store: Store, spec: str, job_timeout: float, load_timeout: float):
        self.store, self.spec = store, spec
        self.job_timeout, self.load_timeout = job_timeout, load_timeout
        self.state = "stopped"          # loading | alive | restarting | stopped
        self._proc = None
        self._tasks = self._events = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="supervisor", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self._kill(graceful=True)
        self.state = "stopped"

    # -- worker process ------------------------------------------------------------
    def _spawn(self) -> str | None:
        """Start the worker and wait until it has loaded the analyzer; error or None."""
        self.state = "loading"
        self._tasks, self._events = _ctx.Queue(), _ctx.Queue()
        self._proc = _ctx.Process(target=worker_main, name="analysis-worker", daemon=True,
                                  args=(self.spec, self._tasks, self._events))
        self._proc.start()
        deadline = time.time() + self.load_timeout
        while not self._stop.is_set():
            try:
                kind, _, payload = self._events.get(timeout=POLL_SEC)
            except queue.Empty:
                if not self._proc.is_alive():
                    return f"worker exited while loading (code {self._proc.exitcode})"
                if time.time() > deadline:
                    return f"analyzer did not load within {self.load_timeout:.0f} s"
                continue
            if kind == "ready":
                self.state = "alive"
                log.info("worker ready (analyzer=%s, pid=%s)", self.spec, self._proc.pid)
                return None
            if kind == "load_error":
                return f"analyzer failed to load: {payload}"
        return "stopping"

    def _kill(self, graceful: bool = False) -> None:
        if self._proc is None:
            return
        if graceful and self._proc.is_alive():
            try:
                self._tasks.put(None)
                self._proc.join(timeout=3)
            except (OSError, ValueError):
                pass
        if self._proc.is_alive():
            self._proc.kill()
        self._proc.join(timeout=5)
        self._proc = None

    def _restart(self, why: str) -> None:
        log.warning("restarting worker: %s", why)
        self.state = "restarting"
        self._kill()

    # -- main loop -----------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            if self._proc is None or not self._proc.is_alive():
                err = self._spawn()
                if err == "stopping":
                    return
                if err:
                    # A broken analyzer must not leave jobs processing forever.
                    log.error(err)
                    self._kill()
                    self.state = "restarting"
                    if job := self.store.claim_next():
                        self.store.fail(job.id, err)
                    self._stop.wait(2.0)
                    continue
            job = self.store.claim_next()
            if job is None:
                self._stop.wait(POLL_SEC)
                continue
            self._process(job)

    def _process(self, job) -> None:
        log.info("job %s started (attempt %d)", job.id, job.attempts)
        self._tasks.put((job.id, job.video_path))
        deadline = time.time() + self.job_timeout
        while True:
            try:
                kind, job_id, payload = self._events.get(timeout=POLL_SEC)
            except queue.Empty:
                if self._stop.is_set():
                    return  # left 'running'; recover() re-queues it on the next start
                if time.time() > deadline:
                    self.store.fail(job.id, f"timeout: processing exceeded "
                                            f"{self.job_timeout:.0f} s")
                    self._restart(f"job {job.id} timed out")
                    return
                if not self._proc.is_alive():
                    self.store.fail(job.id, f"worker crashed (exit code {self._proc.exitcode})")
                    self._restart(f"worker crashed on job {job.id}")
                    return
                continue
            if job_id != job.id:
                continue
            if kind == "progress":
                self.store.set_progress(job.id, payload)
            elif kind == "done":
                self.store.finish(job.id, payload)
                log.info("job %s done: %s, %d violation(s)", job.id, payload["verdict"],
                         len(payload["violations"]))
                return
            elif kind == "error":
                self.store.fail(job.id, payload)
                log.warning("job %s failed: %s", job.id, payload)
                return

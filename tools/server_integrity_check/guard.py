"""Defense in depth for synthetic tests, not an OS security sandbox."""
import importlib.abc
import os
from pathlib import Path
import socket
import sys


class ModelBlocked(ImportError):
    pass


class BlockModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("torch", "transformers", "huggingface_hub", "bitsandbytes", "uvicorn",
                   "ml.pipeline", "ml.perception")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise ModelBlocked("model_and_server_imports_disabled_for_synthetic_check")


def install():
    root = Path(os.environ["FORTE_CHECK_ROOT"]).resolve()
    sys.meta_path.insert(0, BlockModels())

    def within(path):
        if isinstance(path, int):
            return True  # Existing stdout/stderr/capture descriptors.
        path = Path(os.fsdecode(path)).resolve()
        return path == root or path.is_relative_to(root) or str(path) == os.devnull

    def audit(event, args):
        if event in ("socket.bind", "socket.connect"):
            if args[0].family in (socket.AF_INET, socket.AF_INET6):
                raise PermissionError("network_disabled_for_synthetic_check")
        elif event == "socket.getaddrinfo":
            raise PermissionError("dns_disabled_for_synthetic_check")
        elif event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(m in mode for m in "wax+")) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if writing and not within(path):
                raise PermissionError("write_outside_isolated_directory_blocked")
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.chmod") and not within(args[0]):
            raise PermissionError("mutation_outside_isolated_directory_blocked")
        elif event == "os.rename" and not all(within(p) for p in args[:2]):
            raise PermissionError("rename_outside_isolated_directory_blocked")

    sys.addaudithook(audit)


def self_check():
    blocked = {}
    try:
        __import__("torch")
    except ModelBlocked:
        blocked["model_import_blocked"] = True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        for name, action in (("tcp_bind_blocked", lambda: sock.bind(("127.0.0.1", 0))),
                             ("tcp_connect_blocked", lambda: sock.connect(("127.0.0.1", 9)))):
            try:
                action()
            except PermissionError:
                blocked[name] = True
    if len(blocked) != 3:
        raise RuntimeError("test_guard_self_check_failed")
    return blocked

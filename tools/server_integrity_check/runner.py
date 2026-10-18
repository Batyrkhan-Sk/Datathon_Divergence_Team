"""Self-contained zipapp entry point; source project is read-only throughout."""
import argparse
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


class CheckStopped(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)


def snapshot(root, names):
    contents = {}
    for name in names:
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise CheckStopped("source_file_missing_or_symlink")
        contents[name] = path.read_bytes()
    return contents


def patch_definitions(source, replacement, names, additions, import_module, import_line):
    """Replace named functions only; retain surrounding server code verbatim."""
    tree, incoming = ast.parse(source), ast.parse(replacement)
    lines, candidate = source.splitlines(keepends=True), replacement.splitlines(keepends=True)
    definitions = {n.name: n for n in incoming.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    existing = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    if not set(names).issubset(existing) or set(additions) & set(existing):
        raise CheckStopped("unexpected_source_definitions")
    edits = []
    for name in names:
        old, new = existing[name], definitions[name]
        if old.decorator_list or new.decorator_list:
            raise CheckStopped("unexpected_decorated_function")
        edits.append((old.lineno - 1, old.end_lineno,
                      "".join(candidate[new.lineno - 1:new.end_lineno])))
    if import_module:
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
                   and n.module == import_module]
        if len(imports) != 1:
            raise CheckStopped("unexpected_video_import")
        node = imports[0]
        edits.append((node.lineno - 1, node.end_lineno, import_line + "\n"))
    for begin, end, text in sorted(edits, reverse=True):
        lines[begin:end] = [text]
    result = "".join(lines)
    for name in additions:
        node = definitions[name]
        result += "\n\n" + "".join(candidate[node.lineno - 1:node.end_lineno])
    # No future imports are present in the accepted snapshots.
    if any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body):
        raise CheckStopped("unexpected_future_import")
    result = "import math\nfrom numbers import Real\n" + result
    ast.parse(result)
    return result


PATCHES = {
    "backend/app/results.py": {
        "names": ["as_jpeg_base64", "frame_at", "normalize"],
        "additions": ["InvalidResult", "EvidenceUnavailable", "_required_number"],
        "import_module": "ml.video",
        "import_line": "from ml.video import probe, read_frame_with_timestamp",
    },
    "ml/video.py": {"names": ["iter_frames", "read_frame_at"],
                     "additions": ["read_frame_with_timestamp"],
                     "import_module": None, "import_line": None},
    "ml/evidence.py": {"names": ["frames_for"], "additions": [],
                        "import_module": "video",
                        "import_line": "from .video import read_frame_with_timestamp"},
}


def execute(command, cwd, env, log, timeout):
    with log.open("xb") as stream:
        os.chmod(log, 0o600)
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            return result.returncode
        except subprocess.TimeoutExpired:
            raise CheckStopped("own_subprocess_timeout") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable, help="Python 3.12+ for a NEW isolated venv")
    parser.add_argument("--work-parent", type=Path, help="defaults to project parent; never inside project")
    args = parser.parse_args(argv)
    os.umask(0o077)
    root = args.project.resolve()
    report = {"status": "not_started", "source_writes_performed": False,
              "existing_processes_signalled": False, "public_site_contacted": False,
              "bank_media_or_notebooks_copied": False, "model_inference_run": False,
              "base_environment_modified": False, "full_api_latency_measured": False,
              "model_accuracy_improvement_claimed": False}
    work = None
    before = None
    phase = "preflight"
    started = time.monotonic()
    try:
        if not root.is_dir():
            raise CheckStopped("project_directory_missing")
        parent = (args.work_parent or root.parent).resolve()
        if parent == root or parent.is_relative_to(root) or not parent.is_dir():
            raise CheckStopped("work_parent_must_exist_outside_project")
        with zipfile.ZipFile(Path(sys.argv[0]).resolve()) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            payload = {n: archive.read(n) for n in manifest["payload_sha256"]}
            if any(sha(payload[n]) != checksum for n, checksum in manifest["payload_sha256"].items()):
                raise CheckStopped("package_checksum_mismatch")
        before = snapshot(root, manifest["source_files"])
        hashes = {n: sha(data) for n, data in before.items()}
        matches = [name for name, expected in manifest["accepted_snapshots"].items() if hashes == expected]
        if len(matches) != 1:
            report["source_match"] = {name: sum(hashes.get(n) == digest for n, digest in expected.items())
                                      for name, expected in manifest["accepted_snapshots"].items()}
            raise CheckStopped("source_changed_or_unrecognized_prepare_new_package")
        report["source_snapshot"] = matches[0]
        report["source_sha256"] = hashes
        # Only this new directory is writable by this workflow.
        work = Path(tempfile.mkdtemp(prefix="forte-integrity-check-", dir=parent))
        print(json.dumps({"phase": "isolated_directory_created", "path": str(work)}), flush=True)
        for folder in ("baseline", "candidate", "runtime", "tmp", "private_logs"):
            (work / folder).mkdir(mode=0o700)
        for name, content in before.items():
            write(work / "baseline" / name, content)
            write(work / "candidate" / name, content)
        changes = []
        for name, settings in PATCHES.items():
            old = before[name].decode("utf-8")
            new = patch_definitions(old, payload["patch/" + name].decode("utf-8"), **settings)
            (work / "candidate" / name).write_text(new, encoding="utf-8")
            changes.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                               fromfile="baseline/" + name, tofile="candidate/" + name))
        write(work / "candidate.patch", "".join(changes).encode())
        for name, content in payload.items():
            if name.startswith("add/"):
                write(work / "candidate" / name[4:], content)
            elif name.startswith("runtime/"):
                write(work / name, content)
        report["patched_files"] = list(PATCHES)
        report["other_copied_source_files_byte_identical"] = all(
            (work / "candidate" / n).read_bytes() == content for n, content in before.items() if n not in PATCHES)
        # No inherited API keys, model settings, Python paths or pip config.
        env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "SSL_CERT_FILE") if k in os.environ}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                   CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                   HF_HUB_DISABLE_TELEMETRY="1", PIP_CONFIG_FILE=os.devnull,
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   TMPDIR=str(work / "tmp"), TEMP=str(work / "tmp"), TMP=str(work / "tmp"),
                   FORTE_CHECK_ROOT=str(work))
        phase = "python_version"
        check = subprocess.run([args.python, "-I", "-B", "-c", "import sys; raise SystemExit(sys.version_info < (3,12))"],
                               cwd=work, env=env, capture_output=True, timeout=15)
        if check.returncode:
            raise CheckStopped("test_environment_requires_python_3_12_or_newer")
        phase = "venv_creation"
        print(json.dumps({"phase": phase}), flush=True)
        if execute([args.python, "-I", "-B", "-m", "venv", str(work / ".venv")], work, env,
                   work / "private_logs/venv.log", 120):
            raise CheckStopped("isolated_venv_creation_failed")
        python = work / ".venv/bin/python"
        phase = "install_test_dependencies_in_new_venv"
        print(json.dumps({"phase": phase, "model_packages": False}), flush=True)
        if execute([str(python), "-I", "-B", "-m", "pip", "install", "--require-virtualenv", "--no-cache-dir",
                    "--disable-pip-version-check", "--no-input", "--only-binary=:all:",
                    "--index-url", "https://pypi.org/simple", "-r", str(work / "runtime/requirements.lock")],
                   work, env, work / "private_logs/install.log", 600):
            raise CheckStopped("isolated_dependency_install_failed")
        report["new_venv_created"] = True
        for variant in ("baseline", "candidate"):
            phase = variant + "_synthetic_probe"
            print(json.dumps({"phase": phase}), flush=True)
            log = work / ("private_logs/" + variant + ".log")
            if execute([str(python), "-I", "-B", str(work / "runtime/probe.py"), str(work / variant)],
                       work / variant, env, log, 90):
                raise CheckStopped(variant + "_synthetic_probe_failed")
            report[variant + "_probe"] = json.loads(log.read_text().splitlines()[-1])
        phase = "candidate_tests"
        print(json.dumps({"phase": phase}), flush=True)
        exit_code = execute([str(python), "-I", "-B", str(work / "runtime/run_tests.py"),
                             str(work / "candidate"), str(work / "tests_summary.json")],
                            work / "candidate", env, work / "private_logs/tests.log", 180)
        report["tests"] = json.loads((work / "tests_summary.json").read_text())
        candidate = report["candidate_probe"]
        report["five_invalid_cases_rejected"] = all(candidate[n]["outcome"] == "rejected" for n in
            ("missing_result", "missing_verdict", "contradictory_result", "negative_timestamp", "evidence_read_failure"))
        report["valid_controls_preserved"] = all(candidate[n]["outcome"] == "accepted" for n in ("valid_negative", "valid_positive"))
        report["status"] = "passed" if (exit_code == 0 and report["tests"]["passed"] == manifest["expected_tests"]
            and report["tests"]["skipped"] == 0 and report["five_invalid_cases_rejected"]
            and report["valid_controls_preserved"]) else "failed"
    except CheckStopped as exc:
        report.update(status="stopped", reason=str(exc), phase=phase)
    except KeyboardInterrupt:
        report.update(status="interrupted", phase=phase)
    except Exception as exc:
        report.update(status="stopped", reason="unexpected_error", exception_class=type(exc).__name__, phase=phase)
    finally:
        if before is not None:
            try:
                report["original_files_still_identical"] = snapshot(root, list(before)) == before
            except Exception:
                report["original_files_still_identical"] = False
            if not report["original_files_still_identical"]:
                report["status"] = "source_changed_during_check"
        report["elapsed_sec"] = round(time.monotonic() - started, 3)
        if work is not None:
            write(work / "REPORT_SAFE.json", (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
            print(json.dumps({"report_path": str(work / "REPORT_SAFE.json")}), flush=True)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

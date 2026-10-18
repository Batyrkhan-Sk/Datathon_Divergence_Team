"""Build a code-only zipapp; expected server hashes come from a safe pasted report."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PATCH = ["backend/app/results.py", "ml/video.py", "ml/evidence.py"]
ADD = ["backend/__init__.py", "backend/tests/__init__.py", "backend/tests/conftest.py",
       "backend/tests/integrity_stubs.py", "backend/tests/test_result_integrity.py",
       "eval/__init__.py", "eval/quality_audit.py", "eval/quality_metrics.py",
       "eval/tests/__init__.py", "eval/tests/test_quality_audit.py"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-snapshot", type=Path, required=True)
    parser.add_argument("--server-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    text = args.server_report.read_text()
    report, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    server = report["code_sha256"]
    if not set(PATCH).issubset(server) or any(Path(n).is_absolute() or ".." in Path(n).parts for n in server):
        raise ValueError("unexpected_source_paths")
    main = {name: hashlib.sha256((args.main_snapshot / name).read_bytes()).hexdigest() for name in server}
    payload = {"patch/" + name: (ROOT / name).read_bytes() for name in PATCH}
    payload.update({"add/" + name: (ROOT / name).read_bytes() for name in ADD})
    payload.update({"runtime/" + name: (HERE / name).read_bytes() for name in
                    ("guard.py", "probe.py", "run_tests.py", "requirements.lock")})
    manifest = {"schema_version": 1, "source_files": sorted(server), "expected_tests": 86,
                "accepted_snapshots": {"server_report_2026_10_18": server, "main_286927f": main},
                "payload_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}
    with args.output.open("xb") as stream:
        os.chmod(args.output, 0o600)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("__main__.py", (HERE / "runner.py").read_bytes())
            archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            for name, data in sorted(payload.items()):
                archive.writestr(name, data)
    print(json.dumps({"package": str(args.output.resolve()), "bytes": args.output.stat().st_size,
                      "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "bank_data_or_model_weights_included": False}))


if __name__ == "__main__":
    main()

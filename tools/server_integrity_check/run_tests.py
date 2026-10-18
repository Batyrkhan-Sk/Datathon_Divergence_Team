"""Test entry point; multiprocessing children install the same guard."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard import install, self_check
install()
sys.path.insert(0, sys.argv[1])


def main():
    from importlib.metadata import distributions
    import pytest
    result = {"passed": 0, "failed": 0, "skipped": 0, "collection_errors": 0,
              "failed_test_names": [], "guard_checks": self_check()}

    class Summary:
        def pytest_runtest_logreport(self, report):
            if report.failed:
                result["failed"] += 1
                result["failed_test_names"].append(report.nodeid)
            elif report.skipped:
                result["skipped"] += 1
            elif report.when == "call" and report.passed:
                result["passed"] += 1

        def pytest_collectreport(self, report):
            if report.failed:
                result["collection_errors"] += 1

    started = time.monotonic()
    code = pytest.main(["backend/tests/test_result_integrity.py", "eval/tests/test_quality_audit.py",
                        "-q", "-p", "no:cacheprovider", "--basetemp",
                        str(Path(os.environ["FORTE_CHECK_ROOT"]) / "pytest_tmp")], plugins=[Summary()])
    result.update(exit_code=int(code), elapsed_sec=round(time.monotonic() - started, 3),
                  dependency_versions={d.metadata["Name"]: d.version for d in distributions()})
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2) + "\n")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())

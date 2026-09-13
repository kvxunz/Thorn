import copy
import importlib.util
import unittest
from pathlib import Path


def load_script(name):
    path = Path(__file__).resolve().parent.parent / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportGateTests(unittest.TestCase):
    def test_external_gate_rejects_drift_new_failures_and_missing_targets(self):
        check = load_script("check_external_report").check
        baseline = {"cases": 1, "source_sha256": "corpus", "manifest_sha256": "ids", "metric": "recall",
                    "checks": {"parse": {"passed": 1, "total": 1}, "backbone": {"passed": 0, "total": 1}},
                    "failures": [{"case": "one", "category": "backbone", "detail": "known"}]}
        check(baseline, copy.deepcopy(baseline))
        improved = copy.deepcopy(baseline)
        improved["failures"] = []
        improved["checks"]["backbone"]["passed"] = 1
        check(baseline, improved)
        for change in ("identity", "new", "missing"):
            candidate = copy.deepcopy(baseline)
            if change == "identity":
                candidate["manifest_sha256"] = "other"
            elif change == "new":
                candidate["failures"].append({"case": "one", "category": "parse", "detail": "new"})
            else:
                candidate["checks"]["backbone"]["total"] = 0
            with self.assertRaises(ValueError):
                check(baseline, candidate)

    def test_performance_comparison_rejects_environment_changes(self):
        compare = load_script("compare_parser_benchmarks").compare
        baseline = {"corpus_sha256": "corpus", "python": "3.11", "dependencies": {"model": "1"},
                    "repeats": 5, "launches": 3, "platform": "mac", "machine": "arm64",
                    "load_seconds": {"median": 2}, "first_parse_seconds": {"median": 0.1},
                    "peak_rss_bytes": {"median": 100}, "trials": [{"cases": []}]}
        self.assertTrue(all(row["change_percent"] == 0 for row in compare(baseline, copy.deepcopy(baseline))))
        different = copy.deepcopy(baseline)
        different["dependencies"]["model"] = "2"
        with self.assertRaises(ValueError):
            compare(baseline, different)


if __name__ == "__main__":
    unittest.main()

import argparse
import json
from pathlib import Path


def check(baseline, candidate):
    for key in ("cases", "source_sha256", "manifest_sha256", "metric"):
        if baseline[key] != candidate[key]:
            raise ValueError(f"external evaluation identity changed: {key}")
    expected = {key: value["total"] for key, value in baseline["checks"].items() if key != "alignment"}
    actual = {key: value["total"] for key, value in candidate["checks"].items() if key != "alignment"}
    if expected != actual or "execution" in candidate["checks"]:
        raise ValueError("external target counts changed or parser execution failed")
    if any(candidate["checks"][key]["passed"] < baseline["checks"][key]["passed"] for key in expected):
        raise ValueError("external target recall regressed")
    known = {json.dumps(failure, sort_keys=True) for failure in baseline["failures"]}
    added = [failure for failure in candidate["failures"] if json.dumps(failure, sort_keys=True) not in known]
    if added:
        raise ValueError(f"new external target failures: {json.dumps(added, ensure_ascii=False)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    check(json.loads(args.baseline.read_bytes()), json.loads(args.candidate.read_bytes()))
    print("No new external target failures; existing mismatches remain recorded in the baseline")

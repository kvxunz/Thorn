import argparse
import json
import statistics
from pathlib import Path


def compare(before, after):
    for key in ("corpus_sha256", "python", "dependencies", "repeats", "launches", "platform", "machine"):
        if before[key] != after[key]:
            raise ValueError(f"incomparable benchmarks: {key}")
    rows = []

    def append(name, previous, current):
        rows.append({"metric": name, "before": previous, "after": current,
                     "change_percent": (current / previous - 1) * 100 if previous else None})

    for key in ("load_seconds", "first_parse_seconds", "peak_rss_bytes"):
        append(key, before[key]["median"], after[key]["median"])
    for index, case in enumerate(before["trials"][0]["cases"]):
        for stage in case["seconds"]:
            values = []
            for report in (before, after):
                samples = []
                for trial in report["trials"]:
                    measured = trial["cases"][index]
                    if measured["id"] != case["id"]:
                        raise ValueError("case ordering differs")
                    samples.extend(measured["seconds"][stage]["samples"])
                values.append(statistics.median(samples))
            append(f"{case['id']}.{stage}_seconds", *values)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(args.before.read_bytes()), json.loads(args.after.read_bytes())), indent=2))

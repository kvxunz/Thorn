from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path


def summarize(values):
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("benchmark requires finite nonnegative samples")
    ordered = sorted(values)
    return {"samples": values, "median": statistics.median(values),
            "p95": ordered[math.ceil(len(ordered) * 0.95) - 1]}


def peak_rss_bytes(value, system):
    return int(value if system == "Darwin" else value * 1024)


def worker(root, cases, repeats):
    sys.path.insert(0, str(root))
    started = time.perf_counter()
    import server

    if Path(server.__file__).resolve().parent != root.resolve():
        raise ValueError("benchmark imported the wrong source tree")
    server.load()
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    first = server.analyze_text(cases[0]["text"])
    first_seconds = time.perf_counter() - started
    if not first.chunks:
        raise ValueError("empty first parse")
    measurements = []
    for case in cases:
        samples = {stage: [] for stage in ("inference", "evidence", "structure", "projection", "total")}
        for _ in range(repeats):
            from syntax_assembly import analyze_structure
            from teaching_projection import project_structure

            started = time.perf_counter()
            prepared, doc, offsets = server._prepare_document(case["text"])
            inferred = time.perf_counter()
            evidence = server.TeachingEvidence.from_doc(doc)
            relations = evidence.relations
            source = server.TokenSource(text=prepared.surface, token_offsets=offsets)
            evidenced = time.perf_counter()
            structure = analyze_structure(doc, relations)
            structured = time.perf_counter()
            chunks = project_structure(structure, doc, source, evidence)
            projected = time.perf_counter()
            if not chunks:
                raise ValueError(f"empty parse: {case['id']}")
            for stage, duration in {
                "inference": inferred - started, "evidence": evidenced - inferred,
                "structure": structured - evidenced, "projection": projected - structured,
                "total": projected - started,
            }.items():
                samples[stage].append(duration)
        measurements.append({"id": case["id"], "tokens": len(doc),
                             "seconds": {name: summarize(values) for name, values in samples.items()}})
    return {"load_seconds": load_seconds, "first_parse_seconds": first_seconds,
            "peak_rss_bytes": peak_rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, platform.system()),
            "cases": measurements}


def run(root, corpus, repeats, launches):
    if not (root / "server.py").is_file():
        raise ValueError("source root must contain server.py")
    raw = corpus.read_bytes()
    cases = json.loads(raw)["cases"]
    if repeats < 1 or launches < 1 or not cases:
        raise ValueError("positive repeats, launches and nonempty cases required")
    trials = []
    for _ in range(launches):
        started = time.perf_counter()
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", "--source-root", str(root),
             "--corpus", str(corpus), "--repeats", str(repeats)],
            capture_output=True, text=True, check=True, timeout=600,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        result = json.loads(process.stdout)
        result["process_wall_seconds"] = time.perf_counter() - started
        trials.append(result)
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.glob("*.py"))}
    lock = root / "server.py.lock"
    return {
        "schema_version": 1, "scope": "fresh Python processes; OS file cache not flushed; parser only, no UI, HTTP, translation or downloads",
        "platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version(),
        "dependencies": dict(sorted((distribution.metadata["Name"].lower(), distribution.version)
                                    for distribution in importlib.metadata.distributions())),
        "source_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,
        "corpus_sha256": hashlib.sha256(raw).hexdigest(), "repeats": repeats, "launches": launches,
        "load_seconds": summarize([trial["load_seconds"] for trial in trials]),
        "first_parse_seconds": summarize([trial["first_parse_seconds"] for trial in trials]),
        "peak_rss_bytes": summarize([trial["peak_rss_bytes"] for trial in trials]),
        "trials": trials,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--corpus", type=Path, default=Path(__file__).with_name("benchmark_cases.json"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--launches", type=int, default=3)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or args.launches < 1:
        parser.error("repeats and launches must be positive")
    root, corpus = args.source_root.resolve(), args.corpus.resolve()
    result = (worker(root, json.loads(corpus.read_bytes())["cases"], args.repeats) if args.worker
              else run(root, corpus, args.repeats, args.launches))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path


def evaluate(cases, analyze):
    if not cases:
        raise ValueError("relation evaluation requires nonempty cases")
    counts = defaultdict(lambda: {"passed": 0, "total": 0})
    failures = []

    def record(case_id, category, passed, detail):
        counts[category]["total"] += 1
        counts[category]["passed"] += int(passed)
        if not passed:
            failures.append({"case": case_id, "category": category, "detail": detail})

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.get("children") or [])

    for case in cases:
        try:
            analysis = analyze(case["text"])
            tokens = analysis.source_tokens

            def anchor(word, tokens=tokens):
                indices = [index for index, token in enumerate(tokens) if token == word]
                if len(indices) != 1:
                    raise ValueError(f"gold anchor must be unique: {word}")
                return indices[0]

            graph = analysis.evidence.relations
            record(case["id"], "parse", bool(analysis.chunks) and not graph.diagnostics, "empty tree or cyclic relations")
            roots = {frame.predicate for frame in graph.clauses if frame.parent is None}
            record(case["id"], "main_root", anchor(case["root"]) in roots, case["root"])
            edges = {(edge.kind, edge.head, edge.dependent) for edge in graph.edges}
            for category, kind, head, dependent in case["checks"]:
                record(case["id"], category, (kind, anchor(head), anchor(dependent)) in edges,
                       f"{kind}: {head} -> {dependent}")
            groups = {frozenset(group.members) for group in graph.coordinations}
            for group in case.get("groups", []):
                record(case["id"], "coordination_group",
                       frozenset(anchor(word) for word in group) in groups, group)
            for siblings in case.get("siblings", []):
                record(case["id"], "teaching_siblings", any(
                    set(siblings).issubset({child["text"] for child in node.get("children") or []})
                    for node in walk(analysis.chunks)
                ), siblings)
        except (ValueError, RuntimeError, TypeError, AttributeError, KeyError, IndexError, OSError) as error:
            record(case["id"], "execution", False, f"{type(error).__name__}: {error}")
    return {"cases": len(cases), "checks": dict(counts), "failures": failures}


def run(analyze):
    path = Path(__file__).with_name("relation_holdout.json")
    raw = path.read_bytes()
    dataset = json.loads(raw)
    result = evaluate(dataset["cases"], analyze)
    result["dataset_sha256"] = hashlib.sha256(raw).hexdigest()
    result["provenance"] = dataset["provenance"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failures"] else 1

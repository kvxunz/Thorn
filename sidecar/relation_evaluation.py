from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


def split_numeric_anchor(word, text, tokens, evidence):
    if not re.fullmatch(r"[0-9]+['’]s", word):
        return None
    if len(re.findall(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text)) != 1:
        return None
    matches = [index for index in range(len(tokens) - 1)
               if tokens[index] + tokens[index + 1] == word]
    if len(matches) != 1:
        return None
    index = matches[0]
    source = getattr(evidence, "tokens", ())
    if len(source) != len(tokens):
        return None
    number, suffix = source[index:index + 2]
    if (number.pos in ("NUM", "NOUN") and number.head != index + 1
            and suffix.head == index and suffix.dep in ("case", "poss", "quantmod")):
        return index
    return None


def evaluate(cases, analyze, *, strict_anchors=True, normalize_coordination=False):
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
            unmatched = set()

            def anchor(word, tokens=tokens, unmatched=unmatched, case_id=case["id"],
                       text=case["text"], evidence=analysis.evidence):
                indices = [index for index, token in enumerate(tokens) if token == word]
                if len(indices) != 1:
                    if not strict_anchors:
                        aligned = split_numeric_anchor(word, text, tokens, evidence)
                        if aligned is not None:
                            return aligned
                        if word not in unmatched:
                            record(case_id, "alignment", False, f"unmatched gold anchor: {word}")
                            unmatched.add(word)
                        return -1
                    raise ValueError(f"gold anchor must be unique: {word}")
                return indices[0]

            graph = analysis.evidence.relations
            record(case["id"], "parse", bool(analysis.chunks) and not graph.diagnostics, "empty tree or cyclic relations")
            roots = {frame.predicate for frame in graph.clauses if frame.parent is None}
            record(case["id"], "main_root", anchor(case["root"]) in roots, case["root"])
            edges = {(edge.kind, edge.head, edge.dependent) for edge in graph.edges}
            if normalize_coordination:
                edges.update(("coordinate", group.head, member)
                             for group in graph.coordinations for member in group.members
                             if member != group.head)
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

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from relation_evaluation import evaluate

UD_RELATIONS = {
    "nsubj": ("backbone", "subject"), "nsubj:pass": ("backbone", "subject"),
    "obj": ("backbone", "object"), "iobj": ("backbone", "indirect-object"),
    "ccomp": ("attachment", "content-clause"), "xcomp": ("attachment", "open-complement"),
    "acl:relcl": ("attachment", "relative-modifier"), "acl": ("attachment", "nominal-modifier"),
    "advcl": ("attachment", "clausal-modifier"), "amod": ("attachment", "nominal-modifier"),
    "conj": ("coordination", "coordinate"),
}


def convert(block):
    metadata = {}
    rows = {}
    for line in block.splitlines():
        if line.startswith("# ") and " = " in line:
            key, value = line[2:].split(" = ", 1)
            metadata[key] = value
        elif line and not line.startswith("#"):
            fields = line.split("\t")
            if len(fields) != 10:
                raise ValueError("invalid CoNLL-U row")
            if fields[0].isdigit():
                rows[int(fields[0])] = fields
    if not rows or not 8 <= len(rows) <= 60:
        return None
    if any(row[7] == "cop" for row in rows.values()):
        return None
    roots = [row for row in rows.values() if row[6] == "0"]
    if len(roots) != 1 or roots[0][3] != "VERB":
        return None
    frequencies = Counter(row[1] for row in rows.values())
    if frequencies[roots[0][1]] != 1:
        return None
    checks = []
    for row in rows.values():
        if row[7] not in UD_RELATIONS:
            continue
        head = rows[int(row[6])]
        if frequencies[row[1]] != 1 or frequencies[head[1]] != 1:
            continue
        category, kind = UD_RELATIONS[row[7]]
        checks.append([category, kind, head[1], row[1]])
    if not checks:
        return None
    return {"id": metadata["sent_id"], "text": metadata["text"], "root": roots[0][1], "checks": checks}


def select(raw, per_genre):
    if per_genre < 1:
        raise ValueError("positive per-genre sample size required")
    genres = defaultdict(list)
    for block in raw.decode().strip().split("\n\n"):
        case = convert(block)
        if case:
            genres[case["id"].split("-", 1)[0]].append(case)
    if set(genres) != {"answers", "email", "newsgroup", "reviews", "weblog"}:
        raise ValueError("expected all five EWT genres")
    selected = []
    for genre, cases in sorted(genres.items()):
        if len(cases) < per_genre:
            raise ValueError(f"insufficient cases for {genre}")
        selected.extend(sorted(cases, key=lambda case: hashlib.sha256(case["id"].encode()).hexdigest())[:per_genre])
    return selected


def load_cases(path, manifest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["source_sha256"]:
        raise ValueError("external corpus checksum mismatch")
    cases = select(raw, manifest["per_genre"])
    if [case["id"] for case in cases] != manifest["case_ids"]:
        raise ValueError("external selection drift")
    return cases


def evaluate_corpus(path, analyze, manifest_path=None):
    manifest_path = manifest_path or Path(__file__).with_name("external_eval_manifest.json")
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    cases = load_cases(path, manifest)
    result = evaluate(cases, analyze, strict_anchors=False, normalize_coordination=True)
    result.update(provenance=manifest["provenance"], source_sha256=manifest["source_sha256"],
                  source=manifest["source"], revision=manifest["revision"], license=manifest["license"],
                  manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
                  metric="recall of selected gold relation targets, not full dependency accuracy")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if "execution" in result["checks"] else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("external_eval_manifest.json"))
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    if args.freeze:
        raw = args.corpus.read_bytes()
        cases = select(raw, 20)
        print(json.dumps({
            "version": 1,
            "source": "https://github.com/UniversalDependencies/UD_English-EWT",
            "revision": "b7711cce01cdd4f5fcc0a8199b8a50d951b16c0c",
            "file": "en_ewt-ud-test.conllu", "license": "CC-BY-SA-4.0 (annotations/database); original text rights retained",
            "provenance": "Externally human-corrected UD basic dependencies, deterministically mapped to Thorn relation checks; not fresh blind human annotation and model-training overlap is not excluded.",
            "selection": "20 per genre, SHA-256 sentence-id order; 8-60 tokens, unique verbal root, no copula; unique lexical anchors only; fixed before model evaluation",
            "per_genre": 20, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "case_ids": [case["id"] for case in cases],
        }, indent=2))
        return
    import server

    server.load()
    raise SystemExit(evaluate_corpus(args.corpus, server.analyze_text, args.manifest))


if __name__ == "__main__":
    main()

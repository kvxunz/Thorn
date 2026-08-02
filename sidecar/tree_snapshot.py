# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "spacy==3.7.5",
#     "benepar==0.2.0",
#     "torch>=2.2,<3",
#     "transformers==4.30.2",
#     "protobuf==3.20.3",
#     "sentencepiece>=0.1.99",
#     "fastapi>=0.110",
#     "uvicorn>=0.29",
#     "spacy-transformers>=1.3,<1.4",
#     "numpy<2",
#     "en-core-web-trf @ https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.7.3/en_core_web_trf-3.7.3-py3-none-any.whl",
# ]
# ///
"""Every card of every corpus sentence, frozen, so a diff can be reviewed.

`undersplit.py` reports cards that are too *coarse*. Nothing reports cards
that are too fine, and a splitter change trades one for the other: six
separate over-splitting defects — a list shattered into 插入语, stub cards
ending on a stranded preposition, a date cut at its comma — each arrived
disguised as a drop in the coarse-card rate.

This is the missing half. It asserts nothing about what a good tree looks
like; it only asserts that the tree has not changed without someone saying
so. A diff here is not a failure, it is a review request.

    python3 devrunner.py tree_snapshot.py            # compare, exit 1 on drift
    python3 devrunner.py tree_snapshot.py --write     # accept the current trees

Both must run from `sidecar/`, and both need the models, so they go through
`devrunner.py` rather than the fast unittest suite.
"""
import difflib
import hashlib
import json
import os
import re
import sys

import server

SNAPSHOT_DIR = "snapshots"
CONSTRUCTIONS_PATH = "../english_sentence_training.md"
RANDOM_PATH = "/tmp/thorn_corpus.json"

_NUMBERED = re.compile(r"^\d+\.\s+(.*\S)\s*$")

HEADER = """\
# Thorn teaching-tree snapshot -- {corpus}, {count} sentences.
#
# Regenerate: python3 devrunner.py tree_snapshot.py --write
#
# Read every changed line before committing one. This file is the only thing
# in the repo that can see over-splitting; the coarse-card rate cannot.
#
# corpus-digest: {digest}
"""


def load_constructions():
    """The hand-stratified corpus, which lives in the repo."""
    out = []
    with open(CONSTRUCTIONS_PATH) as fh:
        for line in fh:
            found = _NUMBERED.match(line)
            if found:
                out.append(found.group(1))
    return out


def load_random():
    """The sampled corpus, which does not — see `corpus_report.py --fetch`."""
    if not os.path.exists(RANDOM_PATH):
        return None
    with open(RANDOM_PATH) as fh:
        return [item["text"] for item in json.load(fh)]


# `in_repo` says whether a missing or stale snapshot is a failure. The
# stratified corpus ships with the code, so its snapshot must always be
# current; the sampled one is refetched live and simply may not be here.
CORPORA = {
    "constructions": (load_constructions, True),
    "random": (load_random, False),
}


def digest(sentences):
    """Identifies the corpus a snapshot was taken of.

    The sampled corpus is refetched from live Wikipedia and arXiv, so it is a
    different 200 sentences every time. Comparing today's trees against a
    snapshot of yesterday's sentences would report drift that is only the
    corpus moving, so the comparison refuses to run instead.
    """
    joined = "\n".join(sentences).encode()
    return "sha256:" + hashlib.sha256(joined).hexdigest()[:32]


def render(node, depth, out):
    out.append(f"{'  ' * depth}[{node.get('role')}] {node['text']}")
    for child in node.get("children") or []:
        render(child, depth + 1, out)


def snapshot(sentences, name):
    lines = [HEADER.format(
        corpus=name, count=len(sentences), digest=digest(sentences),
    )]
    for text in sentences:
        lines.append(f"== {text}")
        try:
            chunks, _ = server.parse_text(text)
        except Exception as exc:  # noqa: BLE001 - a new crash is drift too
            lines.append(f"  !! {type(exc).__name__}: {exc}")
            lines.append("")
            continue
        for chunk in chunks:
            render(chunk, 1, lines)
        lines.append("")
    return "\n".join(lines)


def path_for(name):
    return os.path.join(SNAPSHOT_DIR, f"{name}.txt")


def main():
    writing = "--write" in sys.argv
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    server.load()

    drifted, stale, skipped = [], [], []
    for name, (loader, in_repo) in CORPORA.items():
        sentences = loader()
        if sentences is None:
            skipped.append(f"{name}: no corpus on disk, nothing to compare")
            continue
        path = path_for(name)
        current = snapshot(sentences, name)
        if writing:
            with open(path, "w") as fh:
                fh.write(current)
            print(f"wrote {path} ({len(sentences)} sentences)")
            continue
        # A snapshot that cannot be compared must not read as a pass. For a
        # corpus that ships with the code there is no innocent reason for one
        # to be missing or stale, and letting it through quietly would leave
        # the whole check green for as long as nobody looked.
        note = None
        if not os.path.exists(path):
            note = f"{name}: no snapshot yet, take one with --write"
        else:
            with open(path) as fh:
                stored = fh.read()
            want = digest(sentences)
            found = re.search(r"^# corpus-digest: (\S+)$", stored, re.MULTILINE)
            if found and found.group(1) != want:
                note = (
                    f"{name}: the corpus itself changed "
                    f"({found.group(1)} -> {want}), so drift here would be "
                    "meaningless. Re-take with --write and review the "
                    "sentences that moved."
                )
        if note is not None:
            (stale if in_repo else skipped).append(note)
            continue
        if stored == current:
            print(f"{name}: unchanged ({len(sentences)} sentences)")
            continue
        drifted.append(name)
        print(f"\n{'=' * 72}\n{name}: the trees changed\n{'=' * 72}")
        # `print`, not `sys.stdout.writelines`: under `devrunner.py` stdout is
        # a socket shim that only implements `write`.
        print("".join(difflib.unified_diff(
            stored.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"{path} (committed)",
            tofile=f"{name} (now)",
            n=2,
        )), end="")

    for note in skipped:
        print(f"skipped {note}")
    for note in stale:
        print(f"STALE {note}")
    if drifted:
        print(
            f"\n{len(drifted)} corpus/corpora drifted. Every line above is a "
            "card a learner will see differently. Once each one is an "
            "improvement, accept them with --write."
        )
    return 1 if drifted or stale else 0


if __name__ == "__main__":
    raise SystemExit(main())

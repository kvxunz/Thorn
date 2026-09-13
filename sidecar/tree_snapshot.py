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
import os
import re
import sys

import server
from corpus import load_sentences

SNAPSHOT_DIR = "snapshots"
CORPUS_NAME = "constructions"

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


def digest(sentences):
    """Identifies the corpus a snapshot was taken of.

    Sentences get added to the corpus, and trees taken of today's sentences
    would then differ from a snapshot of yesterday's for a reason that is not
    a splitter change at all. The comparison refuses to run in that case
    rather than report drift it cannot attribute.
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

    sentences = load_sentences()
    path = path_for(CORPUS_NAME)
    current = snapshot(sentences, CORPUS_NAME)
    if writing:
        with open(path, "w") as fh:
            fh.write(current)
        print(f"wrote {path} ({len(sentences)} sentences)")
        return 0

    # A snapshot that cannot be compared must not read as a pass. The corpus
    # ships with the code, so there is no innocent reason for one to be
    # missing or stale, and letting it through quietly would leave the whole
    # check green for as long as nobody looked.
    if not os.path.exists(path):
        print(f"STALE {CORPUS_NAME}: no snapshot yet, take one with --write")
        return 1
    with open(path) as fh:
        stored = fh.read()
    want = digest(sentences)
    found = re.search(r"^# corpus-digest: (\S+)$", stored, re.MULTILINE)
    if found and found.group(1) != want:
        print(
            f"STALE {CORPUS_NAME}: the corpus itself changed "
            f"({found.group(1)} -> {want}), so drift here would be "
            "meaningless. Re-take with --write and review the sentences "
            "that moved."
        )
        return 1

    if stored == current:
        print(f"{CORPUS_NAME}: unchanged ({len(sentences)} sentences)")
        return 0

    print(f"\n{'=' * 72}\n{CORPUS_NAME}: the trees changed\n{'=' * 72}")
    # `print`, not `sys.stdout.writelines`: under `devrunner.py` stdout is
    # a socket shim that only implements `write`.
    print("".join(difflib.unified_diff(
        stored.splitlines(keepends=True),
        current.splitlines(keepends=True),
        fromfile=f"{path} (committed)",
        tofile=f"{CORPUS_NAME} (now)",
        n=2,
    )), end="")
    print(
        "\nEvery line above is a card a learner will see differently. Once "
        "each one is an improvement, accept them with --write."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

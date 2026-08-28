"""The hand-stratified sentence corpus, and the single way to read it.

`tree_snapshot.py` freezes a tree per sentence; `corpus_report.py` measures a
rate per construction. Both read the same markdown file, and for a while both
carried their own copy of the path, the numbering regex and the loop — so the
file had two owners and a format change needed two edits.

Run from `sidecar/`: the path is relative, as it is in every other tool here.
"""
import re

CONSTRUCTIONS_PATH = "../english_sentence_training.md"

_NUMBERED = re.compile(r"^\d+\.\s+(.*\S)\s*$")


def load_constructions(path=CONSTRUCTIONS_PATH):
    """Every numbered sentence, tagged with the `### ` heading above it.

    Random sampling measures the *average* sentence, so a construction the
    language uses rarely contributes nothing however many sentences you draw:
    200 sampled ones held no VP ellipsis at all. This file is stratified by
    hand — ellipsis, inversion, comparatives, parentheticals — so each stratum
    gets a rate of its own, and a construction the rules never learned shows up
    as its own bad column instead of vanishing into the average.

    Callers that only want the sentences read `text` and ignore `register`.
    """
    stratum = "unlabelled"
    items = []
    with open(path) as fh:
        for line in fh:
            if line.startswith("### "):
                stratum = line[4:].strip()
                continue
            found = _NUMBERED.match(line)
            if found:
                items.append({"register": stratum, "text": found.group(1)})
    return items


def load_sentences(path=CONSTRUCTIONS_PATH):
    """Just the sentences, in file order."""
    return [item["text"] for item in load_constructions(path)]

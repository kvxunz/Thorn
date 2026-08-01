"""Compact, lossless parser evidence for Thorn's teaching-model stage."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

ANALYSIS_PROTOCOL_VERSION = 4
# Backward-compatible import for callers that only consume /analyze.
PROTOCOL_VERSION = ANALYSIS_PROTOCOL_VERSION


def build_analysis_evidence(
    doc,
    source: str,
    *,
    spacy_model: str,
    benepar_model: str,
    spacy_version: str | None = None,
    benepar_version: str | None = None,
    source_token_offsets: Sequence[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Serialize spaCy dependencies and Benepar spans without interpreting them."""
    if (
        source_token_offsets is not None
        and len(source_token_offsets) != len(doc)
    ):
        raise ValueError("analysis token offsets do not match parser tokens")
    tokens = [
        {
            "i": token.i,
            "t": (
                source[
                    source_token_offsets[token.i][0]:
                    source_token_offsets[token.i][1]
                ]
                if source_token_offsets is not None else token.text
            ),
            "a": (
                source_token_offsets[token.i][0]
                if source_token_offsets is not None else token.idx
            ),
            "b": (
                source_token_offsets[token.i][1]
                if source_token_offsets is not None
                else token.idx + len(token.text)
            ),
            "l": token.lemma_,
            "p": token.pos_,
            "x": token.tag_,
            "m": str(token.morph),
            "d": token.dep_,
            "h": token.head.i,
        }
        for token in doc
    ]

    sentences = []
    raw_constituents: dict[tuple[int, int], set[str]] = {}
    for sid, sentence in enumerate(doc.sents):
        sentences.append({
            "sid": sid,
            "s": sentence.start,
            "e": sentence.end,
            "r": sentence.root.i,
        })
        for constituent in sentence._.constituents:
            labels = set(constituent._.labels)
            if not labels:
                continue
            key = (constituent.start, constituent.end)
            raw_constituents.setdefault(key, set()).update(labels)

    spans = [
        (start, end, sorted(labels))
        for (start, end), labels in raw_constituents.items()
    ]
    spans.sort(key=lambda item: (item[0], -item[1], item[2]))
    constituents = []
    for start, end, labels in spans:
        depth = sum(
            1
            for outer_start, outer_end, _ in spans
            if outer_start <= start
            and end <= outer_end
            and (outer_start < start or end < outer_end)
        )
        constituents.append({
            "s": start,
            "e": end,
            "l": labels,
            "d": depth,
        })

    return {
        "protocolVersion": ANALYSIS_PROTOCOL_VERSION,
        "source": source,
        "tokens": tokens,
        "sentences": sentences,
        "constituents": constituents,
        "parser": {
            "status": "ready",
            "spacy": spacy_model,
            "benepar": benepar_model,
            "spacyVersion": spacy_version,
            "beneparVersion": benepar_version,
        },
    }

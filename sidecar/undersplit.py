"""Detect teaching cards that swallowed structure instead of showing it.

A construction with no matching rule does not raise: the tree stays legal and
the panel shows one wide card where it should have shown a layer.  That is the
worst failure this pipeline has, because it is indistinguishable from a
correct coarse reading -- the user is told nothing.

This module names that shape.  It is a *measuring instrument* first: run it
over a corpus and the coarse-card rate is the number that says how far the
rule set is from the language, which no green test suite can tell you.

It reads only the public chunk tree plus `TeachingEvidence`, so it is a pure
observer -- it never changes what gets taught.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from teaching_tree import TeachingEvidence

# VB/VBG/VBN are non-finite: "to lash", "running", "been seen" are ordinary
# parts of a card. A tensed verb is what makes a span a clause.
FINITE_VERB_TAGS = frozenset({"VBD", "VBP", "VBZ", "MD"})

SUBJECT_DEPS = frozenset({"nsubj", "nsubjpass", "csubj", "csubjpass", "expl"})

# Words that can only introduce embedded structure. A leaf holding one of them
# is holding a clause boundary it never drew.
WH_TAGS = frozenset({"WDT", "WP", "WP$", "WRB"})

# Below this a wide leaf is not worth reporting: flat noun phrases like
# "the man in the black hat over there" are legitimately one card.
WIDE_LEAF_TOKENS = 8


@dataclass(frozen=True)
class UndersplitFinding:
    """One card that reads as coarser than the sentence it covers."""

    start: int
    end: int
    role: str
    signal: str
    text: str


def _iter_leaves(
    chunks: Sequence[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    for chunk in chunks:
        children = chunk.get("children") or ()
        if children:
            yield from _iter_leaves(children)
        else:
            yield chunk


def _bounds(chunk: dict[str, Any]) -> tuple[int, int]:
    """Span in parser-token space.

    `_prepare_document` builds one source offset per parser token, so the
    public `s`/`e` index the same positions as `evidence.tokens` even though
    they name the user's original characters rather than the normalized ones
    spaCy saw. `_lo`/`_hi` are the same numbers before alignment strips them.
    """
    if "s" in chunk and "e" in chunk:
        return int(chunk["s"]), int(chunk["e"])
    return int(chunk["_lo"]), int(chunk["_hi"])


def classify_leaf(
    start: int,
    end: int,
    evidence: TeachingEvidence,
) -> str | None:
    """The strongest under-split signal in a span, or None if it reads fine."""
    tokens = evidence.tokens[start:end]

    has_finite_verb = any(token.tag in FINITE_VERB_TAGS for token in tokens)
    # The subject's head must sit inside the span too, otherwise this is a
    # subject card whose verb correctly lives in a sibling.
    has_own_subject = any(
        token.dep in SUBJECT_DEPS and start <= token.head < end
        for token in tokens
    )
    if has_finite_verb and has_own_subject:
        return "clause-in-one-card"

    content = [token for token in tokens if token.pos != "PUNCT"]

    # A card that *is* the wh-word ("who", "which") is the boundary drawn
    # correctly, not a missed one -- only a wh-word buried among other material
    # means the clause it introduces never got its own layer.
    if len(content) >= 3 and any(token.tag in WH_TAGS for token in tokens):
        return "wh-word-in-leaf"

    if len(content) >= WIDE_LEAF_TOKENS:
        return "wide-leaf"
    return None


def find_undersplit(
    chunks: Sequence[dict[str, Any]],
    evidence: TeachingEvidence,
    source_tokens: Sequence[str],
) -> list[UndersplitFinding]:
    """Every leaf card that looks like a rule miss, outermost first.

    `evidence` must come from the *same* document `chunks` were built from.
    `_prepare_document` normalizes dashes and exotic spaces before handing the
    text to spaCy, so evidence built from the raw string tokenizes differently
    and every span here would read the wrong words -- silently, because a
    shifted span is still a legal one. The count and text checks below turn
    that into a loud failure.

    Note the two token spaces this straddles: `evidence.tokens` carries the
    *normalized* characters spaCy saw, `source_tokens` the user's original
    ones. They are index-aligned one-to-one -- only the characters differ --
    so spans are interchangeable but text is not.
    """
    if len(source_tokens) != len(evidence.tokens):
        raise ValueError(
            f"{len(source_tokens)} source tokens vs {len(evidence.tokens)} "
            "evidence tokens -- evidence is from a different document"
        )
    findings = []
    for leaf in _iter_leaves(chunks):
        start, end = _bounds(leaf)
        if not (0 <= start < end <= len(evidence.tokens)):
            raise ValueError(f"leaf span {start}:{end} escapes the evidence")
        expected = "".join("".join(source_tokens[start:end]).split())
        if "".join(str(leaf.get("text") or "").split()) != expected:
            raise ValueError(
                f"leaf {start}:{end} text {leaf.get('text')!r} does not match "
                f"source tokens {expected!r}"
            )
        signal = classify_leaf(start, end, evidence)
        if signal is None:
            continue
        findings.append(
            UndersplitFinding(
                start=start,
                end=end,
                role=str(leaf.get("role") or "other"),
                signal=signal,
                text=str(leaf.get("text") or ""),
            )
        )
    return findings

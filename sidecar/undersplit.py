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

# Punctuation that opens a new constituent when it appears mid-card. A card
# holding one of these is holding a boundary the splitter declined to draw.
# The comma is deliberately absent -- it is the one separator that is more
# often *not* a boundary, and `_comma_opens_a_slot` below judges it per case.
SEPARATORS = frozenset({";", ":", "—", "–", "--", "(", ")"})

# Dependencies that make a token a pre-modifier of the word it hangs on rather
# than the head of anything: "January Magazine" and "New York" reach their real
# dependency one hop up, and it is that hop that says whether a comma before
# them opened a slot.
PREMODIFIER_DEPS = frozenset({"compound", "amod", "det", "nummod", "poss",
                              "quantmod", "predet", "advmod"})

# A comma before one of these continues the phrase instead of interrupting it:
# "the retail, corporate and wholesale markets", "energy, labor, and other
# inputs" are single slots with coordinated heads. Splitting them would be a
# defect, so reporting them is one too.
CONTINUATION_DEPS = frozenset({"conj", "cc"})

# An appositive inside a leaf is a second naming of the head noun, a relative
# or adverbial clause is a layer: two slots shown as one either way. Plain
# `conj` is deliberately absent -- "human nature and human motives" is one slot
# with a coordinated head, and splitting it would be wrong. `pcomp` is handled
# separately below because only some of them are clauses.
STRUCTURE_DEPS = frozenset({"appos", "relcl", "acl", "advcl", "ccomp"})

# All a reporting clause is allowed to hang off its verb. Anything else -- an
# object, a complement, a prepositional phrase -- means the clause carries
# content of its own and is not the fixed "she said" frame.
ATTRIBUTION_DEPS = frozenset({"nsubj", "nsubjpass", "aux", "auxpass", "neg",
                              "advmod", "prt"})


def _is_inserted_attribution(
    tokens: Sequence[Any],
    start: int,
    end: int,
) -> bool:
    """Whether the span is a reporting clause spliced into another sentence.

    ", she said," and ",” he went on, “" are meant to be single insertion
    cards: the interruption reads as one thing, and "she" and "said" on
    separate cards would teach nothing about it. spaCy calls the verb
    `parataxis` -- but so is the verb of a genuinely embedded clause
    ("--for some reason it was the gloomiest event of my day--"), which *does*
    deserve the layer, so the label alone cannot tell them apart.

    What separates them is that a reporting clause is bare. Its complement is
    the surrounding sentence, so nothing but a subject hangs off the verb.
    """
    verbs = [
        token for token in tokens
        if token.dep == "parataxis" and not start <= token.head < end
    ]
    if len(verbs) != 1:
        return False
    verb = verbs[0]
    return all(
        # Punctuation is never the missing layer -- and the quotes around an
        # interruption sit outside its clause, hanging off the verb it broke.
        token.pos == "PUNCT"
        or token.index == verb.index
        or (token.head == verb.index and token.dep in ATTRIBUTION_DEPS)
        for token in tokens
    )


def _is_bare_name_appositive(token: Any, tokens: Sequence[Any]) -> bool:
    """A second proper name hung on a first: "Rossie, New York".

    spaCy labels these ``appos``, but an address is not a second naming worth
    its own card. A teaching appositive introduces its noun with a determiner
    ("Lloyd Nickson, a 54-year-old Darwin resident"), and that is what tells
    the two apart.
    """
    return (
        token.dep == "appos"
        and token.pos == "PROPN"
        and not any(
            other.dep == "det" and other.head == token.index for other in tokens
        )
    )


def _comma_opens_a_slot(
    tokens: Sequence[Any],
    position: int,
    start: int,
    end: int,
) -> bool:
    """Whether the comma at ``position`` fences off material of its own.

    Most mid-card commas do not. A serial list ("energy, labor, and other
    inputs of crop production") and a pair of coordinate adjectives ("such
    large, impersonal manipulation") are each one slot with a coordinated
    head, and a card that holds them whole is right. Reporting those buried
    the real findings under correct cards -- the same mistake the raw width
    threshold used to make, one level down.

    What the comma is followed by settles it. A conjunct or a conjunction
    continues the phrase; anything else -- an appositive, "such as", "i.e.",
    an inserted "she said" -- interrupts it.
    """
    def phrase_head(token):
        """Walk a bare modifier up to the word it actually modifies."""
        seen = 0
        while (
            token.dep in PREMODIFIER_DEPS
            and start <= token.head < end
            and seen < len(tokens)
        ):
            token = tokens[token.head - start]
            seen += 1
        return token

    raw_after = next(
        (token for token in tokens[position + 1:] if token.pos != "PUNCT"),
        None,
    )
    if raw_after is None:
        return False
    # "January Magazine", "New York": the first word is a bare modifier, so it
    # is the phrase's head that carries the dependency worth reading.
    after = phrase_head(raw_after)
    if after.dep in CONTINUATION_DEPS:
        return False

    # Coordinate modifiers of one noun: "such large, impersonal manipulation",
    # "the cautious, unadorned prose", "the inflexible, though tacit, rules".
    # Both sides describe the same word, so the comma is punctuation inside one
    # slot. There is no way to split it into cards anyway -- the two modifiers
    # are not contiguous with each other once the noun is taken out.
    before = next(
        (token for token in reversed(tokens[:position]) if token.pos != "PUNCT"),
        None,
    )
    if (
        before is not None
        and before.dep in PREMODIFIER_DEPS
        and raw_after.dep in PREMODIFIER_DEPS
        and phrase_head(before).index == after.index
    ):
        return False
    return not _is_bare_name_appositive(after, tokens)


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
    if (
        has_finite_verb
        and has_own_subject
        and not _is_inserted_attribution(tokens, start, end)
    ):
        return "clause-in-one-card"

    content = [token for token in tokens if token.pos != "PUNCT"]

    # A card that *is* the wh-word ("who", "which") is the boundary drawn
    # correctly, not a missed one -- only a wh-word buried among other material
    # means the clause it introduces never got its own layer.
    if len(content) >= 3 and any(token.tag in WH_TAGS for token in tokens):
        return "wh-word-in-leaf"

    # Length alone says nothing. "his distrust of human nature and human
    # motives" and "no incentives for buying stock in certain industries" are
    # nine and ten tokens of flat noun phrase, and one card is the right
    # reading of both -- reported as misses they drowned the real findings and
    # invited "fixes" that would have split correct phrases. A wide leaf is
    # only a miss when it *holds* a boundary it declined to draw: separator
    # punctuation in the middle, or a clause-forming dependency whose head sits
    # inside the span.
    if len(content) < WIDE_LEAF_TOKENS:
        return None
    for position, token in enumerate(tokens[:-1]):
        if token.text in SEPARATORS:
            return "wide-leaf"
        if token.text == "," and _comma_opens_a_slot(tokens, position, start, end):
            return "wide-leaf"
    for token in tokens:
        if not start <= token.head < end:
            continue
        if token.dep in STRUCTURE_DEPS and not _is_bare_name_appositive(
            token, tokens
        ):
            return "wide-leaf"
        # A `pcomp` is a clause only when it brings its own subject. "for
        # buying stock in certain industries", "of translating her eccentric
        # prose" are gerunds inside a prepositional phrase -- one card is the
        # right reading, and reporting them was the same length-not-structure
        # mistake as the raw width threshold.
        if token.dep == "pcomp" and any(
            other.dep in SUBJECT_DEPS and other.head == token.index
            for other in tokens
        ):
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
        role = str(leaf.get("role") or "other")
        signal = classify_leaf(start, end, evidence)
        # A card whose own label says it holds two slots is not hiding either.
        # "I'm supposed", "That's" cannot be split at all -- the boundary falls
        # inside a written word -- so the role is the whole of what can be
        # taught there, and reporting it invites a fix that does not exist.
        if signal == "clause-in-one-card" and role == "subject-verb":
            continue
        if signal is None:
            continue
        findings.append(
            UndersplitFinding(
                start=start,
                end=end,
                role=role,
                signal=signal,
                text=str(leaf.get("text") or ""),
            )
        )
    return findings

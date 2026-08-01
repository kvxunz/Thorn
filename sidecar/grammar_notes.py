"""Deterministic grammar notes for function-word chunks.

Some cards translate to nothing useful.  An anticipatory ``It`` has no
Chinese counterpart, a complementizer ``that`` is not a word, an emphatic
``himself`` is not an object.  Asking a translator for these yields either
an empty string or a confident lie — but what a learner actually needs
there is not a translation, it is a note about the construction, and the
dependency tree already knows which construction it is.

Every rule below decides on parse evidence alone and has a verified
negative case that it must stay silent on.  Silence is the safe outcome:
a missing note costs a card nothing, a wrong note teaches wrong grammar.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# A head that governs one of these has a clause carrying the meaning its
# subject slot lacks, which is what makes a preceding ``it`` a placeholder.
# ``advcl`` is absent: "It was raining when I left" has one, and that is
# weather-it, not a formal subject.
_EXTRAPOSED_DEPS = frozenset({"ccomp", "csubj", "csubjpass"})

# What a copula's own complement looks like.  This is the whole difference
# between extraposition and subject raising, which are otherwise identical
# — both are ``it`` + head + ``xcomp``:
#
#   It is advisable to find out …   is/be   [advisable/acomp, find/xcomp]
#   It seems to work now.           seems   [work/xcomp]
#
# A raising verb (seem/tend/continue/appear) has no complement of its own to
# raise out of, so requiring one keeps referential ``it`` unannotated.
_COPULA_COMPLEMENT_DEPS = frozenset({"acomp", "attr"})

# A reflexive in one of these slots is an adjunct, so it is emphasis.  The
# object slots (dobj/pobj/iobj) are the true reflexive use and get no note.
_REFLEXIVE_ADJUNCT_DEPS = frozenset({"appos", "npadvmod"})

# What kind of clause a complementizer opens, read off its head's own role.
_CLAUSE_KIND_NOTES = {
    "ccomp": "引导宾语从句，本身不译",
    "csubj": "引导主语从句，本身不译",
    "csubjpass": "引导主语从句，本身不译",
    "acl": "引导同位语从句，说明前面的名词",
    "advcl": "引导状语从句，本身不译",
}


def _has_clausal_complement(head) -> bool:
    extraposing = head.lemma_ == "be" and any(
        child.dep_ in _COPULA_COMPLEMENT_DEPS for child in head.children
    )
    for child in head.children:
        if child.dep_ in _EXTRAPOSED_DEPS:
            return True
        if child.dep_ == "xcomp" and extraposing:
            return True
    return False


def _anticipatory_it(token) -> str:
    """``It`` that stands in for a clause stated later in the sentence.

    spaCy does not tag this ``expl`` — only "There is…" gets that — and the
    placeholder is morphologically identical to a referential ``it``.  The
    discriminator has to be the head: a formal subject is only formal
    because the real content is a clause hanging off the same verb.
    """
    if token.lower_ != "it" or token.dep_ != "nsubj" or token.pos_ != "PRON":
        return ""
    if not _has_clausal_complement(token.head):
        return ""
    return "形式主语，真正内容在后面的从句"


def _emphatic_reflexive(token) -> str:
    """``himself`` used for emphasis, not as an object.

    "Shakespeare was himself an actor" and "He hurt himself" share a form
    and share ``Reflex=Yes``; they differ in slot, and the slot is exactly
    what the parse gives.
    """
    if "Yes" not in token.morph.get("Reflex"):
        return ""
    if token.dep_ not in _REFLEXIVE_ADJUNCT_DEPS:
        return ""
    return "强调“本人、亲自”，不是宾语"


def _complementizer_that(token) -> str:
    """``that`` opening a clause, as opposed to the demonstrative.

    The demonstrative "that book" is ``det`` and the pronoun "I want that"
    is ``dobj``; requiring ``mark`` leaves only the empty one.
    """
    if token.lower_ != "that" or token.dep_ != "mark" or token.pos_ != "SCONJ":
        return ""
    clause = token.head
    if clause.dep_ == "ccomp" and clause.head.lemma_ == "be":
        # "It is no wonder that he left": spaCy hangs the clause off the
        # copula as ccomp, but nothing there is an object.  Name the clause
        # type only when the governor can actually take one.
        return "引导从句，本身不译"
    return _CLAUSE_KIND_NOTES.get(clause.dep_, "引导从句，本身不译")


def _degree_all(token) -> str:
    """``all`` as an intensifier: "all deliciously ironic", not "全部"."""
    if token.lower_ != "all" or token.pos_ != "ADV" or token.dep_ != "advmod":
        return ""
    return "程度副词“完全”，不是“全部”"


_RULES = (
    _anticipatory_it,
    _emphatic_reflexive,
    _complementizer_that,
    _degree_all,
)


def note_for_token(token) -> str:
    """The first note that applies to ``token``, or "" if none does."""
    for rule in _RULES:
        note = rule(token)
        if note:
            return note
    return ""


def annotate_grammar_notes(
    chunks: Sequence[dict[str, Any]],
    doc,
) -> None:
    """Fill empty glosses on single-token cards, in place.

    Only single-token cards are considered: a note describes one word's job
    in the sentence, and a card spanning a whole phrase has no single word
    to describe.  Cards that already carry a gloss — relative pronouns get
    one from the tree builder — are left alone.
    """
    for chunk in chunks:
        children = chunk.get("children")
        if children:
            annotate_grammar_notes(children, doc)
        if chunk.get("gloss"):
            continue
        start = chunk.get("s")
        end = chunk.get("e")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if end - start != 1 or not 0 <= start < len(doc):
            continue
        note = note_for_token(doc[start])
        if note:
            chunk["gloss"] = note

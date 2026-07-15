"""Small dependency-free lexical rules used by the structure sidecar."""


FIXED_ADVERBIAL_PARTICLES = {
    ("look", "back"),
}

RELATIVE_INTRODUCERS = {
    "that", "which", "who", "whom", "whose", "where", "when",
}


def is_fixed_adverbial_particle(verb_lemma, child_text, child_dependency):
    """Return whether an advmod is a lexical part of its governing verb."""
    return (
        child_dependency == "advmod"
        and (verb_lemma.lower(), child_text.lower()) in FIXED_ADVERBIAL_PARTICLES
    )


def is_concessive_however_clause(clause_dependency, token_signals):
    """Detect a degree-concessive clause mislabeled as a noun relative.

    Each token signal is ``(text, dependency, pos, head_pos, tag)``. Parsers
    can attach ``however difficult the results may be`` as ``relcl`` to the
    preceding noun even though it has its own subject and no relative marker.
    """
    if clause_dependency not in ("relcl", "acl"):
        return False

    signals = list(token_signals)
    has_degree_however = any(
        text.lower() == "however"
        and dependency == "advmod"
        and head_pos in ("ADJ", "ADV")
        for text, dependency, _pos, head_pos, _tag in signals
    )
    has_subject = any(
        dependency in ("nsubj", "nsubjpass")
        for _text, dependency, _pos, _head_pos, _tag in signals
    )
    has_predicate = any(
        pos in ("VERB", "AUX")
        for _text, _dependency, pos, _head_pos, _tag in signals
    )
    has_relative_introducer = any(
        text.lower() in RELATIVE_INTRODUCERS
        for text, _dependency, _pos, _head_pos, _tag in signals
    )
    return (
        has_degree_however
        and has_subject
        and has_predicate
        and not has_relative_introducer
    )

"""Small dependency-free lexical rules used by the structure sidecar."""

from dataclasses import dataclass
import re


# deps absorbed into the finite verbal complex (aux chain + mid-complex adverbs)
VERB_GROUP_CORE_DEPS = frozenset({"aux", "auxpass", "neg", "prt"})
VERB_GROUP_ADVERB_DEPS = frozenset({"advmod", "neg"})


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


def verb_group_indices(head):
    """Indices of the finite verbal complex for ``head``.

    Covers auxiliaries, negation, particles, fixed adverbial particles, and
    degree/manner adverbs that sit *inside* the aux→verb span — including
    nested modifiers (``would almost certainly bring`` where *almost* attaches
    to *certainly*, not to *bring*).
    """
    toks = {head.i}
    lemma = getattr(head, "lemma_", getattr(head, "text", ""))
    for c in head.children:
        dep = getattr(c, "dep_", "")
        if dep in VERB_GROUP_CORE_DEPS or is_fixed_adverbial_particle(
            lemma, getattr(c, "text", ""), dep
        ):
            toks.add(c.i)
    if len(toks) <= 1:
        return toks

    # Iteratively absorb mid-complex adverbs whose head is already in the group
    # (handles stacked degree: almost → certainly → bring).
    doc = head.doc
    changed = True
    while changed:
        changed = False
        lo, hi = min(toks), max(toks)
        for i in range(lo + 1, hi):
            if i in toks:
                continue
            t = doc[i]
            if (
                getattr(t, "dep_", "") in VERB_GROUP_ADVERB_DEPS
                and getattr(t.head, "i", -1) in toks
            ):
                toks.add(i)
                changed = True
    return toks


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


# Past participles that introduce a comitative/accompanying phrase, not a
# true reduced relative ("the book written by X").
COMITATIVE_PARTICIPLE_LEMMAS = frozenset({
    "couple", "combine", "accompany", "associate", "along",
    "together",  # rare as VBN but harmless
})

# Comma-bounded prepositional discourse markers: pragmatic asides, not
# structural prep-phrases. Closed list on purpose — anything else stays literal.
DISCOURSE_MARKERS = frozenset({
    "of course", "in fact", "after all", "at least", "for example",
    "for instance", "in short", "in other words", "on the contrary",
    "as a result", "in addition", "by contrast", "in contrast",
    "on the other hand", "in general", "in particular", "above all",
    "in a sense", "in essence", "to be sure",
})


def mark_discourse_insertions(chunks):
    """Relabel childless prep-phrase chunks that are fixed discourse markers."""
    for ch in chunks:
        if (ch.get("role") == "prep-phrase" and not ch.get("children")
                and ch.get("text", "").strip(" ,.;:").lower() in DISCOURSE_MARKERS):
            ch["role"] = "insertion"
    return chunks


def merge_or_so(chunks):
    """Fuse discourse 'or so' (≈ roughly / 可以说) — not causal so."""
    out = []
    for ch in chunks:
        prev = out[-1] if out else None
        if (
            prev
            and prev.get("role") == "conjunction"
            and prev.get("text", "").strip().lower().rstrip(",") == "or"
            and ch.get("role") in ("conjunction", "adverbial", "other")
            and ch.get("text", "").strip().lower().rstrip(",") == "so"
            and not ch.get("children")
        ):
            glue = "" if prev["text"].endswith(" ") or ch["text"].startswith(" ") else " "
            prev["text"] = prev["text"] + glue + ch["text"]
            prev["role"] = "insertion"
            if "_hi" in ch:  # keep internal token bounds exact after fusion
                prev["_hi"] = ch["_hi"]
            continue
        out.append(ch)
    return out


def is_comitative_participle(token):
    """Return whether ``token`` is VBN acl like 'coupled with the desire…'.

    ``token`` is a spaCy-like object with ``tag_``, ``lemma_``, and
    ``children`` (each child has ``dep_`` and ``lower_``).
    """
    if getattr(token, "tag_", "") != "VBN":
        return False
    lemma = getattr(token, "lemma_", "").lower()
    children = list(getattr(token, "children", []) or [])
    has_with = any(
        getattr(ch, "dep_", "") == "prep"
        and getattr(ch, "lower_", getattr(ch, "text", "")).lower() == "with"
        for ch in children
    )
    has_own_subject = any(
        getattr(ch, "dep_", "") in ("nsubj", "nsubjpass", "csubj", "csubjpass")
        for ch in children
    )
    if has_own_subject:
        return False
    if lemma in COMITATIVE_PARTICIPLE_LEMMAS and has_with:
        return True
    # Broader: VBN + only with/by-prep (and punctuation) — e.g. "faced with"
    if has_with and all(
        getattr(ch, "dep_", "") in ("prep", "punct", "agent", "advmod")
        for ch in children
    ):
        return lemma in COMITATIVE_PARTICIPLE_LEMMAS or lemma in {
            "face", "confront", "equip", "arm", "endow",
        }
    return False


def is_clausal_pcomp(token):
    """Whether a preposition's complement is a full clause: verbal head with
    its own subject ("in how well it can control expression", "of whether it
    works"). Expanded like other clauses. Subjectless gerunds ("in doing so")
    stay flat."""
    if getattr(token, "dep_", "") != "pcomp":
        return False
    if getattr(token, "pos_", "") not in ("VERB", "AUX"):
        return False
    return any(
        getattr(child, "dep_", "") in ("nsubj", "nsubjpass", "csubj", "csubjpass")
        for child in getattr(token, "children", []) or []
    )


_SUBJECT_DEPS = frozenset({"nsubj", "nsubjpass", "csubj", "csubjpass", "expl"})


def has_own_subject(token):
    """True when ``token`` carries a clausal subject among its children."""
    return any(
        getattr(child, "dep_", "") in _SUBJECT_DEPS
        for child in getattr(token, "children", []) or []
    )


def independent_verbal_conjuncts(token):
    """Yield verbal ``conj`` children of ``token`` that look like full clauses.

    Parsers often attach coordinated full clauses under a ccomp head::

        say → curl (ccomp) → tormented (conj, with its own nsubj)

    Teaching trees want those conjuncts as *siblings* of the ccomp (parallel
    reasons / statements), not buried inside the reported content. Only
    conjuncts with their own subject are promoted; shared-subject VP
    coordination ("came and left") stays nested.
    """
    for child in getattr(token, "children", []) or []:
        if getattr(child, "dep_", "") != "conj":
            continue
        if getattr(child, "pos_", "") not in ("VERB", "AUX"):
            continue
        if has_own_subject(child):
            yield child


def coordinating_ccs_before(token, conjunct):
    """Yield ``cc`` children of ``token`` that sit between it and ``conjunct``.

    Lifted with the conjunct so "and" is a sibling conjunction rather than a
    trailing piece of the first clause.
    """
    token_i = getattr(token, "i", None)
    conj_i = getattr(conjunct, "i", None)
    if token_i is None or conj_i is None:
        return
    for child in getattr(token, "children", []) or []:
        if getattr(child, "dep_", "") != "cc":
            continue
        child_i = getattr(child, "i", None)
        if child_i is None:
            continue
        if token_i < child_i < conj_i:
            yield child


_PREP_CONJ_TEXTS = frozenset({
    "by", "with", "in", "on", "for", "from", "to", "at", "of", "as", "into",
    "through", "over", "under", "about", "after", "before", "between", "without",
})


def coordinated_prep_conjuncts(token):
    """Yield preposition-like ``conj`` children of a prep/agent head.

    ``marked first by X … and then by Y`` attaches the second *by* as conj of
    the first; teaching trees want both as sibling prep-phrases under the verb.
    """
    for child in getattr(token, "children", []) or []:
        if getattr(child, "dep_", "") != "conj":
            continue
        pos = getattr(child, "pos_", "")
        lower = getattr(child, "lower_", getattr(child, "text", "")).lower()
        if pos == "ADP" or lower in _PREP_CONJ_TEXTS:
            yield child


def is_preposed_though_adjective(token):
    """``Odd though it sounds``: adjective advcl heading a though/as clause."""
    if getattr(token, "dep_", "") != "advcl":
        return False
    if getattr(token, "pos_", "") not in ("ADJ", "ADV"):
        return False
    for child in getattr(token, "children", []) or []:
        if getattr(child, "dep_", "") != "advcl":
            continue
        if getattr(child, "pos_", "") not in ("VERB", "AUX"):
            continue
        if any(
            getattr(mark, "dep_", "") == "mark"
            and getattr(mark, "lower_", "").lower() in ("though", "as", "although")
            for mark in getattr(child, "children", []) or []
        ):
            return True
    return False


def though_clause_verb(token):
    """Finite verb under a preposed adjective though/as construction."""
    for child in getattr(token, "children", []) or []:
        if (
            getattr(child, "dep_", "") == "advcl"
            and getattr(child, "pos_", "") in ("VERB", "AUX")
        ):
            return child
    return None


def is_dash_appositive(token):
    """Appositive set off by dashes/commas (``Institute—a group—issued``)."""
    if getattr(token, "dep_", "") != "appos":
        return False
    head = getattr(token, "head", None)
    if head is None:
        return False
    doc = getattr(token, "doc", None)
    if doc is None:
        return True
    left = min(getattr(token, "i", 0), getattr(head, "i", 0))
    right = max(getattr(token, "i", 0), getattr(head, "i", 0))
    for index in range(left, right + 1):
        text = doc[index].text
        if text in ("--", "—", "–") or doc[index].dep_ == "punct" and text in (",",):
            # comma alone is weak; prefer dash or both sides punct around appos
            if text in ("--", "—", "–"):
                return True
    # spaCy often attaches ``--`` as punct children of the head noun
    for child in list(getattr(head, "children", []) or []) + list(
        getattr(token, "children", []) or []
    ):
        if getattr(child, "text", "") in ("--", "—", "–"):
            return True
    return False


def is_wh_relative_pronoun(token):
    """who/which/that introducing a relative clause."""
    tag = getattr(token, "tag_", "")
    if tag in ("WDT", "WP", "WP$", "WRB"):
        return True
    lower = getattr(token, "lower_", getattr(token, "text", "")).lower()
    return lower in {"who", "whom", "whose", "which", "that", "where", "when"}


_OCR_BRACKET_JUNK = re.compile(r"\[[A-Za-z0-9]{1,8}\]")
_DASH_RUN = re.compile(r"[—–―]+|-{2,}")
_EXOTIC_SPACE = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")
_PDF_JUNK = re.compile(r"[\ue000-\uf8ff\ufffc\ufffd]")


@dataclass(frozen=True)
class PreparedParseText:
    """Display-safe source plus a parser view mapped back to that source."""

    surface: str
    parser: str
    parser_char_spans: tuple[tuple[int, int], ...]

    def source_token_offsets(
        self,
        parser_token_offsets,
    ) -> tuple[tuple[int, int], ...]:
        offsets = []
        for start, end in parser_token_offsets:
            if not (0 <= start < end <= len(self.parser_char_spans)):
                raise ValueError(f"invalid parser token offset: {start}:{end}")
            mapped = self.parser_char_spans[start:end]
            source_start = min(span[0] for span in mapped)
            source_end = max(span[1] for span in mapped)
            if source_end <= source_start:
                raise ValueError(f"parser token has no source text: {start}:{end}")
            offsets.append((source_start, source_end))
        return tuple(offsets)


def _surface_parse_text(text: str) -> str:
    """Remove only known copy/PDF artifacts; retain meaningful typography."""
    cleaned = _EXOTIC_SPACE.sub(" ", text)
    # Replace visible attachment markers with a boundary before collapsing
    # whitespace; deletion could fuse ``Security\uFFFCwith`` into one token.
    cleaned = _PDF_JUNK.sub(" ", cleaned)
    cleaned = _OCR_BRACKET_JUNK.sub(" ", cleaned)
    cleaned = cleaned.replace("\u00ad", "").replace("\u2060", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def prepare_parse_text(text: str) -> PreparedParseText:
    """Build a normalized parser view without rewriting displayed source text."""
    surface = _surface_parse_text(text)
    parser_chars: list[str] = []
    source_spans: list[tuple[int, int]] = []
    index = 0
    while index < len(surface):
        dash = _DASH_RUN.match(surface, index)
        if dash is not None:
            start, end = dash.span()
            # Be idempotent when the surface already contains whitespace
            # around the dash. A second pair of synthetic spaces made spaCy
            # emit whitespace tokens whose old zero-width mapping could not
            # be projected back to source text.
            if not parser_chars or parser_chars[-1] != " ":
                parser_chars.append(" ")
                source_spans.append((start, end))
            parser_chars.extend(("-", "-"))
            source_spans.extend(((start, end), (start, end)))
            if end >= len(surface) or not surface[end].isspace():
                parser_chars.append(" ")
                source_spans.append((start, end))
            index = end
            continue
        if surface[index].isspace():
            end = index + 1
            while end < len(surface) and surface[end].isspace():
                end += 1
            parser_chars.append(" ")
            source_spans.append((index, end))
            index = end
            continue
        parser_chars.append(surface[index])
        source_spans.append((index, index + 1))
        index += 1

    while parser_chars and parser_chars[0] == " ":
        parser_chars.pop(0)
        source_spans.pop(0)
    while parser_chars and parser_chars[-1] == " ":
        parser_chars.pop()
        source_spans.pop()
    return PreparedParseText(
        surface=surface,
        parser="".join(parser_chars),
        parser_char_spans=tuple(source_spans),
    )


def normalize_parse_text(text: str) -> str:
    """Compatibility wrapper for callers that only need the parser view."""
    return prepare_parse_text(text).parser

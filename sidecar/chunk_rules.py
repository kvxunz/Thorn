"""Small dependency-free lexical rules used by the structure sidecar."""


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

# Subordinators that often attach under a lower V-ing while sitting to its left
# ("when juries began holding…") — must not nest under the V-ing chunk text.
LEFT_EDGE_INTRODUCERS = frozenset({
    "when", "where", "while", "why", "how", "if", "although", "though",
    "because", "unless", "until", "before", "after", "whether",
})


def is_left_edge_introducer(token, subtree_root):
    """Whether token is a left-edge when/if… wrongly inside a lower xcomp head."""
    if token is subtree_root:
        return False
    if getattr(token, "i", 0) >= getattr(subtree_root, "i", 0):
        return False
    lower = getattr(token, "lower_", getattr(token, "text", "")).lower()
    if lower not in LEFT_EDGE_INTRODUCERS:
        return False
    if getattr(token, "dep_", "") not in ("advmod", "mark"):
        return False
    # Only strip from *lower* hosts that attract upper-clause introducers:
    # non-finite complements, and coordinated verbs ("where they met and
    # married" hangs the first "where" on "married"). Keep if/when on
    # advcl/relcl finite clauses so "if the doormat failed…" owns its "if".
    return getattr(subtree_root, "dep_", "") in (
        "xcomp", "ccomp", "pcomp", "acl", "conj",
    )


def constituent_token_indices(root):
    """Ordered token indices a chunk rooted at ``root`` truly owns.

    The subtree, minus stranded left-edge introducers: a when/where/if that
    hangs on this root but sits detached from the root's contiguous span
    belongs to the clause above (spaCy misattachment). An introducer directly
    adjacent to the remainder is genuine and stays. Discontinuous coordinated
    constituents otherwise get spliced once per contiguous run — duplicating
    the whole clause (the "met and married and where I was born" bug).
    """
    raw = sorted(root.subtree, key=lambda t: t.i)
    if getattr(root, "dep_", "") not in ("xcomp", "ccomp", "pcomp", "acl", "conj"):
        return [t.i for t in raw]
    kept = [t for t in raw if not is_left_edge_introducer(t, root)]
    stripped = [t for t in raw if t not in kept]
    while stripped and kept and stripped[-1].i == kept[0].i - 1:
        kept.insert(0, stripped.pop())
    return [t.i for t in kept] if kept else [t.i for t in raw]


def is_left_edge_introducer_token(token):
    """Token-level check without a subtree root (for promotion)."""
    lower = getattr(token, "lower_", getattr(token, "text", "")).lower()
    return (
        lower in LEFT_EDGE_INTRODUCERS
        and getattr(token, "dep_", "") in ("advmod", "mark")
    )


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

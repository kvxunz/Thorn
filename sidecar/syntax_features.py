from chunk_rules import has_own_subject, is_clausal_pcomp, is_concessive_however_clause

CLAUSE_ROLES = {
    "relcl": "clause-relative",
    "acl": "clause-relative",
    "advcl": "clause-adverbial",
    "ccomp": "clause-noun",
    "csubj": "clause-noun",
    "csubjpass": "clause-noun",
    "xcomp": "complement",  # non-finite: treat as complement, not clause
}


def clause_role_for(head):
    signals = [
        (token.text, token.dep_, token.pos_, token.head.pos_, token.tag_)
        for token in head.subtree
    ]
    if is_concessive_however_clause(head.dep_, signals):
        return "clause-adverbial"

    role = CLAUSE_ROLES.get(head.dep_, "clause-relative")
    if role == "clause-relative" and any(
            token.dep_ == "mark" and token.lower_ == "that"
            for token in head.children):
        return "clause-noun"
    return role


COMPLEMENT_DEPS = frozenset({
    "attr", "acomp", "dobj", "obj", "iobj", "dative", "oprd", "xcomp", "ccomp",
})


def parent_contains_if_any(head, token):
    """Guard so promotion never reaches outside the current head's projection."""
    return token.i in {t.i for t in head.subtree}


def contains_clause(tok):
    return any(
        t.dep_ in ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")
        or is_clausal_pcomp(t)
        for t in tok.subtree if t is not tok)


def is_clause_appositive_npadvmod(token):
    """A comma-set-off, determined NP hung on the predicate as ``npadvmod``.

    "…our limited vocabulary for corporate crime, a fact that corresponds to
    …" — the NP comments on the whole preceding clause, but spaCy has no
    clausal antecedent to attach an ``appos`` to and falls back on
    ``npadvmod``, which Thorn reads as 状语. A genuine adverbial NP ("three
    years later", "yesterday") carries no determiner; requiring one, plus the
    comma, keeps those out.
    """
    if token.dep_ != "npadvmod" or token.pos_ not in ("NOUN", "PROPN"):
        return False
    if not any(child.dep_ == "det" for child in token.children):
        return False
    left = min(t.i for t in token.subtree)
    return left > 0 and token.doc[left - 1].text in {",", *DASH_TOKENS}


def is_complex_connective(token):
    """An adverb that exists only to head a subordinate clause.

    "As long as nations cannot …, they must depend on allies": spaCy makes
    ``long`` an advmod of the matrix verb and hangs the entire subordinate
    clause beneath it as ``advcl``. Treated as a plain adverb the card never
    expands and the learner gets one sixteen-token 状语 with no
    connector/subject/predicate split. Same shape for "as soon as", "so long
    as", "now that", "much as".
    """
    return any(
        child.dep_ == "advcl"
        and child.pos_ in ("VERB", "AUX")
        and has_own_subject(child)
        and any(m.dep_ == "mark" for m in child.children)
        for child in token.children
    )


DASH_TOKENS = frozenset({"—", "–", "--"})


OPEN_BRACKETS = frozenset({"(", "[", "（"})


CLOSE_BRACKETS = frozenset({")", "]", "）"})


def has_bracketed_aside(token):
    """Whether a phrase encloses a parenthesis that deserves its own card."""
    return any(t.text in OPEN_BRACKETS for t in token.subtree)


def closing_bracket(doc, start, hi):
    """Index of the bracket closing the one at ``start``, or None if unclosed.

    An unclosed bracket is left alone: half a parenthesis is not an aside, and
    a card running to the end of the frame on the strength of one stray "("
    would be a worse reading than the one it replaced.
    """
    depth = 0
    for index in range(start, hi + 1):
        text = doc[index].text
        if text in OPEN_BRACKETS:
            depth += 1
        elif text in CLOSE_BRACKETS:
            depth -= 1
            if depth == 0:
                return index
    return None


def has_appositive_enumeration(noun):
    """Whether a nominal heads a two-plus appositive list.

    ``a cacophony of coughs, rattles, wheezes, croaks`` — the members hang off
    the phrase as ``appos`` (and any ``conj`` coordinated onto one). With two or
    more, the card should expand so np_expand can collapse the list into one
    revealable block rather than one flat mega-card. Punctuation (colon,
    semicolon, comma) is irrelevant; the dependency label marks the enumeration.
    This must count members the same way np_expand does, or the expand gate and
    the splitter disagree (parsers waver between appos and conj for the tail).
    """
    members = {t.i for t in noun.subtree if t.dep_ == "appos"}
    changed = True
    while changed:
        changed = False
        for t in noun.subtree:
            if t.dep_ == "conj" and t.head.i in members and t.i not in members:
                members.add(t.i)
                changed = True
    return len(members) >= 2


FENCE_ADVERB_DEPS = frozenset({"neg", "advmod"})


SUPPLEMENT_PUNCT = frozenset({":", ";"})


def has_supplement_punctuation(token):
    """Whether a phrase holds a colon with material on both sides of it."""
    indices = [t.i for t in token.subtree]
    lo, hi = min(indices), max(indices)
    return any(
        lo < t.i < hi and t.text in SUPPLEMENT_PUNCT for t in token.subtree
    )


def appositive_fence(doc, left):
    """Index of the punctuation fencing off an appositive starting at ``left``.

    None when the renaming is bare — "the poet Milton", "my friend Sam" is one
    phrase and splitting it would be wrong, which is what the older
    two-or-more rule was really protecting. A dash fences as firmly as a comma:
    "a paradox — an endless conflict between the desire to conform" names the
    same thing twice and reads as two slots.
    """
    while left > 0 and doc[left - 1].dep_ in FENCE_ADVERB_DEPS:
        left -= 1
    return (
        left - 1
        if left > 0 and doc[left - 1].text in {",", *DASH_TOKENS}
        else None
    )


def has_comma_fenced_appositive(noun):
    """Whether a nominal carries a single appositive set off by a comma.

    "Lloyd Nickson, a 54-year-old Darwin resident", "a triumph for yet another
    scientific idea, a refinement of the Big Bang" — one appositive, so
    `has_appositive_enumeration` (which wants a list) leaves the card flat and
    the second naming is taught as more of the first.
    """
    return any(
        t.dep_ == "appos"
        and appositive_fence(noun.doc, min(x.i for x in t.subtree)) is not None
        for t in noun.subtree
    )


def has_comma_supplement(token):
    """Whether a fence sits after the head with material still to come.

    "lifelong cognitive disability, including deficits in learning and memory",
    "the result of several modifications, for instance by Bernhard Severin
    Ingemann" — the phrase is complete before the comma, so what follows it is
    supplementary and belongs on its own card. See `split_comma_supplement`,
    which draws the split this gate opens the door to.
    """
    indices = [t.i for t in token.subtree]
    return any(
        token.i < t.i < max(indices) and t.text in {",", *DASH_TOKENS}
        for t in token.subtree
    )


def has_fenced_supplement(token):
    """Whether a phrase fences off supplementary material inside itself.

    The four fences a slot can raise around a supplement -- bracket, comma
    before an appositive, colon/semicolon, comma with the phrase already
    complete. They are asked together everywhere, so they are named together
    here: a fifth kind of fence is one clause in one place, not an edit to
    every slot that can hold one.
    """
    return (has_bracketed_aside(token)
            or has_comma_fenced_appositive(token)
            or has_supplement_punctuation(token)
            or has_comma_supplement(token))


def prep_object_enumeration(prep):
    """Whether a prep's object carries an appositive list (see above)."""
    pobj = next((c for c in prep.children if c.dep_ == "pobj"), None)
    return pobj is not None and has_appositive_enumeration(pobj)


ADVERBIAL_PREP_HEADS = frozenset({
    "because", "despite", "notwithstanding", "regardless",
    "instead", "unlike", "besides", "barring",
})


def is_adverbial_complex_prep(prep):
    """Whether a prep phrase functions as a sentence-level adverbial."""
    if prep.dep_ not in ("prep", "agent"):
        return False
    if getattr(prep.head, "pos_", "") not in ("VERB", "AUX"):
        return False  # attached to a noun -> a real postmodifying 介词短语
    if prep.pos_ == "SCONJ" or prep.lower_ in ADVERBIAL_PREP_HEADS:
        return True
    # "instead of leaving": spaCy makes "of" the prep and hangs the marker
    # ("instead") on it as an advmod. The leading adverb still flags an adjunct.
    return any(
        child.dep_ in ("advmod", "npadvmod") and child.lower_ in ADVERBIAL_PREP_HEADS
        for child in prep.children
    )


CLAUSE_DEPS = ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")


WH_TAGS = ("WDT", "WP", "WP$")


def has_relative_introducer(root):
    return any(
        token.tag_ in WH_TAGS or token.tag_ == "WRB"
        for token in root.children
    )

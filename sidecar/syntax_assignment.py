"""Which card owns which token, before any card is written.

``analyze_clause`` used to do this inline, and the reading order hid what the
work actually is: a fixed sequence of passes over one ``assign`` map, each one
claiming tokens the pass before it left alone. The order is the contract --
a later pass only ever fills gaps, and the last of them hands every remaining
token to a neighbour so the cards tile the span. Each pass is named here for
the construction it exists to rescue.
"""
from __future__ import annotations

from chunk_rules import has_own_subject, verb_group_indices
from constituency import TokenSpan
from syntax_boundaries import (
    _projection,
    absorb_misattached_roots_into_clauses,
    blocked_indices_for_root,
    boundary_anchors,
    owned_dependency_indices,
)
from syntax_decomposition import plan_roots
from syntax_features import (
    OPEN_BRACKETS,
    clause_role_for,
    closing_bracket,
    contains_clause,
)


def assign_tokens(head, doc, structure, constituency, parent_span, clause_role_of_head):
    """Map every token of ``parent_span`` to the card root that owns it.

    Returns ``(assign, root_entries, inline)``: the token map, the
    ``key -> (token, role, decompose, span)`` table the card writer reads, and
    the keys that must splice their contents in rather than wrap them.
    """
    assign, root_entries, inline, root_specs = _resolve_roots(
        head, doc, structure, constituency, parent_span,
    )
    _promote_stranded_adverbs(
        root_specs, root_entries, assign, constituency, parent_span,
    )
    _promote_orphan_clauses(root_entries, assign, doc, constituency, parent_span)
    _promote_stray_prepositions(
        root_entries, assign, doc, constituency, parent_span,
    )
    _promote_wh_introducers(
        root_entries, assign, doc, constituency, parent_span, clause_role_of_head,
    )
    _claim_brackets(root_entries, assign, doc, parent_span)
    _extend_multiword_subordinators(root_entries, assign, head, doc, parent_span)
    _fill_leftovers(root_entries, assign, doc, parent_span)
    return assign, root_entries, inline


def _tokens_of(doc, parent_span):
    return [doc[index] for index in range(parent_span.start, parent_span.end)]


def _resolve_roots(head, doc, structure, constituency, parent_span):
    """Seed the verbal complex, then give each planned root its Benepar span."""
    assign = {}
    for t_i in verb_group_indices(head):
        if parent_span.contains(t_i):
            assign[t_i] = "verb"

    root_entries = {"verb": None}
    inline = set()
    root_specs = []
    seen_roots = set()
    for c, role, decompose in plan_roots(structure.roots(head.i), doc):
        if not parent_span.contains(c.i) or c.i in seen_roots:
            continue
        seen_roots.add(c.i)
        root_specs.append((c, role, decompose))
    root_specs, absorbed_by_clause = absorb_misattached_roots_into_clauses(
        root_specs,
        head,
        constituency,
        parent_span,
    )

    # Constituency candidates may not reclaim any token already reserved for
    # the finite verbal complex (e.g. ``is not [that …]``). Sibling clause
    # roots block with their full dependency projection so a wide Benepar SBAR
    # cannot keep a promoted independent conjunct inside a ccomp.
    for c, role, decompose in root_specs:
        key = f"n{c.i}"
        if role == "__coord_clause__":
            inline.add(key)
        owned_span = constituency.resolve(
            root=c.i,
            role=role,
            parent=parent_span,
            required=(
                boundary_anchors(c, decompose, parent_span)
                | absorbed_by_clause.get(c.i, set())
            ),
            blocked=blocked_indices_for_root(c, head, root_specs, parent_span),
            dependency_indices=owned_dependency_indices(c, parent_span, root_specs),
        )
        root_entries[key] = (c, role, decompose, owned_span)
        for t_i in range(owned_span.start, owned_span.end):
            if t_i not in assign:
                assign[t_i] = key
    return assign, root_entries, inline, root_specs


def _promote_stranded_adverbs(root_specs, root_entries, assign, constituency, parent_span):
    # Degree/downtoning adverbs stranded between a copula and its predicative
    # complement ("is hardly worth …") hang on the acomp adjective in the
    # dependency parse, yet Benepar leaves them *outside* the complement's
    # ADJP. Left alone they fall to the leftover pass and glue onto the verb
    # ("is hardly"). When the complement's own span excludes such an adverb,
    # promote it to its own adverbial card so the copula stays bare — matching
    # how a lone "was" is shown for a complement with no stranded modifier.
    for c, role, _expand in root_specs:
        if c.dep_ not in ("acomp", "attr", "oprd"):
            continue
        comp_span = root_entries[f"n{c.i}"][3]
        for g in c.children:
            if (
                g.dep_ in ("advmod", "npadvmod")
                and g.i < c.i
                and parent_span.contains(g.i)
                and not comp_span.contains(g.i)
                and g.i not in assign
            ):
                adv_span = constituency.resolve(
                    root=g.i,
                    role="adverbial",
                    parent=parent_span,
                    dependency_indices=sorted(t.i for t in g.subtree),
                )
                if adv_span.contains(c.i):  # never swallow the complement head
                    adv_span = TokenSpan(g.i, g.i + 1)
                key = f"adv{g.i}"
                root_entries[key] = (g, "adverbial", False, adv_span)
                for t_i in range(adv_span.start, adv_span.end):
                    if t_i not in assign:
                        assign[t_i] = key


def _promote_orphan_clauses(root_entries, assign, doc, constituency, parent_span):
    # An extraposed clause — a relative separated from the noun it modifies
    # ("sent a spy to his house, who heard …") — is nobody's dependency child
    # at this level, and the noun's own Benepar NP stops before it, so no root
    # claims a single one of its tokens. The leftover pass below would then
    # glue the whole finite clause onto whichever card sits to its left, and
    # it gets taught as part of that card's phrase. Give it its own root.
    # Requiring a subject of its own keeps stranded participles out: those are
    # genuinely modifiers, and promoting them is a separate question. The
    # dependency label is deliberately not consulted: "chances were that no
    # other surgeon could have either" has spaCy read `have` as an *aux* of
    # the adverb `either`, so the that-clause carries no clausal label at all
    # and used to be welded onto the predicate card ("were that no other
    # surgeon could have"). A verbal with its own subject that nothing else
    # claimed is a clause whatever the parser called it.
    for t in _tokens_of(doc, parent_span):
        if (
            t.i in assign
            or t.pos_ not in ("VERB", "AUX")
            or not has_own_subject(t)
        ):
            continue
        orphan_role = clause_role_for(t)
        orphan_span = constituency.resolve(
            root=t.i,
            role=orphan_role,
            parent=parent_span,
            blocked=set(assign),
            dependency_indices=_projection(t, parent_span),
        )
        key = f"orphan{t.i}"
        root_entries[key] = (t, orphan_role, True, orphan_span)
        for t_i in range(orphan_span.start, orphan_span.end):
            if t_i not in assign:
                assign[t_i] = key


def _promote_stray_prepositions(root_entries, assign, doc, constituency, parent_span):
    # Same shape one level down: a preposition governed from *outside* this
    # clause but sitting inside it. "as perhaps Kelsey will after her
    # resignation …" — spaCy hangs both `after` phrases on the matrix verb
    # `discovered`, so the elided VP `will` has no child to claim them and the
    # leftover pass welds eleven tokens onto the predicate card. A verb card
    # that reads as the whole rest of the clause is the worst thing this
    # pipeline can show: the highlight paints the lot in the predicate colour.
    for t in _tokens_of(doc, parent_span):
        if t.i in assign or t.dep_ not in ("prep", "agent"):
            continue
        stray_span = constituency.resolve(
            root=t.i,
            role="prep-phrase",
            parent=parent_span,
            blocked=set(assign),
            dependency_indices=_projection(t, parent_span),
        )
        key = f"stray{t.i}"
        root_entries[key] = (t, "prep-phrase", contains_clause(t), stray_span)
        for t_i in range(stray_span.start, stray_span.end):
            if t_i not in assign:
                assign[t_i] = key


def _promote_wh_introducers(
    root_entries, assign, doc, constituency, parent_span, clause_role_of_head,
):
    # A WH constituent at the current SBAR edge belongs to this clause even
    # when the dependency parser parked it on a lower xcomp/conj. This is the
    # only promotion path: lexical when/where lists are intentionally gone.
    for t in _tokens_of(doc, parent_span):
        if t.i in assign:
            continue
        wh_span = constituency.leading_wh_span(t.i, parent_span)
        if wh_span is None:
            continue
        key = f"intro{t.i}"
        intro_role = (
            "relative" if clause_role_of_head == "clause-relative" else "conjunction"
        )
        root_entries[key] = (t, intro_role, False, wh_span)
        for t_i in range(wh_span.start, wh_span.end):
            if t_i not in assign:
                assign[t_i] = key


def _claim_brackets(root_entries, assign, doc, parent_span):
    # A parenthesis is one aside, and the constituency spans routinely stop in
    # the middle of it: "Going Down Swinging (2000)" resolved a span ending on
    # the open bracket and the learner got a card reading "Swinging (". Claim
    # the whole run for one insertion card of its own.
    #
    # Only when nothing straddles it. A holder with tokens on *both* sides
    # would be left with two runs sharing one key, and an expandable one would
    # then recurse twice over the same span and emit the same words under two
    # siblings — an overlap the contract rejects outright. Where the run only
    # hangs off the tail of its holders, narrowing their spans is enough.
    lo, hi = parent_span.start, parent_span.end - 1
    bracketed = set()
    for t in _tokens_of(doc, parent_span):
        if t.text not in OPEN_BRACKETS or t.i in bracketed:
            continue
        close = closing_bracket(doc, t.i, hi)
        if close is None or (t.i == lo and close == hi):
            continue
        holders = {assign[i] for i in range(t.i, close + 1) if i in assign}
        entries = [root_entries.get(holder) for holder in holders]
        if any(
            entry is not None and entry[3].start <= t.i and close < entry[3].end
            for entry in entries
        ):
            # One card owns the aside outright, so its own recursion splits it
            # where it belongs — inside the phrase, not hoisted up here. Pulling
            # "(such as F. Scott Fitzgerald)" out to the sentence backbone would
            # cut the subject away from the material it qualifies.
            continue
        if any(assign.get(i) in holders for i in range(close + 1, hi + 1)):
            continue
        for holder in holders:
            entry = root_entries.get(holder)
            if entry is None or entry[3].start >= t.i:
                continue
            root_entries[holder] = (
                *entry[:3],
                TokenSpan(entry[3].start, t.i, entry[3].labels),
            )
        key = f"aside{t.i}"
        span = TokenSpan(t.i, close + 1, frozenset())
        root_entries[key] = (t, "insertion", False, span)
        for t_i in range(t.i, close + 1):
            assign[t_i] = key
            bracketed.add(t_i)


def _extend_multiword_subordinators(root_entries, assign, head, doc, parent_span):
    # A multi-word subordinator ("as long as", "as soon as", "now that") is one
    # connective, but spaCy splits it: the final `as`/`that` is this clause's
    # mark while the adverbs before it govern the clause from outside. Inside
    # this frame those adverbs are nobody's dependent, and the leftover pass
    # below deliberately refuses to hand anything to a conjunction — so it
    # reaches *across* the mark and the learner gets "As long" glued to the
    # subject on the far side. Give them to the mark they belong to.
    lo = parent_span.start
    head_ancestors = {a.i for a in head.ancestors}
    for key, entry in list(root_entries.items()):
        if entry is None or entry[1] != "conjunction" or entry[0].dep_ != "mark":
            continue
        index = entry[3].start - 1
        while (
            index >= lo
            and index not in assign
            and doc[index].pos_ == "ADV"
            and (index in head_ancestors or doc[index].head.i in head_ancestors)
        ):
            assign[index] = key
            index -= 1


def _fill_leftovers(root_entries, assign, doc, parent_span):
    # leftovers (punctuation, stray dets) -> nearest assigned neighbor.
    # Prefer the *adjacent* non-conjunction key (right if left is a pure
    # conjunction). Never jump over an assigned conjunction to a distant
    # earlier card — that created orphan fragments like a lone "then"
    # between "and" and "by…".
    lo, hi = parent_span.start, parent_span.end - 1

    def _role_of(key):
        entry = root_entries.get(key)
        return entry[1] if entry is not None else None

    def _pick_side(start, step, limit):
        i = start
        conj_fallback = None
        while lo <= i <= hi and ((step < 0 and i >= limit) or (step > 0 and i <= limit)):
            if i in assign:
                key = assign[i]
                if _role_of(key) == "conjunction":
                    if conj_fallback is None:
                        conj_fallback = key
                    i += step
                    continue
                return key
            i += step
        return conj_fallback

    for t in _tokens_of(doc, parent_span):
        if t.i in assign:
            continue
        left = _pick_side(t.i - 1, -1, lo)
        right = _pick_side(t.i + 1, 1, hi)
        if left is not None and _role_of(left) != "conjunction":
            # Adjacent left is real content only if no other key sits on i-1
            # as conjunction; if left scan crossed a conj, prefer right.
            if t.i - 1 in assign and _role_of(assign[t.i - 1]) == "conjunction" and right is not None:
                chosen = right
            else:
                chosen = left
        elif right is not None:
            chosen = right
        else:
            chosen = left if left is not None else "verb"
        assign[t.i] = chosen

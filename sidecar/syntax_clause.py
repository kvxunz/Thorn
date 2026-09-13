from __future__ import annotations

from chunk_rules import (
    has_own_subject,
    is_wh_relative_pronoun,
    mark_discourse_insertions,
    merge_or_so,
    merge_split_words,
    merge_tiny,
    relative_pronoun_gloss,
    verb_group_indices,
)
from constituency import ConstituencyIndex, TokenSpan
from syntax_boundaries import (
    _projection,
    absorb_misattached_roots_into_clauses,
    blocked_indices_for_root,
    boundary_anchors,
    owned_dependency_indices,
)
from syntax_decomposition import (
    has_complete_embedded_relative,
    plan_roots,
    preposition_role,
)
from syntax_features import (
    OPEN_BRACKETS,
    WH_TAGS,
    clause_role_for,
    closing_bracket,
    contains_clause,
)
from syntax_grouping import (
    coordinated_gerund_subject_children,
    group_colon_enumerations,
    group_constituency_clauses,
    group_explanatory_for_clause,
    merge_idioms,
)
from syntax_nominal import analyze_nominal, split_prep_core
from syntax_structure import SyntaxStructure


def analyze_clause(
    head,
    doc,
    clause_role_of_head=None,
    constituency=None,
    parent_span=None,
):
    """Partition the subtree of `head` (a verbal head) into ordered chunks.
    Every token is assigned to exactly one chunk root; chunks are contiguous
    runs of each assignment -> full coverage, and discontinuous constituents
    naturally become multiple chunks."""
    def _analyze_nominal(*args, **kwargs):
        return analyze_nominal(*args, **kwargs, analyze_clause=analyze_clause)

    if constituency is None:
        constituency = ConstituencyIndex.from_doc(doc)
    if parent_span is None:
        owned = sorted(token.i for token in head.subtree)
        parent_span = TokenSpan(owned[0], owned[-1] + 1)
    structure = constituency.structure
    if structure is None:
        structure = SyntaxStructure(doc, constituency.relations)
        constituency.structure = structure
    if not parent_span.contains(head.i):
        raise ValueError("dependency head is outside its Benepar parent span")

    subtree = [doc[index] for index in range(parent_span.start, parent_span.end)]
    lo, hi = parent_span.start, parent_span.end - 1
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
    for t in subtree:
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

    # Same shape one level down: a preposition governed from *outside* this
    # clause but sitting inside it. "as perhaps Kelsey will after her
    # resignation …" — spaCy hangs both `after` phrases on the matrix verb
    # `discovered`, so the elided VP `will` has no child to claim them and the
    # leftover pass welds eleven tokens onto the predicate card. A verb card
    # that reads as the whole rest of the clause is the worst thing this
    # pipeline can show: the highlight paints the lot in the predicate colour.
    for t in subtree:
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

    # A WH constituent at the current SBAR edge belongs to this clause even
    # when the dependency parser parked it on a lower xcomp/conj. This is the
    # only promotion path: lexical when/where lists are intentionally gone.
    for t in subtree:
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
    bracketed = set()
    for t in subtree:
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

    # A multi-word subordinator ("as long as", "as soon as", "now that") is one
    # connective, but spaCy splits it: the final `as`/`that` is this clause's
    # mark while the adverbs before it govern the clause from outside. Inside
    # this frame those adverbs are nobody's dependent, and the leftover pass
    # below deliberately refuses to hand anything to a conjunction — so it
    # reaches *across* the mark and the learner gets "As long" glued to the
    # subject on the far side. Give them to the mark they belong to.
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

    # leftovers (punctuation, stray dets) -> nearest assigned neighbor.
    # Prefer the *adjacent* non-conjunction key (right if left is a pure
    # conjunction). Never jump over an assigned conjunction to a distant
    # earlier card — that created orphan fragments like a lone "then"
    # between "and" and "by…".
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

    for t in subtree:
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

    chunks = []
    run_key, run = None, []

    def flush():
        nonlocal run, run_key
        if not run:
            return
        run_local = list(run)
        key = run_key
        run, run_key = [], None
        before = len(chunks)
        emit(doc[run_local[0]: run_local[-1] + 1].text,
             [doc[i] for i in run_local], key, run_local)
        # Exact token bounds ride along internally: coordinate-clause grouping
        # rebuilds wrapper texts from doc spans. Stripped before the response.
        for ch in chunks[before:]:
            ch.setdefault("_lo", run_local[0])
            ch.setdefault("_hi", run_local[-1])

    def emit(text, toks, key, run_local):
        def splice_flat(sub, owned_span):
            """Extend with a constituent's own chunks, then glue back any run
            tokens the constituent doesn't own — a colon the leftover pass
            parked on this run would otherwise vanish with the run text."""
            start_index = len(chunks)
            chunks.extend(sub)
            if not sub:
                return
            suffix = [i for i in run_local if i >= owned_span.end]
            if suffix:
                last_owned = owned_span.end - 1
                char_from = doc[last_owned].idx + len(doc[last_owned].text)
                char_to = doc[suffix[-1]].idx + len(doc[suffix[-1]].text)
                chunks[-1]["text"] += doc.text[char_from:char_to]
                if "_hi" in chunks[-1]:
                    chunks[-1]["_hi"] = suffix[-1]
            prefix = [i for i in run_local if i < owned_span.start]
            if prefix:
                first = chunks[start_index]
                char_to = doc[owned_span.start].idx
                first["text"] = doc.text[doc[prefix[0]].idx: char_to] + first["text"]
                if "_lo" in first:
                    first["_lo"] = prefix[0]

        if key == "verb":
            chunks.append({"text": text, "role": "verb", "gloss": "",
                           "children": None, "_lem": head.lemma_})
            return
        c, role, decompose, owned_span = root_entries[key]
        meaningful_extensions = [
            index for index in run_local
            if not owned_span.contains(index)
            and any(character.isalnum() for character in doc[index].text)
        ]
        recursive_span = owned_span
        if meaningful_extensions:
            recursive_span = TokenSpan(
                min(owned_span.start, meaningful_extensions[0]),
                max(owned_span.end - 1, meaningful_extensions[-1]) + 1,
                owned_span.labels,
            )
        if not decompose and c.pos_ not in ("VERB", "AUX") and constituency.relations is not None:
            decompose = has_complete_embedded_relative(
                constituency.relations, c.i, recursive_span.start, recursive_span.end,
            )
        if key in inline:
            # Coordinate clause. With its own subject it is a full clause:
            # inside a labeled clause it reads best as one collapsible block
            # ("and where I was born"); subject-sharing VP coordination
            # ("and married") splices flat. Top level always splices flat so
            # the header keeps per-role colors on the whole backbone.
            sub = analyze_clause(
                c,
                doc,
                constituency=constituency,
                parent_span=recursive_span,
            )
            own_subject = any(
                t.dep_ in ("nsubj", "nsubjpass", "expl") for t in c.children
            )
            if clause_role_of_head is not None and own_subject and len(sub) >= 2:
                chunks.append({"text": text, "role": clause_role_of_head,
                               "gloss": "", "children": sub})
            else:
                splice_flat(sub, recursive_span)
            return
        # single introducing word inside a clause gets its true role:
        # wh-pronouns/adverbs -> relative (in relative clauses) or conjunction;
        # bare subordinators (when/if/because via "mark") -> conjunction.
        # For relatives the dependency tree already knows the referent
        # (the noun the clause hangs on), so the gloss is deterministic.
        referent_head = head
        while (
            referent_head.dep_ == "conj"
            and referent_head.head is not referent_head
        ):
            referent_head = referent_head.head
        referent = (
            referent_head.head.text
            if clause_role_of_head == "clause-relative" else None
        )
        if len(run_local) == 1 and clause_role_of_head is not None:
            tok = toks[0]
            if is_wh_relative_pronoun(tok) or tok.tag_ in WH_TAGS or tok.tag_ == "WRB":
                # A WH word is a relation marker only inside a relative
                # clause. In adverbial/noun clauses it introduces that clause
                # ("When juries…", "how well it works") and must not be
                # mislabeled merely because its dependency is an argument.
                if (
                    clause_role_of_head == "clause-relative"
                    and tok.dep_ != "mark"
                ):
                    gloss = relative_pronoun_gloss(referent, tok.dep_)
                    chunks.append({"text": text, "role": "relative", "gloss": gloss, "children": None})
                else:
                    chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
                return
            if tok.dep_ == "mark":
                chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
                return
        if (clause_role_of_head is not None or not any(token.text == "?" for token in subtree)) and len(run_local) == 1 and (
            toks[0].tag_ in WH_TAGS or is_wh_relative_pronoun(toks[0])
        ):
            tok = toks[0]
            if clause_role_of_head == "clause-relative":
                gloss = relative_pronoun_gloss(referent, tok.dep_)
                chunks.append({"text": text, "role": "relative", "gloss": gloss, "children": None})
            else:
                chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
            return
        if role is None:
            # A leftover with no slot of its own is still teachable when it
            # holds a colon or a fence. This short-circuit ran before the
            # `decompose` dispatch below, so "living without the haunting fear of
            # his suffering: a terrifying death from his breathing condition"
            # reached the learner as one unlabelled line of fifteen tokens no
            # matter what the gates decided about it.
            parts = _analyze_nominal(
                c, doc, "other", constituency, recursive_span,
            ) if decompose else []
            if len(parts) >= 2:
                splice_flat(parts, recursive_span)
            else:
                chunks.append({"text": text, "role": "other", "gloss": "",
                               "children": None})
        elif (
            role == "clause-noun"
            and c.dep_ in ("csubj", "csubjpass")
            and (gerund_children := coordinated_gerund_subject_children(
                c,
                doc,
                constituency,
                recursive_span,
            )) is not None
        ):
            # spaCy occasionally reads the noun ``move`` as a verb in
            # ``abandoning X and making the alternative move``. Benepar still
            # exposes the coordinated VPs, so present the whole construction
            # as one subject instead of fabricating a nested finite clause.
            chunks.append({
                "text": text,
                "role": "subject",
                "gloss": "",
                "children": gerund_children,
            })
        elif role == "clause-noun" and c.dep_ in ("csubj", "csubjpass"):
            # Subject clauses must stay one wrapped block ("How well… depends").
            kids = analyze_clause(
                c,
                doc,
                clause_role_of_head="clause-noun",
                constituency=constituency,
                parent_span=recursive_span,
            )
            chunks.append({"text": text, "role": "clause-noun", "gloss": "",
                           "children": kids if len(kids) >= 2 else None})
        elif (role == "clause-noun"
              and c.dep_ not in ("csubj", "csubjpass")
              and not any(t.dep_ == "mark" and t.lower_ in
                          ("that", "whether", "if", "what", "whatever", "how", "why", "who")
                          for t in c.children)
              and not any(
                  t.dep_ in ("advmod", "npadvmod") and t.tag_ in WH_TAGS + ("WRB",)
                  for t in c.children
              )
              and not (chunks and chunks[-1]["role"] == "verb")):
            # A "noun clause" with no real subordinator that does NOT follow
            # its governing verb is almost always a misattached coordinate
            # main clause ("..., for, ..."): splice its backbone in flat.
            # Right after a verb it's a bare object clause ("He said he would
            # come") and keeps its clause identity.
            # WH-adjunct subject clauses ("How well…") keep their wrapper.
            splice_flat(analyze_clause(
                c,
                doc,
                clause_role_of_head=clause_role_of_head,
                constituency=constituency,
                parent_span=recursive_span,
            ), recursive_span)
        elif role == "object" and not decompose:
            chunks.append({"text": text, "role": role, "gloss": "",
                           "children": None, "_lem": c.lemma_})
        elif decompose:
            if c.pos_ in ("VERB", "AUX") or role == "absolute":
                # verbal heads recurse fully, wrapped under their clause label;
                # an absolute's adjectival head works the same way — its "verb"
                # run is the elided-be predicate ("dead and gone").
                kids = analyze_clause(
                    c,
                    doc,
                    clause_role_of_head=role if role.startswith("clause") else None,
                    constituency=constituency,
                    parent_span=recursive_span,
                )
                chunks.append({"text": text, "role": role, "gloss": "",
                               "children": kids if len(kids) >= 2 else None})
            elif role.startswith("clause"):
                # Non-verbal clause head with an internal finite verb
                # (preposed-adj path already rewrites to the verb; keep safe).
                verbal = next(
                    (t for t in c.subtree
                     if t is not c and t.pos_ in ("VERB", "AUX")
                     and t.dep_ in ("advcl", "xcomp", "ccomp", "ROOT")),
                    None,
                )
                if verbal is not None:
                    kids = analyze_clause(
                        verbal,
                        doc,
                        clause_role_of_head=role,
                        constituency=constituency,
                        parent_span=recursive_span,
                    )
                    chunks.append({"text": text, "role": role, "gloss": "",
                                   "children": kids if len(kids) >= 2 else None})
                else:
                    chunks.append({"text": text, "role": role, "gloss": "",
                                   "children": None})
            elif role == "subject" or (
                role in ("complement", "object", "adverbial") and c.pos_ in ("NOUN", "PROPN", "PRON")
            ):
                # Keep a single subject card; nested clauses/appos become children
                # via analyze_nominal but re-wrapped so the subject label is not lost.
                sub = _analyze_nominal(
                    c, doc, role, constituency, recursive_span,
                )
                if len(sub) == 1:
                    # One card back, but it carries analyze_nominal's bounds, not the
                    # run's. Any run token analyze_nominal did not claim -- the comma
                    # fencing an appositive it declined to split -- would then
                    # belong to no node at all and the coverage invariant would
                    # fail the whole sentence. Give the card the run back.
                    only = sub[0]
                    only["text"] = text
                    only["_lo"], only["_hi"] = run_local[0], run_local[-1]
                    chunks.append(only)
                else:
                    chunks.append({
                        "text": text, "role": role, "gloss": "",
                        "children": sub if len(sub) >= 2 else None,
                    })
            elif role == "insertion":
                kids = None
                if c.pos_ in ("NOUN", "PROPN", "PRON"):
                    # A nominal aside carrying a relative clause ("…, a work
                    # that was generally consistent with the prose of the
                    # day, …"). Recursing on the inner verb would frame the
                    # clause only, leaving "a work" to the leftover pass — it
                    # landed inside the relative's subject card as "a work
                    # that". analyze_nominal keeps the noun and the clause apart.
                    sub = _analyze_nominal(c, doc, role, constituency, recursive_span)
                    kids = sub if len(sub) >= 2 else None
                elif c.pos_ in ("VERB", "AUX") or any(
                    t.pos_ in ("VERB", "AUX") for t in c.subtree if t is not c
                ):
                    verbal = c if c.pos_ in ("VERB", "AUX") else next(
                        (t for t in c.subtree if t.pos_ in ("VERB", "AUX")), c
                    )
                    kids = analyze_clause(
                        verbal,
                        doc,
                        clause_role_of_head=None,
                        constituency=constituency,
                        parent_span=recursive_span,
                    )
                chunks.append({
                    "text": text, "role": "insertion", "gloss": "",
                    "children": kids if kids and len(kids) >= 2 else None,
                })
            elif role == "prep-phrase":
                # Keep prep as one card when simple; otherwise splice expanded
                # material so annotate_chunk_spans always sees contiguous text.
                # A complex/subordinating prep modifying the predicate reads as
                # a 状语 ("Because of … he had to flee"); relabel the card while
                # keeping the prep-phrase span geometry for analyze_nominal.
                card_role = preposition_role(c)
                sub = _analyze_nominal(c, doc, role, constituency, recursive_span)
                if not sub:
                    chunks.append({"text": text, "role": card_role, "gloss": "",
                                   "children": None})
                elif len(sub) == 1:
                    # One card back: either a plain prep phrase or a single
                    # collapsed block (e.g. an appositive enumeration) that
                    # already carries its own children — keep them.
                    sub[0]["role"] = card_role
                    splice_flat(sub, recursive_span)
                else:
                    # Prefer a single prep wrapper only when the first sub-card
                    # already carries the preposition text.
                    first = sub[0].get("text", "")
                    if first and text.startswith(first[: max(1, min(12, len(first)))]):
                        kids = split_prep_core(sub, c, doc)
                        chunks.append({
                            "text": text, "role": card_role, "gloss": "",
                            "children": kids if len(kids) >= 2 else None,
                        })
                    else:
                        splice_flat(sub, recursive_span)
            else:
                # nominal head embedding a clause: splice core + clause as
                # siblings — no wrapper level, and the backbone highlight
                # stays on the core noun only
                splice_flat(_analyze_nominal(
                    c,
                    doc,
                    role,
                    constituency,
                    recursive_span,
                ), recursive_span)
        else:
            chunks.append({"text": text, "role": role, "gloss": "", "children": None})

    for t in subtree:
        key = assign[t.i]
        if key != run_key:
            flush()
            run_key = key
        run.append(t.i)
    flush()
    result = mark_discourse_insertions(
        merge_tiny(merge_or_so(merge_idioms(merge_split_words(chunks, doc)))))
    if clause_role_of_head is not None:
        result = group_constituency_clauses(
            result,
            clause_role_of_head,
            doc,
            constituency,
            parent_span,
        )
    result = group_colon_enumerations(result, doc, parent_span)
    if clause_role_of_head is None:
        result = group_explanatory_for_clause(
            result,
            doc,
            constituency,
            parent_span,
        )
    return result

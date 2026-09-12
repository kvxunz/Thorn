from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from chunk_rules import (
    has_own_subject,
    is_clausal_pcomp,
    is_wh_relative_pronoun,
    mark_discourse_insertions,
    merge_or_so,
    merge_split_words,
    merge_tiny,
    prep_object_start,
    relative_pronoun_gloss,
    verb_group_indices,
)
from constituency import CLAUSE_LABELS, ConstituencyIndex, TokenSpan
from syntax_decomposition import (
    has_complete_embedded_relative,
    plan_roots,
    preposition_role,
)
from syntax_features import (
    CLAUSE_DEPS,
    CLOSE_BRACKETS,
    DASH_TOKENS,
    OPEN_BRACKETS,
    SUPPLEMENT_PUNCT,
    WH_TAGS,
    appositive_fence,
    clause_role_for,
    closing_bracket,
    contains_clause,
)
from syntax_structure import SyntaxStructure, collect_embedded_clauses

BOUNDARY_ANCHOR_DEPS = frozenset({
    "nsubj", "nsubjpass", "expl", "dobj", "obj", "iobj", "dative", "oprd",
    "attr", "acomp", "xcomp", "ccomp", "csubj", "csubjpass", "advcl",
    "relcl", "acl", "prep", "agent", "conj",
    # Noun-noun premodifiers ("tweed [and woolen] coats") are part of the NP;
    # without them the resolver settles for the minimal inner NP and strands
    # the modifier as a leftover glued onto the neighbouring predicate.
    "nmod", "compound",
})


def boundary_anchors(root, decompose, parent):
    """Dependency anchors a compatible Benepar span must contain."""
    anchors = {root.i}
    if root.pos_ in ("VERB", "AUX"):
        anchors.update(i for i in verb_group_indices(root) if parent.contains(i))
    anchors.update(
        child.i for child in root.children
        if parent.contains(child.i)
        and child.dep_ in BOUNDARY_ANCHOR_DEPS
        # Independent full-clause conjuncts are promoted to sibling roots; if
        # they remain required anchors here, blocked-token logic cannot cut
        # them out of an overwide ccomp SBAR.
        and not (
            child.dep_ == "conj"
            and child.pos_ in ("VERB", "AUX")
            and has_own_subject(child)
        )
    )
    if decompose:
        # An expandable nominal/PP owns its directly embedded clause even when
        # Benepar also offers a smaller core NP. analyze_nominal separates it later.
        anchors.update(
            token.i for token in root.subtree
            if parent.contains(token.i)
            and token is not root
            and (token.dep_ in CLAUSE_DEPS or is_clausal_pcomp(token))
        )
    return anchors


def dependency_indices(root, parent):
    """Full dependency projection of ``root`` inside ``parent``."""
    return {
        token.i for token in root.subtree
        if parent.contains(token.i)
    }


def _projection(token, parent_span):
    return {
        piece.i for piece in token.subtree if parent_span.contains(piece.i)
    }


def owned_dependency_indices(root, parent_span, root_specs):
    """Dependency projection of ``root`` minus promoted descendant siblings.

    A ccomp head still *dominates* an independent conj in spaCy; after we
    promote that conj to a peer teaching root, the parent's owned tokens must
    stop before the conj's projection.
    """
    own = _projection(root, parent_span)
    for other, _role, _expand in root_specs:
        if other.i == root.i:
            continue
        other_proj = _projection(other, parent_span)
        if other.i in own:
            own -= other_proj
    return own


def blocked_indices_for_root(root, head, root_specs, parent_span):
    """Indices a span resolver must not swallow for ``root``.

    Verb-complex members stay as single-token barriers. Sibling teaching roots
    contribute their owned projections; ancestor siblings only contribute the
    part *outside* this root (so a promoted conj is not blocked by its former
    ccomp parent's full subtree).
    """
    blocked = set()
    for index in verb_group_indices(head):
        if index != root.i and parent_span.contains(index):
            blocked.add(index)

    own = owned_dependency_indices(root, parent_span, root_specs)
    for other, _role, _expand in root_specs:
        if other.i == root.i:
            continue
        other_owned = owned_dependency_indices(other, parent_span, root_specs)
        blocked.update(other_owned)

    blocked -= own
    return blocked


def absorb_misattached_roots_into_clauses(
    root_specs,
    head,
    constituency,
    parent_span,
):
    """Trust a tight Benepar clause over a dependency edge that escaped it.

    Elliptical clauses such as ``as Kelsey will after ...`` may attach the
    trailing PP to the matrix verb even though Benepar correctly includes it
    in the SBAR. Keeping that PP as a matrix sibling blocks the clause span
    resolver and destroys the nesting. Only non-clause roots inside a clause
    constituent that excludes the matrix head are absorbed.
    """
    absorbed = set()
    absorbed_by_clause = {}
    clauses = [
        (root, role)
        for root, role, _expand in root_specs
        if role and role.startswith("clause-")
        # This recovery is for genuinely elliptical auxiliary predicates
        # ("as Kelsey will [discover]"), not ordinary lexical verbs whose
        # broad Benepar SBAR may contain a following discourse coordinator.
        and root.pos_ == "AUX"
        and any(child.dep_ == "mark" for child in root.children)
    ]
    for clause, _role in clauses:
        clause_spans = [
            span for span in constituency.spans
            if span.inside(parent_span)
            and span.labels.intersection(CLAUSE_LABELS)
            and span.contains(clause.i)
            and not span.contains(head.i)
        ]
        for other, other_role, _expand in root_specs:
            if other.i == clause.i or (
                other_role and other_role.startswith("clause-")
            ):
                continue
            projection = _projection(other, parent_span)
            if projection and any(
                span.contains_all(projection) for span in clause_spans
            ):
                absorbed.add(other.i)
                absorbed_by_clause.setdefault(clause.i, set()).update(projection)
    return (
        [
            spec for spec in root_specs
            if spec[0].i not in absorbed
        ],
        absorbed_by_clause,
    )


COMPOUND_ADV_PREP = {
    ("apart", "from"), ("according", "to"), ("regardless", "of"), ("instead", "of"),
    ("prior", "to"), ("owing", "to"), ("contrary", "to"), ("thanks", "to"),
    ("along", "with"), ("together", "with"), ("ahead", "of"), ("aside", "from"),
}


IDIOM_VO = {
    ("raise", "eyebrow"), ("make", "sense"), ("take", "place"), ("pay", "attention"),
    ("take", "care"), ("take", "advantage"), ("make", "use"), ("shed", "light"),
    ("play", "role"), ("play", "part"), ("catch", "sight"), ("give", "rise"),
    ("draw", "attention"), ("make", "progress"), ("take", "part"), ("keep", "pace"),
    ("lose", "sight"), ("make", "difference"), ("take", "account"), ("take", "effect"),
    ("make", "way"), ("take", "root"), ("break", "ground"), ("set", "foot"),
}


def analyze_nominal(head, doc, role, constituency, parent_span):
    """Expand a noun-ish chunk that embeds clauses: the clause subtrees become
    child chunks (recursed); everything else is the core, keeping the parent
    role. 'a decision that surprised...' -> core 'a decision' + that-clause."""
    subtree = [doc[index] for index in range(parent_span.start, parent_span.end)]
    embedded = collect_embedded_clauses(head, doc, parent_span)
    clause_heads = [doc[spec.index] for spec in embedded]
    clause_roles = {spec.index: spec.role for spec in embedded}
    clause_spans = {}
    owner = {}
    blocked_clause_roots = {head.i, *(clause.i for clause in clause_heads)}
    for clause in clause_heads:
        crole = clause_roles[clause.i]
        span = constituency.resolve(
            root=clause.i,
            role=crole,
            parent=parent_span,
            required=boundary_anchors(clause, True, parent_span),
            blocked=blocked_clause_roots - {clause.i},
            dependency_indices=dependency_indices(clause, parent_span),
        )
        clause_spans[clause.i] = span
        for index in range(span.start, span.end):
            owner.setdefault(index, clause)

    # First-come ownership settles a token that two Benepar spans both cover,
    # but a token is only genuinely shared when neither clause governs it. In
    # "…who had retired on their incomes, and who had no relation…" both SBARs
    # open at the *first* `who`, so the second clause's own subject went to the
    # first clause and the conjunct card started on its bare verb. A token
    # belongs to the nearest clause head above it, not the earliest resolved.
    clause_by_index = {clause.i: clause for clause in clause_heads}

    def nearest_clause_head(index):
        node = doc[index]
        while True:
            if node.i in clause_by_index:
                return clause_by_index[node.i]
            if node.head.i == node.i or not parent_span.contains(node.head.i):
                return None
            node = node.head

    for index, holder in list(owner.items()):
        governor = nearest_clause_head(index)
        if (
            governor is not None
            and governor is not holder
            and clause_spans[governor.i].contains(index)
        ):
            owner[index] = governor

    # `owner` is first-come, so a later clause whose Benepar span overlaps an
    # earlier one keeps only the tokens still free — but its *recursion* span
    # was not narrowed to match. "…classes who had retired on their incomes,
    # and who had no relation…" gives the second conjunct an SBAR that opens at
    # its own `who`, a token the first conjunct already took; recursing over
    # the untightened span emits that `who` inside both clauses, and a child
    # that starts before its parent gets the whole sentence rejected.
    for clause in clause_heads:
        span = clause_spans[clause.i]
        held = [
            index for index in range(span.start, span.end)
            if owner.get(index) is clause
        ]
        if not held or not held[0] <= clause.i <= held[-1]:
            # Nothing left, or the head itself went to a neighbour: tightening
            # would hand analyze_clause a span its own head sits outside.
            continue
        if held[0] != span.start or held[-1] != span.end - 1:
            clause_spans[clause.i] = TokenSpan(held[0], held[-1] + 1, span.labels)

    # Appositive enumeration ("the Irish version: the poverty; the father; …"):
    # appos chain members hanging inside this NP. With two or more, the
    # semicolon/colon-separated items are a list, not a continuation of the
    # parent phrase — each becomes its own appositive chunk.
    enum_members = set()
    for t in subtree:
        if t.dep_ == "appos":  # noqa: SIM114
            enum_members.add(t.i)
        elif t.dep_ == "conj" and t.head.i in enum_members:
            enum_members.add(t.i)

    def bracketed_indices(run):
        """The indices of ``run`` that sit between brackets, not the brackets.

        Never break inside a parenthesis. "(Seaside, Florida)" holds a comma
        that fences an appositive by every test there is, but the aside is one
        card: cutting it open left ", Florida)" hanging off the next item.
        `split_brackets` owns everything between the brackets.
        """
        depth, inside = 0, set()
        for index in run:
            text = doc[index].text
            if text in CLOSE_BRACKETS and depth:
                depth -= 1
            elif depth:
                inside.add(index)
            if text in OPEN_BRACKETS:
                depth += 1
        return inside

    def split_enumeration(run):
        # Split at each appositive member's own start so comma-, semicolon- and
        # colon-separated lists all break into items. Punctuation is not a
        # reliable separator (commas also fence off single amods); the member's
        # leading determiner/adjective run is. Everything before the first
        # member is the core ("a cacophony of hacking coughs").
        if not enum_members:
            return [run]
        # With one member the comma is what licenses the split: a bare renaming
        # ("the poet Milton") is one phrase, a fenced one ("Lloyd Nickson, a
        # 54-year-old Darwin resident") is a second naming with its own card.
        # A list needs no comma test -- the members are the enumeration.
        lone = len(enum_members) < 2
        run_set = set(run)
        inside = bracketed_indices(run)
        starts = set()
        for member in enum_members:
            # The item starts where its own subtree does, not where its direct
            # children do. "Affinity, a Melbourne-based ISP" hangs `Melbourne`
            # and the hyphen off `based` rather than off `ISP`, so a walk that
            # only accepted direct children stopped at the hyphen -- two tokens
            # short of the comma that was the whole licence to split.
            member_subtree = {x.i for x in doc[member].subtree}
            start = member
            while (
                (start - 1) in run_set
                and (start - 1) in member_subtree
                and (start - 1) not in enum_members
            ):
                start -= 1
            # "the English and the terrible things" is one slot: a bare and/or
            # (no comma before it) coordinates within an item, not between
            # items. Only an and/or after a comma ("A, B, and C") opens a slot.
            left = start - 1
            if left in run_set and getattr(doc[left], "pos_", "") == "CCONJ":
                prev = left - 1
                if not (prev in run_set and doc[prev].text in (",", ";")):
                    continue
            if lone:
                fence = appositive_fence(doc, start)
                if fence is None or fence not in run_set:
                    continue
                # Split at the fence, not after it: the comma introduces the
                # appositive, so ", a poetry book" is the card. Leaving it
                # behind strands it on whatever preceded ("(2001),").
                start = fence
                # A second comma closes the insertion. "the highlight, not the
                # totality, of his travels" is three cards, and opening one
                # without closing it would hand the tail to the appositive —
                # "of his travels" is the head noun's, not the renaming's.
                right = max(x.i for x in doc[member].subtree)
                if (
                    right + 1 in run_set
                    and right + 2 in run_set
                    and doc[right + 1].text == ","
                ):
                    starts.add(right + 2)
            starts.add(start)
        starts -= inside
        parts, current = [], []
        for i in run:
            if i in starts and current:
                parts.append(current)
                current = []
            current.append(i)
        if current:
            parts.append(current)
        return parts if len(parts) > 1 else [run]

    def split_brackets(run):
        # A parenthesis is supplementary material whatever the parse made of
        # its contents — across three corpus sentences spaCy read the same
        # "(1905–1974)" shape as `parataxis`, `npadvmod` and `prep`, so no
        # dependency test finds them and the brackets themselves are the
        # signal. Nesting is tracked so an inner pair does not close the card
        # early; anything unclosed simply runs to the end of the run.
        parts, current, depth = [], [], 0
        for index in run:
            text = doc[index].text
            if text in OPEN_BRACKETS:
                if depth == 0 and current:
                    parts.append(current)
                    current = []
                depth += 1
            current.append(index)
            if text in CLOSE_BRACKETS and depth:
                depth -= 1
                if depth == 0:
                    parts.append(current)
                    current = []
        if current:
            parts.append(current)
        return parts

    supplement_starts = set()

    def split_comma_supplement(run):
        # A comma after the head noun closes the phrase, and what follows it
        # expands rather than continues: "lifelong cognitive disability,
        # including deficits in learning and memory", "at the very tip of the
        # egg, only fifty yards from the Sound". spaCy has no one label for
        # these -- `prep`, `advmod`, `amod`, `npadvmod` across the corpus -- so
        # again the punctuation is what holds. `fences` below is where a comma
        # earns the split.
        run_set = set(run)
        inside = bracketed_indices(run)
        if not any(doc[i].pos_ != "PUNCT" for i in run):
            return [run]
        # A lone dash fences the same way a comma does: "a paradox — an endless
        # conflict between the desire", "the tallest church building in Estonia
        # – 123.7 meters above ground level". A *pair* of them is a
        # parenthetical with two edges, and `_split_paired_dash_parentheticals`
        # in the card layer already knows where both of them go.
        dashes = [i for i in run if doc[i].text in DASH_TOKENS]
        fence_texts = {","} | ({doc[dashes[0]].text} if len(dashes) == 1 else set())

        def fences(comma):
            """Whether this comma has a whole supplement to its right."""
            tail = next(
                (doc[i] for i in run if i > comma and doc[i].pos_ != "PUNCT"),
                None,
            )
            # "such as penalisation, incentives, and resources": what follows is
            # another item of the same list, not a supplement to it. A list is
            # one slot -- `split_enumeration` is where a list earns its cards --
            # and calling each item an 插入语 would teach the wrong thing about
            # every one of them.
            if tail is None or tail.pos_ == "CCONJ":
                return False
            # "on March 16, 1998" is a date, and "400, 500 and 600" a figure:
            # a comma with a number either side joins them.
            before = doc[comma - 1] if comma - 1 in run_set else None
            if before is not None and before.pos_ == tail.pos_ == "NUM":
                return False
            root = phrase_root(comma, tail)
            if root.dep_ == "conj":
                return False
            reach = [x.i for x in root.subtree]
            # One word is never a supplement. "in several books, notably The
            # Demon-Haunted World" and "…and genuine, both as an individual and
            # as a member of a society" hang everything after `notably` and
            # `both` off a word outside this run, so all the comma could open is
            # a modifier that lost the thing it modifies.
            if len(reach) < 2:
                return False
            # The phrase to the right has to begin at the fence. Where it
            # reaches back across it the comma is inside one phrase rather than
            # around it: "the medieval convention of symbolic, two-dimensional
            # space", "the cautious, unadorned prose of the day". Take the head
            # noun out and the modifiers either side are no longer next to each
            # other, so there is no split to draw.
            #
            # And it has to be whole inside this run. "Livingston's story,
            # Houdini Act, originally published by The Saturday Evening Post"
            # and "a compensating involvement with religious writings,
            # inoffensive to the church" each lose the phrase's own complement
            # to a card carved out earlier, leaving a participle or an adjective
            # with nothing to stand on.
            return comma < min(reach) and max(reach) <= run[-1]

        def phrase_root(comma, tail):
            seen = 0
            while (
                tail.head.i in run_set
                and tail.head.i > comma
                and tail.head is not tail
                and seen < len(run)
            ):
                tail = tail.head
                seen += 1
            return tail

        opened = [
            index for index in run[1:-1]
            if index not in inside
            and doc[index].text in fence_texts
            and fences(index)
        ]
        starts = set(opened)
        supplement_starts.update(starts)

        parts, current = [], []
        for index in run:
            if index in starts and current:
                parts.append(current)
                current = []
            current.append(index)
        if current:
            parts.append(current)
        return parts

    def split_supplement(run):
        # A colon introduces an expansion of whatever came before it, and the
        # dependency parse does not say so: across four corpus sentences spaCy
        # read the tail as `pobj`, `appos`, `appos` and `npadvmod`. As with
        # brackets, the punctuation is the only signal that holds.
        #
        # The colon stays with the half that introduced it. "two perspectives:"
        # is the phrase making the promise, and a card opening on a bare colon
        # reads as punctuation stranded from its sentence.
        parts, current = [], []
        for index in run:
            current.append(index)
            if doc[index].text in SUPPLEMENT_PUNCT:
                parts.append(current)
                current = []
        if current:
            parts.append(current)
        return parts

    chunks = []
    run_owner, run = "__sentinel__", []

    def flush():
        nonlocal run, run_owner
        if not run:
            return
        text = doc[run[0]: run[-1] + 1].text
        bounds = {"_lo": run[0], "_hi": run[-1]}
        o = run_owner
        if o is None:
            parts = [
                piece
                for item in split_enumeration(run)
                for bracketed in split_brackets(item)
                for fenced in split_comma_supplement(bracketed)
                for piece in split_supplement(fenced)
            ]
            for part in parts:
                part_role = role
                if (
                    any(doc[index].dep_ == "cc" for index in part)
                    and all(
                        doc[index].dep_ in ("cc", "punct")
                        for index in part
                    )
                ):
                    part_role = "conjunction"
                # A comma-fenced supplement is named by what it is. ", by Carl
                # Sagan of Cornell University" and ", including deficits in
                # learning and memory" are prepositional phrases and saying so
                # teaches the learner where to look; ", only fifty yards from
                # the Sound" is not, and 插入语 is the honest name for the rest.
                # A renaming is neither, so this yields to the appositive
                # rules below rather than replacing them — and it asks about
                # the cut it made itself, since every other splitter here has
                # already named what it separated.
                if part[0] in supplement_starts:
                    opener = next(
                        (doc[i] for i in part
                         if doc[i].pos_ not in ("PUNCT", "CCONJ")),
                        None,
                    )
                    part_role = (
                        "prep-phrase"
                        if opener is not None and opener.dep_ == "prep"
                        else "insertion"
                    )
                # An appositive is only labelled once it has a card to itself.
                # Where the run stayed whole ("as a class, an element…") the
                # label would demote the entire object NP instead of naming the
                # aside, which is why this asks about the split, not the count.
                if len(parts) > 1 and any(i in enum_members for i in part):
                    part_role = "appositive"
                if doc[part[0]].text in OPEN_BRACKETS:
                    part_role = "insertion"
                # What a colon introduces expands what precedes it, whether
                # spaCy called it an appositive or not: "Chronicles: A Magazine
                # of American Culture", "two perspectives: that of the owner
                # and that of the operator". 同位语 is what a grammar names
                # that, and repeating the parent's own role on both halves
                # would say nothing about why there are two cards.
                if part[0] - 1 in set(run) and doc[part[0] - 1].text in SUPPLEMENT_PUNCT:
                    part_role = "appositive"
                chunks.append({"text": doc[part[0]: part[-1] + 1].text,
                               "role": part_role, "gloss": "", "children": None,
                               "_lo": part[0], "_hi": part[-1]})
        else:
            crole = clause_roles[o.i]
            kids = analyze_clause(
                o, doc,
                clause_role_of_head=crole if crole.startswith("clause") else None,
                constituency=constituency,
                parent_span=clause_spans[o.i],
            )
            chunks.append({"text": text, "role": crole, "gloss": "",
                           "children": kids if len(kids) >= 2 else None, **bounds})
        run, run_owner = [], "__sentinel__"

    for t in subtree:
        o = owner.get(t.i)
        if o is not run_owner:
            flush()
            run_owner = o
        run.append(t.i)
    flush()
    result = merge_tiny(chunks)
    if len(enum_members) >= 2 and len(result) >= 2:
        # The whole enumeration collapses into ONE block under its parent
        # role; items and their clauses are children revealed on decompose.
        # A flat splice would drown the sentence backbone in list rows.
        return [{
            "text": doc[subtree[0].i: subtree[-1].i + 1].text,
            "role": role, "gloss": "", "children": result,
            "_lo": subtree[0].i, "_hi": subtree[-1].i,
        }]
    return result


def split_prep_core(sub, prep, doc):
    """Split the core card of a prep wrapper into 介词 + 宾语.

    "Apart from the fact that …" wraps a core "from the fact" plus the clause.
    That core card repeats its parent's own 介词短语 label and so teaches
    nothing; naming the preposition and its object does. Only for a wrapper —
    a prep phrase that stays one card must stay one card."""
    core = sub[0]
    lo, hi = core.get("_lo"), core.get("_hi")
    if (core.get("role") != "prep-phrase" or core.get("children")
            or not isinstance(lo, int) or not isinstance(hi, int)
            or not lo <= prep.i <= hi):
        return sub
    start = prep_object_start(prep, lo, hi)
    if start is None:
        return sub
    return [
        {"text": doc[lo:start].text, "role": "prep-phrase", "gloss": "",
         "children": None, "_lo": lo, "_hi": start - 1},
        {"text": doc[start:hi + 1].text, "role": "object", "gloss": "",
         "children": None, "_lo": start, "_hi": hi},
        *sub[1:],
    ]


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
        if len(run_local) == 1 and (toks[0].tag_ in WH_TAGS or is_wh_relative_pronoun(toks[0])):
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
            parts = analyze_nominal(
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
            elif role == "subject":
                # Keep a single subject card; nested clauses/appos become children
                # via analyze_nominal but re-wrapped so the subject label is not lost.
                sub = analyze_nominal(
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
                        "text": text, "role": "subject", "gloss": "",
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
                    sub = analyze_nominal(c, doc, role, constituency, recursive_span)
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
                sub = analyze_nominal(c, doc, role, constituency, recursive_span)
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
                splice_flat(analyze_nominal(
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


def coordinated_gerund_subject_children(
    root,
    doc,
    constituency,
    parent_span,
):
    """Return coarse children for a Benepar-backed coordinated VBG subject."""
    if root.tag_ != "VBG" or root.i != parent_span.start:
        return None
    for connector_index in range(root.i + 1, parent_span.end - 1):
        connector = doc[connector_index]
        if connector.pos_ != "CCONJ":
            continue
        if connector.dep_ != "cc":
            continue
        later = next((
            doc[index]
            for index in range(connector_index + 1, parent_span.end)
            if (
                doc[index].tag_ == "VBG"
                and doc[index].dep_ == "conj"
                and connector.head.i in (doc[index].head.i, doc[index].i)
            )
        ), None)
        if later is None:
            continue
        later_is_vp = any(
            span.start == later.i
            and span.end == parent_span.end
            and "VP" in span.labels
            for span in constituency.spans
        )
        whole_is_clause = any(
            span.start == parent_span.start
            and span.end == parent_span.end
            and span.labels.intersection({"S", "VP"})
            for span in constituency.spans
        )
        if not (later_is_vp and whole_is_clause):
            continue
        return [
            {
                "text": doc[parent_span.start:connector_index].text,
                "role": "subject",
                "gloss": "",
                "children": None,
                "_lo": parent_span.start,
                "_hi": connector_index - 1,
            },
            {
                "text": doc[connector_index:later.i].text,
                "role": "conjunction",
                "gloss": "",
                "children": None,
                "_lo": connector_index,
                "_hi": later.i - 1,
            },
            {
                "text": doc[later.i:parent_span.end].text,
                "role": "subject",
                "gloss": "",
                "children": None,
                "_lo": later.i,
                "_hi": parent_span.end - 1,
            },
        ]
    return None


def group_explanatory_for_clause(chunks, doc, constituency, parent_span):
    """Keep a comma-introduced explanatory ``for`` clause as one branch."""
    for index, chunk in enumerate(chunks):
        if (
            chunk.get("role") != "conjunction"
            or chunk.get("text", "").strip(" ,;:").lower() != "for"
        ):
            continue
        before = chunks[:index]
        after = chunks[index + 1:]
        if not (
            any(item.get("role") == "subject" for item in before)
            and any(item.get("role") == "verb" for item in before)
            and any(item.get("role") == "subject" for item in after)
            and any(item.get("role") == "verb" for item in after)
        ):
            continue
        cut = len(chunks)
        # When Benepar exposes coordinated top-level S children, use the
        # constituent containing ``for`` as the authoritative endpoint. With
        # no such boundary, keep the entire tail: guessing from a later "and"
        # would wrongly eject a coordinate clause that is still inside for.
        coordinate_spans = constituency.coordinate_clause_children(parent_span)
        for span in coordinate_spans:
            if not span.contains(chunk.get("_lo", -1)):
                continue
            cut = next(
                (
                    position
                    for position in range(index + 1, len(chunks))
                    if chunks[position].get("_lo", parent_span.end) >= span.end
                    and chunks[position].get("role") == "conjunction"
                ),
                len(chunks),
            )
            break
        tail = chunks[index:cut]
        rest = chunks[cut:]
        lo = tail[0].get("_lo")
        hi = tail[-1].get("_hi")
        if lo is None or hi is None:
            return chunks
        return before + [{
            "text": doc[lo:hi + 1].text,
            "role": "clause",
            "gloss": "",
            "children": tail,
            "_lo": lo,
            "_hi": hi,
        }] + rest
    return chunks


def group_colon_enumerations(chunks, doc, parent_span):
    """Collapse post-colon appositive lists into one expandable insertion.

    ``…is pervasive: an aspirin…, some wine…, coffee…`` otherwise floods the
    top level with insertion crumbs.
    """
    if len(chunks) < 3:
        return chunks
    colon_at = None
    for index, chunk in enumerate(chunks):
        text = chunk.get("text") or ""
        if text.rstrip().endswith(":") or text.strip() == ":":
            colon_at = index
            break
        # colon glued to previous card ("pervasive:")
        if ":" in text and index + 1 < len(chunks):
            # only treat as list opener when following cards look like list items
            following = chunks[index + 1:]
            if sum(1 for c in following if c.get("role") in ("insertion", "appositive", "adverbial", "other")) >= 2:
                colon_at = index
                break
    if colon_at is None or colon_at >= len(chunks) - 1:
        return chunks
    head = chunks[: colon_at + 1]
    tail = chunks[colon_at + 1:]
    list_roles = {"insertion", "appositive", "adverbial", "other", "object", "complement"}
    if sum(1 for c in tail if c.get("role") in list_roles) < 2:
        return chunks
    # Keep trailing non-list material (rare) outside the group.
    cut = len(tail)
    for i, chunk in enumerate(tail):
        if chunk.get("role") in ("verb", "subject", "clause-noun", "clause-adverbial",
                                   "clause-relative", "coordinator"):
            cut = i
            break
    items = tail[:cut]
    rest = tail[cut:]
    if len(items) < 2:
        return chunks
    lo = items[0].get("_lo")
    hi = items[-1].get("_hi")
    if lo is not None and hi is not None and lo < hi <= len(doc):
        text = doc[lo:hi].text
    else:
        text = " ".join(c.get("text", "") for c in items)
    group = {
        "text": text,
        "role": "insertion",
        "gloss": "",
        "children": items,
    }
    if lo is not None:
        group["_lo"] = lo
    if hi is not None:
        group["_hi"] = hi
    return head + [group] + rest


def group_constituency_clauses(chunks, role, doc, constituency, parent_span):
    """Wrap coordinated clause siblings using Benepar's actual boundaries."""
    clause_spans = constituency.coordinate_clause_children(parent_span)
    if not clause_spans:
        return chunks

    def content_hi(chunk):
        """A card's last non-punctuation token.

        Benepar's clause spans stop before a trailing comma while merge_tiny
        glues that comma onto the card, so comparing raw ``_hi`` against a
        span end drops a card that belongs inside — the same seam as
        LEARNINGS #42. "not because she was not hardworking, but …" lost its
        complement that way and the wrapper read "because she was not".
        """
        hi = chunk.get("_hi", parent_span.end - 1)
        lo = chunk.get("_lo", hi)
        while hi > lo and not any(c.isalnum() for c in doc[hi].text):
            hi -= 1
        return hi
    for left, right in pairwise(clause_spans):
        separators = [
            chunk for chunk in chunks
            if chunk.get("_lo", -1) >= left.end
            and chunk.get("_hi", parent_span.end) < right.start
        ]
        if not any(chunk.get("role") == "conjunction" for chunk in separators):
            return chunks
    result = list(chunks)
    for span in reversed(clause_spans):
        positions = [
            index for index, chunk in enumerate(result)
            if chunk.get("_lo", -1) >= span.start
            and content_hi(chunk) < span.end
        ]
        if not positions or positions != list(range(positions[0], positions[-1] + 1)):
            continue
        first, last = positions[0], positions[-1]
        selected = result[first:last + 1]
        # Bounds come from the cards actually grouped, never from the Benepar
        # span. `positions` keeps only cards falling wholly inside the span, so
        # a card that straddles its edge is left outside — and a wrapper
        # measured by the span would then cover tokens that also live in that
        # sibling. "not because she was not hardworking, but because …" hit
        # exactly this: `hardworking` sat in both the wrapper and the
        # complement card beside it, and the duplicate killed the sentence.
        lo = selected[0].get("_lo", span.start)
        hi = selected[-1].get("_hi", span.end - 1)
        if (len(selected) == 1
                and selected[0].get("_lo") == lo
                and selected[0].get("_hi") == hi):
            continue
        wrapper = {
            "text": doc[lo:hi + 1].text,
            "role": role,
            "gloss": "",
            "children": selected,
            "_lo": lo,
            "_hi": hi,
        }
        result[first:last + 1] = [wrapper]
    return result


def merge_idioms(chunks):
    """Fuse verb+object idioms (raise eyebrows) and adverb+preposition
    compounds (apart from the fact)."""
    out = []
    for ch in chunks:
        if (out and out[-1].get("_lem") and out[-1]["role"] == "verb"
                and ch.get("_lem") and ch["role"] == "object"
                and (out[-1]["_lem"], ch["_lem"]) in IDIOM_VO):
            out[-1]["text"] = out[-1]["text"] + " " + ch["text"]
            if "_hi" in ch:
                out[-1]["_hi"] = ch["_hi"]
            continue
        if (out and out[-1]["role"] in ("adverbial", "other")
                and ch["role"] == "prep-phrase" and not out[-1].get("children")):
            first_prep = ch["text"].split()[0].lower() if ch["text"].split() else ""
            if (out[-1]["text"].strip(",").lower(), first_prep) in COMPOUND_ADV_PREP:
                kids = ch.get("children")
                if kids and kids[0].get("_lo") == ch.get("_lo"):
                    # The adverb is half of the preposition ("apart from"), so
                    # it belongs on the card that names it, not only on the
                    # wrapper above it.
                    kids = list(kids)
                    kids[0] = dict(
                        kids[0],
                        text=out[-1]["text"] + " " + kids[0]["text"],
                    )
                    if "_lo" in out[-1]:
                        kids[0]["_lo"] = out[-1]["_lo"]
                ch = dict(ch, text=out[-1]["text"] + " " + ch["text"])
                if kids:
                    ch["children"] = kids
                if "_lo" in out[-1]:
                    ch["_lo"] = out[-1]["_lo"]
                out.pop()
        out.append(ch)
    for ch in out:
        ch.pop("_lem", None)
    return out


@dataclass(frozen=True)
class StructuralNode:
    attributes: tuple[tuple[str, object], ...]
    children: tuple[StructuralNode, ...] = ()

    def __post_init__(self):
        if any(not isinstance(value, (str, int, float, bool, type(None)))
               for _, value in self.attributes):
            raise TypeError("structural node attributes must be immutable scalar values")

    @classmethod
    def from_payload(cls, payload):
        return cls(
            tuple((key, value) for key, value in payload.items() if key != "children"),
            tuple(cls.from_payload(child) for child in payload.get("children") or ()),
        )

    def payload(self):
        return dict(self.attributes, children=[child.payload() for child in self.children] or None)


@dataclass(frozen=True)
class StructuralAnalysis:
    nodes: tuple[StructuralNode, ...]
    boundary_decisions: tuple[tuple[tuple[str, object], ...], ...]

    def payload(self):
        return [node.payload() for node in self.nodes]

    def decisions(self):
        return tuple(dict(decision) for decision in self.boundary_decisions)


def analyze_structure(doc, relations, *, trace=False):
    constituency = ConstituencyIndex.from_doc(doc, trace=trace, relations=relations)
    constituency.structure = SyntaxStructure(doc, relations)
    all_chunks = []
    last_end = None
    for sent in doc.sents:
        sent_chunks = analyze_clause(
            sent.root,
            doc,
            constituency=constituency,
            parent_span=constituency.sentence_span(sent.start, sent.end),
        )
        if sent_chunks:
            all_chunks.extend(sent_chunks)
        elif all_chunks and last_end is not None:
            # spaCy splits a bare colon/dash between clauses into its own
            # "sentence"; its chunks all die as punctuation-only. Glue the
            # exact source text onto the previous chunk so no character
            # vanishes from the header.
            all_chunks[-1]["text"] += doc.text[last_end: sent.end_char]
            all_chunks[-1]["_hi"] = sent.end - 1
        last_end = sent.end_char
    return StructuralAnalysis(
        tuple(StructuralNode.from_payload(chunk) for chunk in all_chunks),
        tuple(tuple(decision.items()) for decision in constituency.decisions),
    )

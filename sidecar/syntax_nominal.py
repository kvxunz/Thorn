from __future__ import annotations

from chunk_rules import merge_tiny, prep_object_start
from constituency import TokenSpan
from syntax_boundaries import boundary_anchors, dependency_indices
from syntax_features import (
    CLOSE_BRACKETS,
    DASH_TOKENS,
    OPEN_BRACKETS,
    SUPPLEMENT_PUNCT,
    appositive_fence,
)
from syntax_structure import collect_embedded_clauses


def analyze_nominal(head, doc, role, constituency, parent_span, *, analyze_clause):
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
        for index in opened:
            tail = next(doc[position] for position in run if position > index and doc[position].pos_ != "PUNCT")
            root = phrase_root(index, tail)
            end = max(piece.i for piece in root.subtree) + 1
            if (end in run_set and end + 1 in run_set and doc[end].text == ","
                    and doc[end + 1].pos_ == "CCONJ"):
                starts.add(end + 1)

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
                content = next((doc[index] for index in part if doc[index].pos_ not in ("PUNCT", "CCONJ")), None)
                if content is not None and content.pos_ == "ADP" and content.dep_ == "conj":
                    part_role = "prep-phrase"
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
    grouped = []
    for chunk in result:
        previous = grouped[-1] if grouped else None
        governing_clause = next((clause for clause in clause_heads
                                 if chunk["_lo"] <= clause.i <= chunk["_hi"]), None)
        if (previous is not None and previous["role"] == "appositive"
                and chunk["role"] == "clause-relative" and governing_clause is not None
                and previous["_lo"] <= governing_clause.head.i <= previous["_hi"]):
            children = previous.get("children") or [dict(previous)]
            grouped[-1] = dict(previous, text=doc[previous["_lo"]:chunk["_hi"] + 1].text,
                               _hi=chunk["_hi"], children=[*children, chunk])
        else:
            grouped.append(chunk)
    result = grouped
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

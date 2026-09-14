from __future__ import annotations

from chunk_rules import (
    is_wh_relative_pronoun,
    mark_discourse_insertions,
    merge_or_so,
    merge_split_words,
    merge_tiny,
    relative_pronoun_gloss,
)
from constituency import ConstituencyIndex, TokenSpan
from syntax_assignment import assign_tokens
from syntax_decomposition import (
    has_complete_embedded_relative,
    preposition_role,
)
from syntax_features import WH_TAGS
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

    assign, root_entries, inline = assign_tokens(
        head, doc, structure, constituency, parent_span, clause_role_of_head,
    )

    writer = _CardWriter(
        head, doc, constituency, clause_role_of_head, parent_span,
        root_entries, inline,
    )
    for index in range(parent_span.start, parent_span.end):
        writer.take(index, assign[index])
    writer.flush()

    result = mark_discourse_insertions(
        merge_tiny(merge_or_so(merge_idioms(merge_split_words(writer.chunks, doc)))))
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


def _nominal(*args, **kwargs):
    """``analyze_nominal`` with the recursion it is not allowed to import."""
    return analyze_nominal(*args, **kwargs, analyze_clause=analyze_clause)


class _CardWriter:
    """One card per run of tokens that share an owner.

    Cards are written in token order, so the writer holds the run it is
    collecting and closes it the moment the owner changes. Every branch below
    answers one question about the slot it was handed — does it stay one card,
    open into children, or splice its own cards into this level — and those
    answers are the shape of the sentence the learner is shown.
    """

    def __init__(
        self, head, doc, constituency, clause_role_of_head, parent_span,
        root_entries, inline,
    ):
        self.head = head
        self.doc = doc
        self.constituency = constituency
        self.clause_role_of_head = clause_role_of_head
        self.parent_span = parent_span
        self.root_entries = root_entries
        self.inline = inline
        self.chunks = []
        self._run = []
        self._key = None

    def take(self, index, key):
        if key != self._key:
            self.flush()
            self._key = key
        self._run.append(index)

    def flush(self):
        if not self._run:
            return
        run_local, key = self._run, self._key
        self._run, self._key = [], None
        before = len(self.chunks)
        self._emit(
            self.doc[run_local[0]: run_local[-1] + 1].text,
            [self.doc[i] for i in run_local],
            key,
            run_local,
        )
        # Exact token bounds ride along internally: coordinate-clause grouping
        # rebuilds wrapper texts from doc spans. Stripped before the response.
        for ch in self.chunks[before:]:
            ch.setdefault("_lo", run_local[0])
            ch.setdefault("_hi", run_local[-1])

    # ------------------------------------------------------------- writing

    def _emit(self, text, toks, key, run_local):
        if key == "verb":
            self.chunks.append({"text": text, "role": "verb", "gloss": "",
                                "children": None, "_lem": self.head.lemma_})
            return
        c, role, decompose, owned_span = self.root_entries[key]
        recursive_span = self._recursive_span(owned_span, run_local)
        if (not decompose and c.pos_ not in ("VERB", "AUX")
                and self.constituency.relations is not None):
            decompose = has_complete_embedded_relative(
                self.constituency.relations, c.i,
                recursive_span.start, recursive_span.end,
            )
        if key in self.inline:
            self._emit_coordinate(text, c, recursive_span, run_local)
            return
        if self._emit_introducer(text, toks, run_local):
            return
        self._emit_slot(text, c, role, decompose, recursive_span, run_local)

    def _recursive_span(self, owned_span, run_local):
        """The span to recurse over: what the root owns, plus any real word the
        run picked up outside it."""
        meaningful_extensions = [
            index for index in run_local
            if not owned_span.contains(index)
            and any(character.isalnum() for character in self.doc[index].text)
        ]
        if not meaningful_extensions:
            return owned_span
        return TokenSpan(
            min(owned_span.start, meaningful_extensions[0]),
            max(owned_span.end - 1, meaningful_extensions[-1]) + 1,
            owned_span.labels,
        )

    def _splice_flat(self, sub, owned_span, run_local):
        """Extend with a constituent's own chunks, then glue back any run
        tokens the constituent doesn't own — a colon the leftover pass
        parked on this run would otherwise vanish with the run text."""
        doc = self.doc
        start_index = len(self.chunks)
        self.chunks.extend(sub)
        if not sub:
            return
        suffix = [i for i in run_local if i >= owned_span.end]
        if suffix:
            last_owned = owned_span.end - 1
            char_from = doc[last_owned].idx + len(doc[last_owned].text)
            char_to = doc[suffix[-1]].idx + len(doc[suffix[-1]].text)
            self.chunks[-1]["text"] += doc.text[char_from:char_to]
            if "_hi" in self.chunks[-1]:
                self.chunks[-1]["_hi"] = suffix[-1]
        prefix = [i for i in run_local if i < owned_span.start]
        if prefix:
            first = self.chunks[start_index]
            char_to = doc[owned_span.start].idx
            first["text"] = doc.text[doc[prefix[0]].idx: char_to] + first["text"]
            if "_lo" in first:
                first["_lo"] = prefix[0]

    # -------------------------------------------------------------- slots

    def _emit_coordinate(self, text, c, recursive_span, run_local):
        # Coordinate clause. With its own subject it is a full clause:
        # inside a labeled clause it reads best as one collapsible block
        # ("and where I was born"); subject-sharing VP coordination
        # ("and married") splices flat. Top level always splices flat so
        # the header keeps per-role colors on the whole backbone.
        sub = analyze_clause(
            c,
            self.doc,
            constituency=self.constituency,
            parent_span=recursive_span,
        )
        own_subject = any(
            t.dep_ in ("nsubj", "nsubjpass", "expl") for t in c.children
        )
        if self.clause_role_of_head is not None and own_subject and len(sub) >= 2:
            self.chunks.append({"text": text, "role": self.clause_role_of_head,
                                "gloss": "", "children": sub})
        else:
            self._splice_flat(sub, recursive_span, run_local)

    def _relative_referent(self):
        # For relatives the dependency tree already knows the referent
        # (the noun the clause hangs on), so the gloss is deterministic.
        referent_head = self.head
        while (
            referent_head.dep_ == "conj"
            and referent_head.head is not referent_head
        ):
            referent_head = referent_head.head
        return (
            referent_head.head.text
            if self.clause_role_of_head == "clause-relative" else None
        )

    def _emit_introducer(self, text, toks, run_local):
        """Write a single introducing word with its true role, or decline.

        wh-pronouns/adverbs -> relative (in relative clauses) or conjunction;
        bare subordinators (when/if/because via "mark") -> conjunction.
        """
        role_of_head = self.clause_role_of_head
        referent = self._relative_referent()
        if len(run_local) == 1 and role_of_head is not None:
            tok = toks[0]
            if is_wh_relative_pronoun(tok) or tok.tag_ in WH_TAGS or tok.tag_ == "WRB":
                # A WH word is a relation marker only inside a relative
                # clause. In adverbial/noun clauses it introduces that clause
                # ("When juries…", "how well it works") and must not be
                # mislabeled merely because its dependency is an argument.
                if (
                    role_of_head == "clause-relative"
                    and tok.dep_ != "mark"
                ):
                    gloss = relative_pronoun_gloss(referent, tok.dep_)
                    self.chunks.append({"text": text, "role": "relative", "gloss": gloss, "children": None})
                else:
                    self.chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
                return True
            if tok.dep_ == "mark":
                self.chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
                return True
        if (role_of_head is not None or not any(
            token.text == "?" for token in self._span_tokens()
        )) and len(run_local) == 1 and (
            toks[0].tag_ in WH_TAGS or is_wh_relative_pronoun(toks[0])
        ):
            tok = toks[0]
            if role_of_head == "clause-relative":
                gloss = relative_pronoun_gloss(referent, tok.dep_)
                self.chunks.append({"text": text, "role": "relative", "gloss": gloss, "children": None})
            else:
                self.chunks.append({"text": text, "role": "conjunction", "gloss": "", "children": None})
            return True
        return False

    def _span_tokens(self):
        return [
            self.doc[index]
            for index in range(self.parent_span.start, self.parent_span.end)
        ]

    def _emit_slot(self, text, c, role, decompose, recursive_span, run_local):
        doc = self.doc
        if role is None:
            # A leftover with no slot of its own is still teachable when it
            # holds a colon or a fence. This short-circuit ran before the
            # `decompose` dispatch below, so "living without the haunting fear of
            # his suffering: a terrifying death from his breathing condition"
            # reached the learner as one unlabelled line of fifteen tokens no
            # matter what the gates decided about it.
            parts = _nominal(
                c, doc, "other", self.constituency, recursive_span,
            ) if decompose else []
            if len(parts) >= 2:
                self._splice_flat(parts, recursive_span, run_local)
            else:
                self.chunks.append({"text": text, "role": "other", "gloss": "",
                                    "children": None})
        elif (
            role == "clause-noun"
            and c.dep_ in ("csubj", "csubjpass")
            and (gerund_children := coordinated_gerund_subject_children(
                c,
                doc,
                self.constituency,
                recursive_span,
            )) is not None
        ):
            # spaCy occasionally reads the noun ``move`` as a verb in
            # ``abandoning X and making the alternative move``. Benepar still
            # exposes the coordinated VPs, so present the whole construction
            # as one subject instead of fabricating a nested finite clause.
            self.chunks.append({
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
                constituency=self.constituency,
                parent_span=recursive_span,
            )
            self.chunks.append({"text": text, "role": "clause-noun", "gloss": "",
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
              and not (self.chunks and self.chunks[-1]["role"] == "verb")):
            # A "noun clause" with no real subordinator that does NOT follow
            # its governing verb is almost always a misattached coordinate
            # main clause ("..., for, ..."): splice its backbone in flat.
            # Right after a verb it's a bare object clause ("He said he would
            # come") and keeps its clause identity.
            # WH-adjunct subject clauses ("How well…") keep their wrapper.
            self._splice_flat(analyze_clause(
                c,
                doc,
                clause_role_of_head=self.clause_role_of_head,
                constituency=self.constituency,
                parent_span=recursive_span,
            ), recursive_span, run_local)
        elif role == "object" and not decompose:
            self.chunks.append({"text": text, "role": role, "gloss": "",
                                "children": None, "_lem": c.lemma_})
        elif decompose:
            self._emit_decomposed(text, c, role, recursive_span, run_local)
        else:
            self.chunks.append({"text": text, "role": role, "gloss": "", "children": None})

    def _emit_decomposed(self, text, c, role, recursive_span, run_local):
        doc = self.doc
        if c.pos_ in ("VERB", "AUX") or role == "absolute":
            # verbal heads recurse fully, wrapped under their clause label;
            # an absolute's adjectival head works the same way — its "verb"
            # run is the elided-be predicate ("dead and gone").
            kids = analyze_clause(
                c,
                doc,
                clause_role_of_head=role if role.startswith("clause") else None,
                constituency=self.constituency,
                parent_span=recursive_span,
            )
            self.chunks.append({"text": text, "role": role, "gloss": "",
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
                    constituency=self.constituency,
                    parent_span=recursive_span,
                )
                self.chunks.append({"text": text, "role": role, "gloss": "",
                                    "children": kids if len(kids) >= 2 else None})
            else:
                self.chunks.append({"text": text, "role": role, "gloss": "",
                                    "children": None})
        elif role == "subject" or (
            role in ("complement", "object", "adverbial") and c.pos_ in ("NOUN", "PROPN", "PRON")
        ):
            # Keep a single subject card; nested clauses/appos become children
            # via analyze_nominal but re-wrapped so the subject label is not lost.
            sub = _nominal(
                c, doc, role, self.constituency, recursive_span,
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
                self.chunks.append(only)
            else:
                self.chunks.append({
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
                sub = _nominal(c, doc, role, self.constituency, recursive_span)
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
                    constituency=self.constituency,
                    parent_span=recursive_span,
                )
            self.chunks.append({
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
            sub = _nominal(c, doc, role, self.constituency, recursive_span)
            if not sub:
                self.chunks.append({"text": text, "role": card_role, "gloss": "",
                                    "children": None})
            elif len(sub) == 1:
                # One card back: either a plain prep phrase or a single
                # collapsed block (e.g. an appositive enumeration) that
                # already carries its own children — keep them.
                sub[0]["role"] = card_role
                self._splice_flat(sub, recursive_span, run_local)
            else:
                # Prefer a single prep wrapper only when the first sub-card
                # already carries the preposition text.
                first = sub[0].get("text", "")
                if first and text.startswith(first[: max(1, min(12, len(first)))]):
                    kids = split_prep_core(sub, c, doc)
                    self.chunks.append({
                        "text": text, "role": card_role, "gloss": "",
                        "children": kids if len(kids) >= 2 else None,
                    })
                else:
                    self._splice_flat(sub, recursive_span, run_local)
        else:
            # nominal head embedding a clause: splice core + clause as
            # siblings — no wrapper level, and the backbone highlight
            # stays on the core noun only
            self._splice_flat(_nominal(
                c,
                doc,
                role,
                self.constituency,
                recursive_span,
            ), recursive_span, run_local)

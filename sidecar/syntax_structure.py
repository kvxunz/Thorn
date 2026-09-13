from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from chunk_rules import (
    coordinated_prep_conjuncts,
    coordinating_ccs_before,
    has_own_subject,
    independent_verbal_conjuncts,
    is_clausal_pcomp,
    is_comitative_participle,
    is_dash_appositive,
    is_preposed_though_adjective,
    though_clause_verb,
    verb_group_indices,
)
from syntax_features import (
    CLAUSE_DEPS,
    COMPLEMENT_DEPS,
    DASH_TOKENS,
    clause_role_for,
    has_relative_introducer,
    is_clause_appositive_npadvmod,
    is_complex_connective,
    parent_contains_if_any,
)
from syntax_policy import backbone_role


class StructureKind(Enum):
    ATOMIC = "atomic"
    NOMINAL = "nominal"
    CLAUSAL = "clausal"
    PREPOSITIONAL = "prepositional"
    EMBEDDED = "embedded"
    APPOSITIVE = "appositive"
    SUPPLEMENT = "supplement"


@dataclass(frozen=True)
class SyntaxRoot:
    index: int
    role: str | None
    kind: StructureKind


def adverbial_root(token) -> SyntaxRoot:
    if (token.pos_ == "ADP" and any(child.tag_ == "WRB" for child in token.children)
            and any("SBAR" in span._.labels and span.start <= token.i < span.end
                    and not span.start <= token.head.i < span.end
                    for span in token.sent._.constituents)):
        return SyntaxRoot(token.i, "clause-adverbial", StructureKind.CLAUSAL)
    if is_preposed_though_adjective(token):
        verbal = though_clause_verb(token)
        return SyntaxRoot((verbal if verbal is not None else token).i,
                          "clause-adverbial", StructureKind.CLAUSAL)
    nested_verbal = any(child.pos_ in ("VERB", "AUX") for child in token.subtree if child is not token)
    if token.pos_ not in ("VERB", "AUX"):
        return SyntaxRoot(token.i, "clause-adverbial" if nested_verbal else "adverbial",
                          StructureKind.CLAUSAL if nested_verbal else StructureKind.ATOMIC)
    infinitive = any(child.tag_ == "TO" for child in token.children) or (
        token.i > 0 and token.doc[token.i - 1].tag_ == "TO"
    )
    reduced = not has_own_subject(token) and not nested_verbal and token.tag_ in ("VBG", "VBN", "JJ")
    return SyntaxRoot(token.i, "adverbial" if infinitive or reduced else "clause-adverbial",
                      StructureKind.CLAUSAL)


def relative_role(token, *, nominal_context=False) -> str:
    infinitive = any(child.tag_ == "TO" for child in token.children) or (
        token.i > 0 and token.doc[token.i - 1].tag_ == "TO"
    )
    own_subject = any(child.dep_ in ("nsubj", "nsubjpass", "csubj", "csubjpass")
                      for child in token.children) if nominal_context else has_own_subject(token)
    if nominal_context and token.dep_ == "pcomp":
        return "clause-noun"
    if infinitive and not own_subject:
        return "adverbial"
    finite_auxiliary = any(child.dep_ in ("aux", "auxpass") and child.tag_ in ("VBD", "VBP", "VBZ", "MD")
                           for child in token.children)
    if token.tag_ == "VBG" and own_subject and not finite_auxiliary and not has_relative_introducer(token):
        return "insertion"
    if is_comitative_participle(token):
        return "insertion"
    if nominal_context:
        if token.dep_ == "acl" and not has_relative_introducer(token) and not infinitive:
            start = min(child.i for child in token.subtree)
            set_off = start > 0 and token.doc[start - 1].text in {",", *DASH_TOKENS}
            return "insertion" if set_off else "clause-relative"
    elif token.dep_ == "acl" and token.head.dep_ in ("nsubj", "nsubjpass", "dobj", "pobj", "appos"):
        return "insertion" if not has_relative_introducer(token) else clause_role_for(token)
    return clause_role_for(token)


def collect_roots(head, relations=None) -> tuple[SyntaxRoot, ...]:
    group = verb_group_indices(head)
    candidates = list(head.children)
    for index in group:
        if index != head.i:
            candidates.extend(child for child in head.doc[index].children if child.i not in group)
    roots = []
    for token in sorted(candidates, key=lambda child: child.i):
        dependency = token.dep_
        if dependency in ("aux", "auxpass", "neg", "prt", "punct"):
            continue
        relation = relations.attachment(token.i) if relations is not None else None
        decision = backbone_role(relation.dependency if relation is not None else dependency, head.lemma_)
        if decision is not None:
            role, clausal = decision
            spec = SyntaxRoot(token.i, role, StructureKind.CLAUSAL if clausal else StructureKind.NOMINAL)
        elif dependency == "pcomp" and is_clausal_pcomp(token):
            spec = SyntaxRoot(token.i, clause_role_for(token), StructureKind.CLAUSAL)
        elif dependency == "advcl":
            spec = adverbial_root(token)
        elif dependency in ("relcl", "acl"):
            spec = SyntaxRoot(token.i, relative_role(token), StructureKind.CLAUSAL)
        elif dependency in ("prep", "agent"):
            if token.i in group:
                continue
            spec = SyntaxRoot(token.i, "conjunction", StructureKind.EMBEDDED) if token.lower_ == "than" else (
                SyntaxRoot(token.i, "prep-phrase", StructureKind.PREPOSITIONAL)
            )
        elif dependency == "pobj":
            spec = SyntaxRoot(token.i, "object", StructureKind.NOMINAL)
        elif dependency in ("advmod", "npadvmod"):
            if token.i in group:
                continue
            if is_clause_appositive_npadvmod(token):
                spec = SyntaxRoot(token.i, "insertion", StructureKind.CLAUSAL)
            elif is_complex_connective(token):
                spec = SyntaxRoot(token.i, "clause-adverbial", StructureKind.CLAUSAL)
            elif dependency == "npadvmod" and token.pos_ in ("NOUN", "PROPN", "PRON"):
                spec = SyntaxRoot(token.i, "adverbial", StructureKind.NOMINAL)
            else:
                spec = SyntaxRoot(token.i, "adverbial", StructureKind.ATOMIC)
        elif dependency in ("cc", "mark"):
            spec = SyntaxRoot(token.i, "conjunction", StructureKind.ATOMIC)
        elif dependency == "conj" or (dependency == "dep" and token.pos_ in ("VERB", "AUX")):
            if token.pos_ in ("VERB", "AUX"):
                spec = SyntaxRoot(token.i, "__coord_clause__", StructureKind.CLAUSAL)
            elif any(child.dep_ in ("nsubj", "nsubjpass") for child in token.children):
                spec = SyntaxRoot(token.i, "absolute", StructureKind.CLAUSAL)
            elif token.pos_ == "ADP" and any(child.dep_ == "pobj" for child in token.children):
                spec = SyntaxRoot(token.i, "prep-phrase", StructureKind.PREPOSITIONAL)
            else:
                spec = SyntaxRoot(token.i, "object" if head.pos_ in ("VERB", "AUX") else "adverbial",
                                  StructureKind.EMBEDDED)
        elif dependency == "appos":
            spec = SyntaxRoot(token.i, "insertion", StructureKind.APPOSITIVE)
        elif dependency in ("intj", "parataxis"):
            independent = (token.pos_ in ("VERB", "AUX")
                           and any(child.dep_ in ("nsubj", "nsubjpass", "expl") for child in token.children)
                           and any(child.dep_ in COMPLEMENT_DEPS for child in token.children))
            spec = SyntaxRoot(token.i, "insertion", StructureKind.CLAUSAL if independent else StructureKind.EMBEDDED)
        elif token.lower_ == "for" and token.pos_ in ("ADP", "CCONJ", "SCONJ") and not any(
            child.dep_ == "pobj" for child in token.children
        ):
            spec = SyntaxRoot(token.i, "conjunction", StructureKind.ATOMIC)
        else:
            spec = SyntaxRoot(token.i, None, StructureKind.SUPPLEMENT)
        roots.append(spec)

    seen = {spec.index for spec in roots}
    promoted = []
    for spec in roots:
        token = head.doc[spec.index]
        conjuncts = ()
        if spec.role == "clause-noun":
            conjuncts = independent_verbal_conjuncts(token)
        elif spec.role == "prep-phrase":
            conjuncts = coordinated_prep_conjuncts(token)
        for conjunct in conjuncts:
            if spec.role == "clause-noun" and content_scope_contains(token, conjunct, head):
                continue
            if conjunct.i in seen or not parent_contains_if_any(head, conjunct):
                continue
            seen.add(conjunct.i)
            promoted.append(SyntaxRoot(
                conjunct.i, "__coord_clause__" if spec.role == "clause-noun" else "prep-phrase",
                StructureKind.CLAUSAL if spec.role == "clause-noun" else StructureKind.PREPOSITIONAL,
            ))
            for connector in coordinating_ccs_before(token, conjunct):
                if connector.i not in seen:
                    seen.add(connector.i)
                    promoted.append(SyntaxRoot(connector.i, "conjunction", StructureKind.ATOMIC))
        if spec.role == "subject":
            for child in token.children:
                if child.i not in seen and (child.dep_ == "appos" or is_dash_appositive(child)):
                    seen.add(child.i)
                    promoted.append(SyntaxRoot(child.i, "insertion", StructureKind.CLAUSAL))
    if promoted:
        roots.extend(promoted)
        roots.sort(key=lambda spec: spec.index)
    return tuple(roots)


def content_scope_contains(token, conjunct, governor):
    if token.dep_ != "ccomp":
        return False
    return any(
        "SBAR" in span._.labels
        and span.start <= token.i < span.end
        and span.start <= conjunct.i < span.end
        and not span.start <= governor.i < span.end
        for span in token.sent._.constituents
    )


def collect_embedded_clauses(head, doc, parent_span) -> tuple[SyntaxRoot, ...]:
    candidates = [doc[index] for index in range(parent_span.start, parent_span.end)
                  if doc[index] is not head
                  and (doc[index].dep_ in CLAUSE_DEPS or is_clausal_pcomp(doc[index]))
                  and parent_span.contains(doc[index].head.i)]
    promoted = set()
    for clause in list(candidates):
        for conjunct in independent_verbal_conjuncts(clause):
            if parent_span.contains(conjunct.i):
                promoted.add(conjunct.i)
                candidates.append(conjunct)
    candidates = list({clause.i: clause for clause in candidates}.values())
    candidates = [clause for clause in candidates
                  if clause.i in promoted or not any(
                      clause is not other and clause in other.subtree for other in candidates
                  )]
    return tuple(SyntaxRoot(clause.i, relative_role(clause, nominal_context=True), StructureKind.CLAUSAL)
                 for clause in candidates)


class SyntaxStructure:
    def __init__(self, doc, relations=None):
        self.doc = doc
        self.relations = relations
        self._roots: dict[int, tuple[SyntaxRoot, ...]] = {}

    def roots(self, head_index: int) -> tuple[SyntaxRoot, ...]:
        if head_index not in self._roots:
            self._roots[head_index] = collect_roots(self.doc[head_index], self.relations)
        return self._roots[head_index]

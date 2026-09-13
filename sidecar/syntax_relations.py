from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teaching_tree import TeachingEvidence


_RELATIONS = {
    "nsubj": "subject", "nsubjpass": "subject", "csubj": "subject",
    "csubjpass": "subject", "expl": "expletive", "dobj": "object", "obj": "object",
    "iobj": "indirect-object", "dative": "indirect-object",
    "pobj": "preposition-object", "attr": "complement", "acomp": "complement",
    "oprd": "complement", "ccomp": "content-clause", "xcomp": "open-complement",
    "relcl": "relative-modifier", "acl": "nominal-modifier",
    "advcl": "clausal-modifier", "amod": "nominal-modifier",
    "advmod": "adverbial-modifier", "prep": "preposition-modifier",
    "agent": "preposition-modifier", "appos": "appositive",
    "conj": "coordinate", "aux": "auxiliary", "auxpass": "auxiliary",
    "neg": "negation",
}
_CLAUSAL = frozenset({"ccomp", "xcomp", "relcl", "acl", "advcl", "csubj", "csubjpass", "pcomp"})
_SUBJECTS = frozenset({"nsubj", "nsubjpass", "csubj", "csubjpass"})


@dataclass(frozen=True)
class SyntaxRelation:
    head: int
    dependent: int
    kind: str
    dependency: str
    provenance: str = "spacy-dependency"


@dataclass(frozen=True)
class ClauseFrame:
    predicate: int
    parent: int | None
    subjects: tuple[int, ...]
    objects: tuple[int, ...]
    complements: tuple[int, ...]
    finiteness: str


@dataclass(frozen=True)
class Coordination:
    head: int
    members: tuple[int, ...]


@dataclass(frozen=True)
class SyntaxRelations:
    edges: tuple[SyntaxRelation, ...]
    clauses: tuple[ClauseFrame, ...]
    coordinations: tuple[Coordination, ...]
    clause_by_token: tuple[int | None, ...]
    diagnostics: tuple[str, ...]
    token_heads: tuple[int, ...]

    @classmethod
    def from_evidence(cls, evidence: TeachingEvidence) -> SyntaxRelations:
        tokens = evidence.tokens
        children: dict[int, list[int]] = {token.index: [] for token in tokens}
        for token in tokens:
            if token.head != token.index:
                children[token.head].append(token.index)

        predicates = {
            token.index for token in tokens
            if token.dep == "ROOT"
            or token.dep in _CLAUSAL
            or (token.dep == "conj" and token.pos in {"VERB", "AUX"})
        }
        diagnostics: set[str] = set()

        def ancestor(index, candidates, include_self=True):
            visited = set()
            current = index if include_self else tokens[index].head
            while current not in visited:
                visited.add(current)
                if current in candidates and (include_self or current != index):
                    return current
                if tokens[current].head == current:
                    return None
                current = tokens[current].head
            diagnostics.add("dependency-cycle")
            return None

        edges = tuple(
            SyntaxRelation(token.head, token.index, _RELATIONS[token.dep], token.dep,
                           next((rule for index, rule, _before in evidence.repairs if index == token.index),
                                "spacy-dependency"))
            for token in tokens
            if token.dep in _RELATIONS and token.head != token.index
        )
        frames = []
        for predicate in sorted(predicates):
            dependents = [tokens[index] for index in children[predicate]]
            finite = any(
                token.tag in {"VBD", "VBP", "VBZ", "MD"}
                for token in [tokens[predicate], *[
                    child for child in dependents if child.dep in {"aux", "auxpass", "cop"}
                ]]
            )
            frames.append(ClauseFrame(
                predicate=predicate,
                parent=ancestor(predicate, predicates, include_self=False),
                subjects=tuple(child.index for child in dependents if child.dep in _SUBJECTS),
                objects=tuple(child.index for child in dependents if child.dep in {"dobj", "obj", "iobj", "dative"}),
                complements=tuple(child.index for child in dependents if child.dep in {
                    "attr", "acomp", "oprd", "ccomp", "xcomp",
                }),
                finiteness=(
                    "finite" if finite else "nonfinite"
                    if tokens[predicate].tag in {"VBG", "VBN"}
                    or any(child.tag == "TO" for child in dependents)
                    else "undetermined"
                ),
            ))
        groups: dict[int, set[int]] = {}
        for token in tokens:
            if token.dep != "conj":
                continue
            head = token.head
            visited = {token.index}
            while tokens[head].dep == "conj" and head not in visited:
                visited.add(head)
                head = tokens[head].head
            if head in visited:
                diagnostics.add("coordination-cycle")
                continue
            groups.setdefault(head, {head}).add(token.index)
        ownership = tuple(ancestor(token.index, predicates) for token in tokens)
        return cls(
            edges=edges,
            clauses=tuple(frames),
            coordinations=tuple(
                Coordination(head, tuple(sorted(members))) for head, members in sorted(groups.items())
            ),
            clause_by_token=ownership,
            diagnostics=tuple(sorted(diagnostics)),
            token_heads=tuple(token.head for token in tokens),
        )

    @cached_property
    def _children(self) -> dict[int, tuple[int, ...]]:
        children: dict[int, list[int]] = {}
        for index, head in enumerate(self.token_heads):
            if index != head:
                children.setdefault(head, []).append(index)
        return {head: tuple(indices) for head, indices in children.items()}

    def descendants(self, root: int) -> frozenset[int]:
        visited = set()
        pending = [root]
        while pending:
            index = pending.pop()
            if index in visited:
                continue
            visited.add(index)
            pending.extend(self._children.get(index, ()))
        return frozenset(visited)

    @cached_property
    def _attachments(self) -> dict[int, SyntaxRelation]:
        return {edge.dependent: edge for edge in self.edges}

    def attachment(self, dependent: int) -> SyntaxRelation | None:
        return self._attachments.get(dependent)

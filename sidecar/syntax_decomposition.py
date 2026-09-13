from __future__ import annotations

from chunk_rules import is_dash_appositive
from syntax_features import (
    contains_clause,
    has_appositive_enumeration,
    has_comma_supplement,
    has_fenced_supplement,
    has_supplement_punctuation,
    is_adverbial_complex_prep,
    prep_object_enumeration,
)
from syntax_structure import StructureKind, SyntaxRoot


def requires_decomposition(spec: SyntaxRoot, doc) -> bool:
    token = doc[spec.index]
    if spec.kind == StructureKind.CLAUSAL:
        return True
    if spec.kind == StructureKind.ATOMIC:
        return False
    if spec.kind == StructureKind.NOMINAL:
        return contains_clause(token) or has_appositive_enumeration(token) or has_fenced_supplement(token)
    if spec.kind == StructureKind.PREPOSITIONAL:
        return (prep_object_enumeration(token) or contains_clause(token)
                or is_adverbial_complex_prep(token) or has_fenced_supplement(token))
    if spec.kind == StructureKind.EMBEDDED:
        return contains_clause(token)
    if spec.kind == StructureKind.APPOSITIVE:
        return contains_clause(token) or is_dash_appositive(token)
    if spec.kind == StructureKind.SUPPLEMENT:
        return contains_clause(token) or has_supplement_punctuation(token) or has_comma_supplement(token)
    raise ValueError(f"unsupported structure kind: {spec.kind}")


def plan_roots(specs, doc):
    return [(doc[spec.index], spec.role, requires_decomposition(spec, doc)) for spec in specs]


def has_complete_embedded_relative(relations, root: int, start: int, end: int) -> bool:
    return any(
        edge.dependency == "relcl"
        and edge.dependent != root
        and start <= edge.dependent < end
        and start <= edge.head < end
        and all(start <= index < end for index in relations.descendants(edge.dependent))
        for edge in relations.edges
    )


def preposition_role(token):
    return "adverbial" if is_adverbial_complex_prep(token) else "prep-phrase"

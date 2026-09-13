from __future__ import annotations

from chunk_rules import has_own_subject, is_clausal_pcomp, verb_group_indices
from constituency import CLAUSE_LABELS
from syntax_features import CLAUSE_DEPS

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
    if root.pos_ in ("NOUN", "PROPN", "PRON"):
        anchors.update(child.i for child in root.children
                       if child.dep_ in ("amod", "appos") and child.i > root.i and parent.contains(child.i))
    if root.dep_ in ("prep", "agent"):
        anchors.update(child.i for child in root.children
                       if child.dep_ == "npadvmod" and child.i < root.i and parent.contains(child.i))
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

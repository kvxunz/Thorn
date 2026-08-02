# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "spacy==3.7.5",
#     "benepar==0.2.0",
#     "torch>=2.2,<3",
#     "transformers==4.30.2",
#     "protobuf==3.20.3",
#     "sentencepiece>=0.1.99",
#     "fastapi>=0.110",
#     "uvicorn>=0.29",
#     "spacy-transformers>=1.3,<1.4",
#     "numpy<2",
#     "en-core-web-trf @ https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.7.3/en_core_web_trf-3.7.3-py3-none-any.whl",
# ]
# ///
"""Thorn local language sidecar: raw spaCy + Benepar evidence.

Run: uv run --script server.py [--port 48620] [--idle-exit 120]
"""
import argparse
import hmac
import importlib.metadata
import os
import re
import signal
import threading
import time

import benepar
import spacy
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from alignment import annotate_chunk_spans
from chunk_rules import (
    coordinated_prep_conjuncts,
    coordinating_ccs_before,
    has_own_subject,
    independent_verbal_conjuncts,
    is_clausal_pcomp,
    is_comitative_participle,
    is_concessive_however_clause,
    is_dash_appositive,
    is_preposed_though_adjective,
    is_wh_relative_pronoun,
    mark_discourse_insertions,
    merge_or_so,
    prep_object_start,
    prepare_parse_text,
    relative_pronoun_gloss,
    though_clause_verb,
    verb_group_indices,
)
from constituency import CLAUSE_LABELS, ConstituencyIndex, TokenSpan
from evidence import ANALYSIS_PROTOCOL_VERSION, build_analysis_evidence
from grammar_notes import annotate_grammar_notes
from teaching_tree import TeachingEvidence, TokenSource, compile_teaching_tree

SPACY_MODEL = "en_core_web_trf"
BENEPAR_MODEL = "benepar_en3"
PARSE_PROTOCOL_VERSION = 4

# UD dep label -> Thorn role, for clause-level constituents
CLAUSE_ROLES = {
    "relcl": "clause-relative",
    "acl": "clause-relative",
    "advcl": "clause-adverbial",
    "ccomp": "clause-noun",
    "csubj": "clause-noun",
    "csubjpass": "clause-noun",
    "xcomp": "complement",  # non-finite: treat as complement, not clause
}

nlp = None
nlp_inference_lock = threading.Lock()
# One request may wait behind the active inference; additional requests fail
# fast instead of consuming every FastAPI worker while blocked on Torch.
parse_slots = threading.BoundedSemaphore(2)
last_request = time.time()
auth_token = os.environ.get("THORN_SIDECAR_TOKEN", "")


def require_auth(x_thorn_token: str | None = Header(default=None)):
    if (not auth_token or not x_thorn_token
            or not hmac.compare_digest(auth_token, x_thorn_token)):
        raise HTTPException(status_code=401, detail="unauthorized sidecar request")


def load():
    global nlp
    # Model installation is an explicit setup action.  Starting the app must
    # never trigger a network download or mutate the user's model cache.
    nlp = spacy.load(SPACY_MODEL)
    if "benepar" not in nlp.pipe_names:
        nlp.add_pipe("benepar", config={"model": BENEPAR_MODEL})


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


# ---------------------------------------------------------------- chunking

def chunk_roots(head):
    """Decide the chunk-root tokens directly under a clause head.
    Returns list of (root_token, role, expand). expand=True -> recurse."""
    # In inversions ("Nor, if …, is management to be blamed") spaCy hangs
    # fronted conjunctions/clauses on the auxiliary, not the content verb.
    # The verbal complex is one predicate: harvest dependents of every
    # member, or those tokens become orphans swallowed by a neighbor chunk.
    group = verb_group_indices(head)
    doc = head.doc
    candidates = list(head.children)
    for index in group:
        if index == head.i:
            continue
        candidates.extend(
            c for c in doc[index].children if c.i not in group
        )
    roots = []
    for c in sorted(candidates, key=lambda t: t.i):
        d = c.dep_
        if d in ("aux", "auxpass", "neg", "prt", "punct"):
            continue  # part of the verb group / attached punctuation
        if d in ("nsubj", "nsubjpass", "expl"):
            # True clausal dependents expand; dash appositives are promoted as
            # insertion siblings so the head noun keeps role=subject. A
            # multi-item appositive list also expands into a revealable block.
            roots.append((c, "subject",
                          contains_clause(c) or has_appositive_enumeration(c)))
        elif d in ("dobj", "obj", "iobj", "dative", "oprd"):
            # linking verbs never take an object: theirs is a predicative
            linking = head.lemma_ in ("be", "seem", "become", "remain", "appear",
                                      "look", "feel", "sound", "stay", "grow")
            roots.append((c, "complement" if linking else "object",
                          contains_clause(c) or has_appositive_enumeration(c)))
        elif d in ("attr", "acomp"):
            roots.append((c, "complement",
                          contains_clause(c) or has_appositive_enumeration(c)))
        elif d == "xcomp":
            roots.append((c, "complement", True))
        elif d in ("ccomp", "csubj", "csubjpass"):
            # csubj/csubjpass are subject clauses ("How well… depends") — always
            # expand as a wrapped noun clause, never flatten onto the matrix.
            roots.append((c, "clause-noun", True))
        elif d == "advcl":
            if is_preposed_though_adjective(c):
                # "Odd though it sounds": keep one clause block headed by the
                # finite verb; the adjective is absorbed into that span.
                verb = though_clause_verb(c)
                if verb is not None:
                    roots.append((verb, "clause-adverbial", True))
                else:
                    roots.append((c, "clause-adverbial", True))
            elif c.pos_ not in ("VERB", "AUX"):
                # adjectival-predicate clauses ("however farfetched their
                # principles may seem") still contain a verb: expand those;
                # verbless fragments ("at worst") stay flat
                if any(t.pos_ in ("VERB", "AUX") for t in c.subtree if t is not c):
                    roots.append((c, "clause-adverbial", True))
                else:
                    roots.append((c, "adverbial", False))
            else:
                # infinitive purpose phrases have no subject of their own:
                # label them adverbial, not clause (still expanded)
                has_to = any(t.tag_ == "TO" for t in c.children) or (
                    c.i > 0 and c.doc[c.i - 1].tag_ == "TO")
                # "for NP to VP" purpose: for is mark on the infinitive
                # A participial/depictive adjunct with no subject of its own and
                # no inner finite verb ("slapped it, sizzling, on the chest";
                # "born in 1990, he…") is a participial 状语, not a full 状语从句.
                # spaCy may tag such a participle VBG/VBN or even JJ, so key off
                # the absence of a subject and of any nested verb, not the tag.
                reduced_participle = (
                    not has_own_subject(c)
                    and not any(
                        t.pos_ in ("VERB", "AUX") for t in c.subtree if t is not c
                    )
                    and c.tag_ in ("VBG", "VBN", "JJ")
                )
                roots.append((
                    c,
                    "adverbial" if (has_to or reduced_participle) else "clause-adverbial",
                    True,
                ))
        elif d in ("relcl", "acl"):
            # Infinitival acl after adjectives/nouns ("enough to cover…",
            # "a plan to expand") is purpose/complement, not a relative clause.
            has_to = any(t.tag_ == "TO" for t in c.children) or (
                c.i > 0 and c.doc[c.i - 1].tag_ == "TO"
            )
            has_subj = has_own_subject(c)
            if has_to and not has_subj:
                roots.append((c, "adverbial", True))
            elif c.tag_ == "VBG" and has_subj and not has_relative_introducer(c):
                # Absolute / participial appositive: "everyone being the same…"
                roots.append((c, "insertion", True))
            elif is_comitative_participle(c):
                # "coupled with…", "combined with…" — not a true relative clause
                roots.append((c, "insertion", True))
            elif c.dep_ == "acl" and c.head.dep_ in ("nsubj", "nsubjpass", "dobj", "pobj", "appos"):
                # Reduced relative / inserted participle on a noun
                # ("Big Bang, first put forward in the 1920s")
                roots.append((c, "insertion" if not has_relative_introducer(c) else clause_role_for(c), True))
            else:
                roots.append((c, clause_role_for(c), True))
        elif d in ("prep", "agent"):
            if c.i in group:
                # Swallowed by a phrasal-prepositional verb ("live up **to**").
                # Its object belongs to the verb; the harvest above already put
                # that pobj on this candidate list, handled below.
                continue
            # Comparative "than" is not a true preposition for teaching labels.
            if c.lower_ == "than":
                roots.append((c, "conjunction", contains_clause(c)))
            else:
                # Keep prep/agent as one contiguous card. Coordinated second
                # preps ("and then by…") are promoted as sibling cards below.
                # Exceptions that make the card expandable: a colon-introduced
                # appositive list, or an embedded clause (participial/relative)
                # inside the object — "with … smoke laced with … where many a
                # man puked …" — so those layers surface as their own rows.
                roots.append((
                    c,
                    "prep-phrase",
                    prep_object_enumeration(c)
                    or contains_clause(c)
                    or is_adverbial_complex_prep(c),
                ))
        elif d == "pobj":
            # Only reachable when the governing preposition was absorbed into a
            # phrasal-prepositional verb: an ordinary pobj sits under a prep
            # card and never surfaces as a candidate here. "put up with his
            # rudeness" — 宾语, not 介词短语.
            roots.append((c, "object",
                          contains_clause(c) or has_appositive_enumeration(c)))
        elif d in ("advmod", "npadvmod"):
            # Mid-complex adverbs already in the verbal complex stay off this list
            # so they cannot steal nested degree modifiers (almost under certainly).
            if c.i in group:
                continue
            roots.append((c, "adverbial", False))
        elif d == "cc":
            roots.append((c, "conjunction", False))
        elif d == "conj" or (d == "dep" and c.pos_ in ("VERB", "AUX")):
            # coordinate clause/phrase: same backbone treatment. spaCy also
            # falls back to the catch-all "dep" label for a coordinate verb it
            # could not attach ("housed …, sometimes sprouted …"); a verbal
            # "dep" hanging off the predicate is that same coordinate predicate.
            if c.pos_ in ("VERB", "AUX"):
                roots.append((c, "__coord_clause__", True))
            elif any(t.dep_ in ("nsubj", "nsubjpass") for t in c.children):
                # Non-verbal conjunct carrying its own subject = a verbless
                # coordinated clause ("…, my sister, Margaret, dead and gone"):
                # an absolute construction, never the verb's object.
                roots.append((c, "absolute", True))
            else:
                roots.append((c, "object" if head.pos_ in ("VERB", "AUX") else "adverbial",
                              contains_clause(c)))
        elif d == "mark":
            roots.append((c, "conjunction", False))
        elif d == "appos":
            roots.append((c, "insertion", contains_clause(c) or is_dash_appositive(c)))
        elif d in ("intj", "parataxis"):
            roots.append((c, "insertion", contains_clause(c)))
        elif c.lower_ == "for" and c.pos_ in ("ADP", "CCONJ", "SCONJ") and not any(
                t.dep_ == "pobj" for t in c.children):
            # bare coordinating "for" (= because) between clauses
            roots.append((c, "conjunction", False))
        else:
            roots.append((c, None, contains_clause(c)))  # absorbed later

    # Promote full-clause conjuncts nested under clausal complements so they
    # become siblings (see independent_verbal_conjuncts). Without this, spaCy's
    # "say → curl (ccomp) → tormented (conj+nsubj)" package keeps the second
    # clause inside the reported content even when teaching wants it parallel.
    seen = {token.i for token, _role, _expand in roots}
    promoted = []
    for token, role, expand in roots:
        # Only noun-clause complements (ccomp/csubj). Promoting out of an
        # adverbial clause head would lift "and why does he think…" out of a
        # because-SBAR onto the matrix clause.
        if expand and role == "clause-noun":
            for conjunct in independent_verbal_conjuncts(token):
                if conjunct.i in seen or not parent_contains_if_any(head, conjunct):
                    continue
                seen.add(conjunct.i)
                promoted.append((conjunct, "__coord_clause__", True))
                for cc in coordinating_ccs_before(token, conjunct):
                    if cc.i in seen:
                        continue
                    seen.add(cc.i)
                    promoted.append((cc, "conjunction", False))
        # "first by X … and then by Y": second by is conj of the first prep.
        if role == "prep-phrase":
            for conjunct in coordinated_prep_conjuncts(token):
                if conjunct.i in seen or not parent_contains_if_any(head, conjunct):
                    continue
                seen.add(conjunct.i)
                promoted.append((
                    conjunct,
                    "prep-phrase",
                    prep_object_enumeration(conjunct)
                    or contains_clause(conjunct)
                    or is_adverbial_complex_prep(conjunct),
                ))
                for cc in coordinating_ccs_before(token, conjunct):
                    if cc.i in seen:
                        continue
                    seen.add(cc.i)
                    promoted.append((cc, "conjunction", False))

        # Dash appositive under a subject: surface as insertion sibling so the
        # subject noun keeps role=subject ("Institute — a group — issued").
        if role == "subject":
            for child in token.children:
                if child.i in seen:
                    continue
                if child.dep_ == "appos" or is_dash_appositive(child):
                    seen.add(child.i)
                    promoted.append(
                        (child, "insertion", bool(contains_clause(child) or True))
                    )
    if promoted:
        roots.extend(promoted)
        roots.sort(key=lambda item: item[0].i)
    return roots


def parent_contains_if_any(head, token):
    """Guard so promotion never reaches outside the current head's projection."""
    return token.i in {t.i for t in head.subtree}


def contains_clause(tok):
    return any(
        t.dep_ in ("relcl", "acl", "advcl", "ccomp", "csubj", "csubjpass")
        or is_clausal_pcomp(t)
        for t in tok.subtree if t is not tok)


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


def prep_object_enumeration(prep):
    """Whether a prep's object carries an appositive list (see above)."""
    pobj = next((c for c in prep.children if c.dep_ == "pobj"), None)
    return pobj is not None and has_appositive_enumeration(pobj)


# Complex/subordinating prepositions that head a reason/concession adjunct.
# "because of", "despite", "regardless of", "instead of" — when they modify the
# predicate the whole phrase is an adverbial (原因/让步状语), not a plain 介词短语.
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

# Dependents that establish the semantic extent of a verbal constituent.  We
# deliberately omit advmod/mark: those are the attachments that most often
# strand a left-edge when/where on a lower predicate.  Benepar supplies their
# actual SBAR/WH boundary instead.
BOUNDARY_ANCHOR_DEPS = frozenset({
    "nsubj", "nsubjpass", "expl", "dobj", "obj", "iobj", "dative", "oprd",
    "attr", "acomp", "xcomp", "ccomp", "csubj", "csubjpass", "advcl",
    "relcl", "acl", "prep", "agent", "conj",
    # Noun-noun premodifiers ("tweed [and woolen] coats") are part of the NP;
    # without them the resolver settles for the minimal inner NP and strands
    # the modifier as a leftover glued onto the neighbouring predicate.
    "nmod", "compound",
})


def boundary_anchors(root, expand, parent):
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
    if expand:
        # An expandable nominal/PP owns its directly embedded clause even when
        # Benepar also offers a smaller core NP. np_expand separates it later.
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


def has_relative_introducer(root):
    return any(
        token.tag_ in WH_TAGS or token.tag_ == "WRB"
        for token in root.children
    )

# adverb+preposition compounds that read as one prep chunk
COMPOUND_ADV_PREP = {
    ("apart", "from"), ("according", "to"), ("regardless", "of"), ("instead", "of"),
    ("prior", "to"), ("owing", "to"), ("contrary", "to"), ("thanks", "to"),
    ("along", "with"), ("together", "with"), ("ahead", "of"), ("aside", "from"),
}

# verb+object pairs that read as one idiom chunk (lemma-based)
IDIOM_VO = {
    ("raise", "eyebrow"), ("make", "sense"), ("take", "place"), ("pay", "attention"),
    ("take", "care"), ("take", "advantage"), ("make", "use"), ("shed", "light"),
    ("play", "role"), ("play", "part"), ("catch", "sight"), ("give", "rise"),
    ("draw", "attention"), ("make", "progress"), ("take", "part"), ("keep", "pace"),
    ("lose", "sight"), ("make", "difference"), ("take", "account"), ("take", "effect"),
    ("make", "way"), ("take", "root"), ("break", "ground"), ("set", "foot"),
}


def np_expand(head, doc, role, constituency, parent_span):
    """Expand a noun-ish chunk that embeds clauses: the clause subtrees become
    child chunks (recursed); everything else is the core, keeping the parent
    role. 'a decision that surprised...' -> core 'a decision' + that-clause."""
    subtree = [doc[index] for index in range(parent_span.start, parent_span.end)]
    clause_heads = [t for t in subtree
                    if t is not head
                    and (t.dep_ in CLAUSE_DEPS or is_clausal_pcomp(t))
                    and parent_span.contains(t.head.i)]
    # A relative/adverbial head can coordinate a second full clause under
    # ``conj`` ("where they met ... and where I was born").  Although the
    # dependency projection nests the conjunct under the first clause, its own
    # subject makes it a sibling teaching clause.  Promote it before ownership
    # spans are resolved so the leftover pass cannot mislabel it as part of the
    # surrounding noun/preposition phrase.
    promoted_clause_ids = set()
    for clause in list(clause_heads):
        for conjunct in independent_verbal_conjuncts(clause):
            if not parent_span.contains(conjunct.i):
                continue
            promoted_clause_ids.add(conjunct.i)
            clause_heads.append(conjunct)
    clause_heads = list({clause.i: clause for clause in clause_heads}.values())
    # only direct clause attachments; nested ones handled by recursion
    clause_heads = [c for c in clause_heads
                    if c.i in promoted_clause_ids
                    or not any(c is not o and c in o.subtree for o in clause_heads)]
    clause_roles = {}
    clause_spans = {}
    owner = {}
    blocked_clause_roots = {head.i, *(clause.i for clause in clause_heads)}
    for clause in clause_heads:
        has_to = any(t.tag_ == "TO" for t in clause.children) or (
            clause.i > 0 and doc[clause.i - 1].tag_ == "TO"
        )
        has_own_subject = any(
            t.dep_ in ("nsubj", "nsubjpass", "csubj", "csubjpass")
            for t in clause.children
        )
        if clause.dep_ == "pcomp":
            crole = "clause-noun"
        elif has_to and not has_own_subject:
            crole = "adverbial"
        elif (clause.tag_ == "VBG" and has_own_subject  # noqa: SIM114
              and not has_relative_introducer(clause)):
            crole = "insertion"
        elif is_comitative_participle(clause):
            crole = "insertion"
        elif (
            clause.dep_ == "acl"
            and not has_relative_introducer(clause)
            and not has_to
        ):
            # Reduced participle on a noun. Comma/dash-set-off is a
            # non-restrictive aside ("Big Bang, first put forward…") and reads
            # as an insertion; a tight, unpunctuated postmodifier ("the mother
            # moaning by the fire") is a reduced relative — a 定语从句.
            left = min(t.i for t in clause.subtree)
            set_off = left > 0 and doc[left - 1].text in (",", "—", "–", "--")
            crole = "insertion" if set_off else "clause-relative"
        else:
            crole = clause_role_for(clause)
        clause_roles[clause.i] = crole
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

    def split_enumeration(run):
        # Split at each appositive member's own start so comma-, semicolon- and
        # colon-separated lists all break into items. Punctuation is not a
        # reliable separator (commas also fence off single amods); the member's
        # leading determiner/adjective run is. Everything before the first
        # member is the core ("a cacophony of hacking coughs").
        if len(enum_members) < 2:
            return [run]
        run_set = set(run)
        starts = set()
        for member in enum_members:
            start = member
            while (
                (start - 1) in run_set
                and doc[start - 1].head.i == member
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
            starts.add(start)
        parts, current = [], []
        for i in run:
            if i in starts and current:
                parts.append(current)
                current = []
            current.append(i)
        if current:
            parts.append(current)
        return parts if len(parts) > 1 else [run]

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
            for part in split_enumeration(run):
                part_role = role
                if (
                    any(doc[index].dep_ == "cc" for index in part)
                    and all(
                        doc[index].dep_ in ("cc", "punct")
                        for index in part
                    )
                ):
                    part_role = "conjunction"
                # Only multi-item appositive lists get the appositive role; a
                # single appositive after "as a class, an element…" must not
                # demote the whole object NP.
                if (
                    len(enum_members) >= 2
                    and any(i in enum_members for i in part)
                ):
                    part_role = "appositive"
                chunks.append({"text": doc[part[0]: part[-1] + 1].text,
                               "role": part_role, "gloss": "", "children": None,
                               "_lo": part[0], "_hi": part[-1]})
        else:
            crole = clause_roles[o.i]
            kids = build_chunks(
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
        # role; items and their clauses are children revealed on expand.
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


def build_chunks(
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
    for c, role, expand in chunk_roots(head):
        if not parent_span.contains(c.i) or c.i in seen_roots:
            continue
        seen_roots.add(c.i)
        root_specs.append((c, role, expand))
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
    for c, role, expand in root_specs:
        key = f"n{c.i}"
        if role == "__coord_clause__":
            inline.add(key)
        owned_span = constituency.resolve(
            root=c.i,
            role=role,
            parent=parent_span,
            required=(
                boundary_anchors(c, expand, parent_span)
                | absorbed_by_clause.get(c.i, set())
            ),
            blocked=blocked_indices_for_root(c, head, root_specs, parent_span),
            dependency_indices=owned_dependency_indices(c, parent_span, root_specs),
        )
        root_entries[key] = (c, role, expand, owned_span)
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
        c, role, expand, owned_span = root_entries[key]
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
        if key in inline:
            # Coordinate clause. With its own subject it is a full clause:
            # inside a labeled clause it reads best as one collapsible block
            # ("and where I was born"); subject-sharing VP coordination
            # ("and married") splices flat. Top level always splices flat so
            # the header keeps per-role colors on the whole backbone.
            sub = build_chunks(
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
            chunks.append({"text": text, "role": "other", "gloss": "", "children": None})
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
            kids = build_chunks(
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
            splice_flat(build_chunks(
                c,
                doc,
                clause_role_of_head=clause_role_of_head,
                constituency=constituency,
                parent_span=recursive_span,
            ), recursive_span)
        elif role == "object" and not expand:
            chunks.append({"text": text, "role": role, "gloss": "",
                           "children": None, "_lem": c.lemma_})
        elif expand:
            if c.pos_ in ("VERB", "AUX") or role == "absolute":
                # verbal heads recurse fully, wrapped under their clause label;
                # an absolute's adjectival head works the same way — its "verb"
                # run is the elided-be predicate ("dead and gone").
                kids = build_chunks(
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
                    kids = build_chunks(
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
                # via np_expand but re-wrapped so the subject label is not lost.
                sub = np_expand(
                    c, doc, role, constituency, recursive_span,
                )
                if len(sub) == 1:
                    chunks.append(sub[0])
                else:
                    chunks.append({
                        "text": text, "role": "subject", "gloss": "",
                        "children": sub if len(sub) >= 2 else None,
                    })
            elif role == "insertion":
                kids = None
                if c.pos_ in ("VERB", "AUX") or any(
                    t.pos_ in ("VERB", "AUX") for t in c.subtree if t is not c
                ):
                    verbal = c if c.pos_ in ("VERB", "AUX") else next(
                        (t for t in c.subtree if t.pos_ in ("VERB", "AUX")), c
                    )
                    kids = build_chunks(
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
                # keeping the prep-phrase span geometry for np_expand.
                card_role = "adverbial" if is_adverbial_complex_prep(c) else "prep-phrase"
                sub = np_expand(c, doc, role, constituency, recursive_span)
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
                splice_flat(np_expand(
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
    result = mark_discourse_insertions(merge_tiny(merge_or_so(merge_idioms(chunks))))
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
    for left, right in zip(clause_spans, clause_spans[1:]):
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
            and chunk.get("_hi", parent_span.end) < span.end
        ]
        if not positions or positions != list(range(positions[0], positions[-1] + 1)):
            continue
        first, last = positions[0], positions[-1]
        selected = result[first:last + 1]
        if (len(selected) == 1
                and selected[0].get("_lo") == span.start
                and selected[0].get("_hi") == span.end - 1):
            continue
        wrapper = {
            "text": doc[span.start:span.end].text,
            "role": role,
            "gloss": "",
            "children": selected,
            "_lo": span.start,
            "_hi": span.end - 1,
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


def merge_tiny(chunks):
    """Attach punctuation-only chunks to the previous chunk (or the next one
    when they lead)."""
    out = []
    pending = ""
    pending_lo = None
    for ch in chunks:
        if not any(c.isalnum() for c in ch["text"]):
            if out:
                out[-1]["text"] = out[-1]["text"] + ch["text"]
                if "_hi" in ch:
                    out[-1]["_hi"] = ch["_hi"]
            else:
                if pending_lo is None:
                    pending_lo = ch.get("_lo")
                pending += ch["text"]
        else:
            if pending:
                ch = dict(ch, text=pending + ch["text"])
                if pending_lo is not None:
                    ch["_lo"] = pending_lo
                pending = ""
                pending_lo = None
            out.append(ch)
    return out


def _prepare_document(text):
    prepared = prepare_parse_text(text)
    if not prepared.parser:
        raise ValueError("source contains no parseable text")
    with nlp_inference_lock:
        doc = nlp(prepared.parser)
    parser_offsets = [
        (token.idx, token.idx + len(token.text))
        for token in doc
    ]
    offsets = prepared.source_token_offsets(parser_offsets)
    return prepared, doc, offsets


def parse_text(text):
    prepared, doc, offsets = _prepare_document(text)
    constituency = ConstituencyIndex.from_doc(doc)
    all_chunks = []
    last_end = None
    for sent in doc.sents:
        sent_chunks = build_chunks(
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
    source = TokenSource(text=prepared.surface, token_offsets=offsets)
    teaching_chunks = compile_teaching_tree(
        source,
        all_chunks,
        evidence=TeachingEvidence.from_doc(doc),
    )
    chunks = annotate_chunk_spans(prepared.surface, teaching_chunks, offsets)
    # After spans, because a note is chosen by the token a card covers and
    # only the annotated tree knows which token that is.
    annotate_grammar_notes(chunks, doc)
    return chunks, [
        prepared.surface[start:end]
        for start, end in offsets
    ]


def analyze_text(text):
    """Return untouched parser evidence for the constrained Qwen stage."""
    prepared, doc, offsets = _prepare_document(text)
    return build_analysis_evidence(
        doc,
        prepared.surface,
        spacy_model=SPACY_MODEL,
        benepar_model=BENEPAR_MODEL,
        spacy_version=spacy.__version__,
        benepar_version=importlib.metadata.version("benepar"),
        source_token_offsets=offsets,
    )


# ---------------------------------------------------------------- server

app = FastAPI()


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


@app.get("/health", dependencies=[Depends(require_auth)])
def health():
    return {
        "ok": nlp is not None,
        # Keep the legacy key for older app builds while advertising endpoint
        # versions independently so an /analyze-only bump cannot disable
        # otherwise compatible /parse clients.
        "protocolVersion": PARSE_PROTOCOL_VERSION,
        "parseProtocolVersion": PARSE_PROTOCOL_VERSION,
        "analysisProtocolVersion": ANALYSIS_PROTOCOL_VERSION,
    }


@app.post("/analyze", dependencies=[Depends(require_auth)])
def analyze(req: ParseRequest):
    global last_request
    last_request = time.time()
    if len(re.findall(r"\w+|[^\w\s]", req.text)) > 512:
        raise HTTPException(status_code=422, detail="source token limit exceeded")
    if not parse_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="sentence parser is busy")
    try:
        return analyze_text(req.text)
    except (AttributeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        parse_slots.release()


@app.post("/parse", dependencies=[Depends(require_auth)])
def parse(req: ParseRequest):
    global last_request
    last_request = time.time()
    # Reject oversized input before running the transformer/benepar pipeline.
    if len(re.findall(r"\w+|[^\w\s]", req.text)) > 512:
        raise HTTPException(status_code=422, detail="source token limit exceeded")
    if not parse_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="sentence parser is busy")
    try:
        chunks, source_tokens = parse_text(req.text)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        parse_slots.release()
    return {"chunks": chunks, "sourceTokens": source_tokens}


def idle_watchdog(limit):
    while True:
        time.sleep(30)
        if time.time() - last_request > limit:
            # sys.exit() would only stop this watchdog thread. Terminating the
            # process is required to release spaCy and benepar memory.
            os.kill(os.getpid(), signal.SIGTERM)


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=48620)
    # The transformer models cost ~3.2 GB resident but only ~2.7 s to reload,
    # so idling for a quarter of an hour trades a lot of RAM for a saving the
    # user rarely collects. Two minutes still covers a reading session.
    ap.add_argument("--idle-exit", type=int, default=120)
    ap.add_argument(
        "--install-models",
        action="store_true",
        help="explicitly install Benepar data, then exit",
    )
    args = ap.parse_args()
    if args.install_models:
        benepar.download(BENEPAR_MODEL)
        raise SystemExit(0)
    if not auth_token:
        raise SystemExit("THORN_SIDECAR_TOKEN is required")
    load()
    threading.Thread(target=idle_watchdog, args=(args.idle_exit,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")

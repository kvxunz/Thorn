"""Fixtures only -- no model.

This module decides which tokens a Benepar span must contain, which tokens it
must not swallow, and when a dependency edge that escaped a clause is put back.
Every input is a token graph plus a ``TokenSpan``, so fake tokens exercise it
without the 3.2 GB of weights the snapshot needs.
"""
import unittest

from constituency import ConstituencyIndex, TokenSpan
from syntax_boundaries import (
    absorb_misattached_roots_into_clauses,
    blocked_indices_for_root,
    boundary_anchors,
    dependency_indices,
    owned_dependency_indices,
)


class _Token:
    def __init__(self, index, text, pos, tag, dep, head):
        self.i = index
        self.text = text
        self.lower_ = text.lower()
        self.lemma_ = text.lower()
        self.pos_ = pos
        self.tag_ = tag
        self.dep_ = dep
        self.head_index = head
        self.doc = None

    @property
    def head(self):
        return self.doc[self.head_index]

    @property
    def children(self):
        return [token for token in self.doc
                if token.head_index == self.i and token.i != self.i]

    @property
    def subtree(self):
        out = [self]
        pending = list(self.children)
        while pending:
            token = pending.pop()
            out.append(token)
            pending.extend(token.children)
        return sorted(out, key=lambda token: token.i)


class _Doc:
    """The slice of ``spacy.tokens.Doc`` these passes touch."""

    def __init__(self, rows):
        self._tokens = [
            _Token(index, *row) for index, row in enumerate(rows)
        ]
        for token in self._tokens:
            token.doc = self

    def __getitem__(self, index):
        return self._tokens[index]

    def __iter__(self):
        return iter(self._tokens)

    def __len__(self):
        return len(self._tokens)

    @property
    def span(self):
        return TokenSpan(0, len(self._tokens))


def finished_doc():
    """She has not finished the report ."""
    return _Doc([
        ("She", "PRON", "PRP", "nsubj", 3),
        ("has", "AUX", "VBZ", "aux", 3),
        ("not", "PART", "RB", "neg", 3),
        ("finished", "VERB", "VBN", "ROOT", 3),
        ("the", "DET", "DT", "det", 5),
        ("report", "NOUN", "NN", "dobj", 3),
        (".", "PUNCT", ".", "punct", 3),
    ])


class BoundaryAnchorTests(unittest.TestCase):
    def test_a_verb_anchors_its_whole_verb_complex_and_its_arguments(self):
        doc = finished_doc()
        self.assertEqual(
            boundary_anchors(doc[3], False, doc.span),
            {0, 1, 2, 3, 5},
        )

    def test_an_anchor_outside_the_parent_span_is_dropped(self):
        doc = finished_doc()
        self.assertEqual(
            boundary_anchors(doc[3], False, TokenSpan(3, 7)),
            {3, 5},
        )

    def test_an_independent_conjunct_is_not_an_anchor_of_its_head(self):
        doc = _Doc([
            ("He", "PRON", "PRP", "nsubj", 1),
            ("left", "VERB", "VBD", "ROOT", 1),
            ("and", "CCONJ", "CC", "cc", 1),
            ("she", "PRON", "PRP", "nsubj", 4),
            ("stayed", "VERB", "VBD", "conj", 1),
            (".", "PUNCT", ".", "punct", 1),
        ])
        self.assertEqual(boundary_anchors(doc[1], False, doc.span), {0, 1})

    def test_a_conjunct_without_its_own_subject_stays_an_anchor(self):
        doc = _Doc([
            ("He", "PRON", "PRP", "nsubj", 1),
            ("left", "VERB", "VBD", "ROOT", 1),
            ("and", "CCONJ", "CC", "cc", 1),
            ("stayed", "VERB", "VBD", "conj", 1),
            (".", "PUNCT", ".", "punct", 1),
        ])
        self.assertEqual(boundary_anchors(doc[1], False, doc.span), {0, 1, 3})

    def test_an_expandable_nominal_anchors_a_clause_below_its_children(self):
        doc = _Doc([
            ("the", "DET", "DT", "det", 1),
            ("cover", "NOUN", "NN", "ROOT", 1),
            ("of", "ADP", "IN", "prep", 1),
            ("the", "DET", "DT", "det", 4),
            ("book", "NOUN", "NN", "pobj", 2),
            ("that", "PRON", "WDT", "dobj", 6),
            ("wrote", "VERB", "VBD", "relcl", 4),
        ])
        self.assertEqual(boundary_anchors(doc[1], False, doc.span), {1, 2})
        self.assertEqual(boundary_anchors(doc[1], True, doc.span), {1, 2, 6})

    def test_a_noun_anchors_a_following_modifier_but_not_a_preceding_one(self):
        following = _Doc([
            ("people", "NOUN", "NNS", "ROOT", 0),
            ("present", "ADJ", "JJ", "amod", 0),
        ])
        preceding = _Doc([
            ("strange", "ADJ", "JJ", "amod", 1),
            ("people", "NOUN", "NNS", "ROOT", 1),
        ])
        self.assertEqual(boundary_anchors(following[0], False, following.span), {0, 1})
        self.assertEqual(boundary_anchors(preceding[1], False, preceding.span), {1})

    def test_a_preposition_anchors_the_measure_phrase_in_front_of_it(self):
        doc = _Doc([
            ("three", "NUM", "CD", "nummod", 1),
            ("years", "NOUN", "NNS", "npadvmod", 2),
            ("before", "ADP", "IN", "prep", 2),
            ("the", "DET", "DT", "det", 4),
            ("war", "NOUN", "NN", "pobj", 2),
        ])
        self.assertEqual(boundary_anchors(doc[2], False, doc.span), {1, 2})

    def test_an_open_complement_keeps_the_wh_word_below_it(self):
        doc = wh_doc()
        self.assertEqual(boundary_anchors(doc[3], False, doc.span), {2, 3, 4, 6})


def wh_doc():
    """He wanted to know where she went ."""
    return _Doc([
        ("He", "PRON", "PRP", "nsubj", 1),
        ("wanted", "VERB", "VBD", "ROOT", 1),
        ("to", "PART", "TO", "aux", 3),
        ("know", "VERB", "VB", "xcomp", 1),
        ("where", "SCONJ", "WRB", "advmod", 6),
        ("she", "PRON", "PRP", "nsubj", 6),
        ("went", "VERB", "VBD", "ccomp", 3),
    ])


class DependencyProjectionTests(unittest.TestCase):
    def test_the_projection_is_the_whole_subtree(self):
        doc = wh_doc()
        self.assertEqual(dependency_indices(doc[3], doc.span), {2, 3, 4, 5, 6})

    def test_the_projection_is_cut_to_the_parent_span(self):
        doc = wh_doc()
        self.assertEqual(dependency_indices(doc[3], TokenSpan(3, 5)), {3, 4})


def promoted_conj_doc():
    """She said he left and they stayed ."""
    return _Doc([
        ("She", "PRON", "PRP", "nsubj", 1),
        ("said", "VERB", "VBD", "ROOT", 1),
        ("he", "PRON", "PRP", "nsubj", 3),
        ("left", "VERB", "VBD", "ccomp", 1),
        ("and", "CCONJ", "CC", "cc", 3),
        ("they", "PRON", "PRP", "nsubj", 6),
        ("stayed", "VERB", "VBD", "conj", 3),
        (".", "PUNCT", ".", "punct", 1),
    ])


def promoted_conj_specs(doc):
    return [
        (doc[3], "clause-noun", True),
        (doc[6], "clause-noun", True),
    ]


class OwnedProjectionTests(unittest.TestCase):
    def test_a_promoted_descendant_leaves_its_former_parent(self):
        doc = promoted_conj_doc()
        self.assertEqual(
            owned_dependency_indices(doc[3], doc.span, promoted_conj_specs(doc)),
            {2, 3, 4},
        )

    def test_a_peer_that_is_not_a_descendant_takes_nothing_away(self):
        doc = promoted_conj_doc()
        self.assertEqual(
            owned_dependency_indices(doc[6], doc.span, promoted_conj_specs(doc)),
            {5, 6},
        )


class BlockedIndexTests(unittest.TestCase):
    def test_a_promoted_conjunct_is_not_blocked_by_its_former_parent(self):
        doc = promoted_conj_doc()
        blocked = blocked_indices_for_root(
            doc[6], doc[1], promoted_conj_specs(doc), doc.span,
        )
        self.assertEqual(blocked, {1, 2, 3, 4})

    def test_a_sibling_root_blocks_the_tokens_it_owns(self):
        doc = promoted_conj_doc()
        blocked = blocked_indices_for_root(
            doc[3], doc[1], promoted_conj_specs(doc), doc.span,
        )
        self.assertEqual(blocked, {1, 5, 6})

    def test_every_member_of_the_matrix_verb_complex_is_a_barrier(self):
        doc = finished_doc()
        specs = [(doc[5], "object", False)]
        blocked = blocked_indices_for_root(doc[5], doc[3], specs, doc.span)
        self.assertEqual(blocked, {1, 2, 3})


def elliptical_rows(clause_pos="AUX", clause_dep="advcl", mark=True):
    """He will leave as Kelsey will after lunch ."""
    return [
        ("He", "PRON", "PRP", "nsubj", 2),
        ("will", "AUX", "MD", "aux", 2),
        ("leave", "VERB", "VB", "ROOT", 2),
        ("as", "SCONJ", "IN", "mark" if mark else "advmod", 5),
        ("Kelsey", "PROPN", "NNP", "nsubj", 5),
        ("will", clause_pos, "MD", clause_dep, 2),
        ("after", "ADP", "IN", "prep", 2),
        ("lunch", "NOUN", "NN", "pobj", 6),
        (".", "PUNCT", ".", "punct", 2),
    ]


def elliptical_specs(doc):
    return [
        (doc[5], "clause-adverbial", True),
        (doc[6], "prep-phrase", True),
    ]


def sbar(start, end):
    return ConstituencyIndex([TokenSpan(start, end, frozenset({"SBAR"}))])


class AbsorbMisattachedRootTests(unittest.TestCase):
    def test_a_tight_clause_span_takes_back_the_escaped_phrase(self):
        doc = _Doc(elliptical_rows())
        specs, absorbed = absorb_misattached_roots_into_clauses(
            elliptical_specs(doc), doc[2], sbar(3, 8), doc.span,
        )
        self.assertEqual([spec[0].i for spec in specs], [5])
        self.assertEqual(absorbed, {5: {6, 7}})

    def test_a_lexical_predicate_is_not_treated_as_elliptical(self):
        doc = _Doc(elliptical_rows(clause_pos="VERB"))
        specs, absorbed = absorb_misattached_roots_into_clauses(
            elliptical_specs(doc), doc[2], sbar(3, 8), doc.span,
        )
        self.assertEqual([spec[0].i for spec in specs], [5, 6])
        self.assertEqual(absorbed, {})

    def test_a_clause_without_a_subordinator_absorbs_nothing(self):
        doc = _Doc(elliptical_rows(mark=False))
        specs, absorbed = absorb_misattached_roots_into_clauses(
            elliptical_specs(doc), doc[2], sbar(3, 8), doc.span,
        )
        self.assertEqual([spec[0].i for spec in specs], [5, 6])
        self.assertEqual(absorbed, {})

    def test_a_span_that_also_holds_the_matrix_verb_is_not_a_clause_boundary(self):
        doc = _Doc(elliptical_rows())
        specs, absorbed = absorb_misattached_roots_into_clauses(
            elliptical_specs(doc), doc[2], sbar(0, 9), doc.span,
        )
        self.assertEqual([spec[0].i for spec in specs], [5, 6])
        self.assertEqual(absorbed, {})

    def test_a_phrase_that_only_half_fits_the_clause_stays_outside(self):
        doc = _Doc(elliptical_rows())
        specs, absorbed = absorb_misattached_roots_into_clauses(
            elliptical_specs(doc), doc[2], sbar(3, 7), doc.span,
        )
        self.assertEqual([spec[0].i for spec in specs], [5, 6])
        self.assertEqual(absorbed, {})

    def test_one_clause_root_never_swallows_another(self):
        doc = _Doc(elliptical_rows())
        specs = [
            (doc[5], "clause-adverbial", True),
            (doc[6], "clause-relative", True),
        ]
        kept, absorbed = absorb_misattached_roots_into_clauses(
            specs, doc[2], sbar(3, 8), doc.span,
        )
        self.assertEqual([spec[0].i for spec in kept], [5, 6])
        self.assertEqual(absorbed, {})


if __name__ == "__main__":
    unittest.main()

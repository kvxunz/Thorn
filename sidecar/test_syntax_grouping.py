"""Fixtures only -- no model.

These passes take builder chunks (inclusive ``_hi``; see
``teaching_tree._node_from_builder``) plus Benepar spans and regroup them.
Both inputs are plain data, so the whole module is reachable without loading
3.2 GB of weights. Until now it was only exercised through the real-model
snapshot, which meant a 95 s round trip to see a one-line mistake.
"""
import unittest

from constituency import ConstituencyIndex, TokenSpan
from syntax_grouping import (
    coordinated_gerund_subject_children,
    group_colon_enumerations,
    group_constituency_clauses,
    group_explanatory_for_clause,
    merge_idioms,
)


class _Span:
    def __init__(self, tokens):
        self._tokens = tokens

    @property
    def text(self):
        return " ".join(token.text for token in self._tokens)


class _Token:
    def __init__(self, index, text, pos, tag, dep, head):
        self.i = index
        self.text = text
        self.pos_ = pos
        self.tag_ = tag
        self.dep_ = dep
        self.head_index = head
        self.doc = None

    @property
    def head(self):
        return self.doc[self.head_index]


class _Doc:
    """The narrow slice of ``spacy.tokens.Doc`` these passes actually touch."""

    def __init__(self, rows):
        self._tokens = []
        for index, row in enumerate(rows):
            text, pos, tag, dep, head = row if isinstance(row, tuple) else (
                row, "NOUN", "NN", "dep", index
            )
            self._tokens.append(_Token(index, text, pos, tag, dep, head))
        for token in self._tokens:
            token.doc = self

    def __getitem__(self, key):
        if isinstance(key, slice):
            return _Span(self._tokens[key])
        return self._tokens[key]

    def __len__(self):
        return len(self._tokens)


def card(text, role, lo, hi, **extra):
    return {"text": text, "role": role, "gloss": "", "_lo": lo, "_hi": hi, **extra}


class MergeIdiomsTests(unittest.TestCase):
    def test_a_verb_object_idiom_becomes_one_card(self):
        got = merge_idioms([
            card("raise", "verb", 1, 1, _lem="raise"),
            card("eyebrows", "object", 2, 2, _lem="eyebrow"),
        ])
        self.assertEqual([chunk["text"] for chunk in got], ["raise eyebrows"])
        self.assertEqual(got[0]["_hi"], 2)

    def test_the_lemma_hint_never_reaches_the_caller(self):
        # `_lem` exists only so this pass can recognise an idiom. Leaving it on
        # the card would ship a private key into the projection layer.
        got = merge_idioms([card("raise", "verb", 1, 1, _lem="raise")])
        self.assertNotIn("_lem", got[0])

    def test_a_verb_object_pair_that_is_not_an_idiom_stays_split(self):
        got = merge_idioms([
            card("raise", "verb", 1, 1, _lem="raise"),
            card("questions", "object", 2, 2, _lem="question"),
        ])
        self.assertEqual([chunk["text"] for chunk in got], ["raise", "questions"])

    def test_a_compound_preposition_takes_its_adverb_onto_both_cards(self):
        got = merge_idioms([
            card("apart", "adverbial", 0, 0),
            card("from the fact", "prep-phrase", 1, 3, children=[
                card("from", "other", 1, 1),
                card("the fact", "object", 2, 3),
            ]),
        ])
        self.assertEqual([chunk["text"] for chunk in got], ["apart from the fact"])
        self.assertEqual(got[0]["_lo"], 0)
        # "apart" is half of the preposition, so the card that names the
        # preposition has to carry it too -- not only the wrapper above it.
        self.assertEqual(got[0]["children"][0]["text"], "apart from")
        self.assertEqual(got[0]["children"][0]["_lo"], 0)

    def test_an_adverb_that_already_expands_is_not_half_a_preposition(self):
        got = merge_idioms([
            card("apart", "adverbial", 0, 0, children=[card("apart", "other", 0, 0)]),
            card("from the fact", "prep-phrase", 1, 3),
        ])
        self.assertEqual(len(got), 2)

    def test_an_unlisted_adverb_preposition_pair_is_left_alone(self):
        got = merge_idioms([
            card("quietly", "adverbial", 0, 0),
            card("from the fact", "prep-phrase", 1, 3),
        ])
        self.assertEqual(len(got), 2)


COLON_DOC = _Doc([
    "Risk", "is", "pervasive", ":", "an", "aspirin", ",", "some", "wine", ",", "coffee",
])


def colon_chunks():
    return [
        card("Risk", "subject", 0, 0),
        card("is", "verb", 1, 1),
        card("pervasive:", "complement", 2, 3),
        card("an aspirin,", "insertion", 4, 6),
        card("some wine,", "insertion", 7, 9),
        card("coffee", "insertion", 10, 10),
    ]


class ColonEnumerationTests(unittest.TestCase):
    def test_a_post_colon_list_collapses_into_one_expandable_card(self):
        got = group_colon_enumerations(colon_chunks(), COLON_DOC, TokenSpan(0, 11))
        self.assertEqual([chunk["role"] for chunk in got],
                         ["subject", "verb", "complement", "insertion"])
        self.assertEqual(len(got[3]["children"]), 3)

    def test_the_group_card_text_covers_every_token_its_bounds_claim(self):
        # `_hi` is inclusive in the builder layer, so a card announcing 4..10
        # must read through token 10. Slicing `doc[lo:hi]` silently drops the
        # last item of every enumeration -- "coffee" here.
        got = group_colon_enumerations(colon_chunks(), COLON_DOC, TokenSpan(0, 11))
        group = got[3]
        self.assertEqual((group["_lo"], group["_hi"]), (4, 10))
        self.assertEqual(group["text"], COLON_DOC[4:11].text)
        self.assertIn("coffee", group["text"])

    def test_a_single_item_after_the_colon_is_not_a_list(self):
        chunks = colon_chunks()[:4]
        self.assertEqual(group_colon_enumerations(chunks, COLON_DOC, TokenSpan(0, 11)),
                         chunks)

    def test_clause_material_after_the_list_stays_outside_the_group(self):
        chunks = colon_chunks() + [card("and everyone knew", "verb", 11, 13)]
        doc = _Doc(list("x" * 14))
        got = group_colon_enumerations(chunks, doc, TokenSpan(0, 14))
        self.assertEqual(got[-1]["role"], "verb")
        self.assertEqual(got[3]["_hi"], 10)

    def test_text_without_a_colon_is_returned_unchanged(self):
        chunks = [card("Risk", "subject", 0, 0), card("is", "verb", 1, 1),
                  card("pervasive", "complement", 2, 2)]
        self.assertEqual(group_colon_enumerations(chunks, COLON_DOC, TokenSpan(0, 11)),
                         chunks)


# "not because she was hardworking, but because she was unlucky"
SEAM_DOC = _Doc([
    "not", "because", "she", "was", "hardworking", ",",
    "but", "because", "she", "was", "unlucky",
])
# Benepar stops each clause before the comma; merge_tiny glues it on.
SEAM_INDEX = ConstituencyIndex([
    TokenSpan(1, 5, frozenset({"SBAR"})),
    TokenSpan(7, 11, frozenset({"SBAR"})),
])


def seam_chunks():
    return [
        card("not", "adverbial", 0, 0),
        card("because", "conjunction", 1, 1),
        card("she", "subject", 2, 2),
        card("was hardworking,", "verb", 3, 5),
        card("but", "conjunction", 6, 6),
        card("because", "conjunction", 7, 7),
        card("she", "subject", 8, 8),
        card("was unlucky", "verb", 9, 10),
    ]


class ConstituencyClauseGroupingTests(unittest.TestCase):
    def test_coordinated_clauses_are_wrapped_as_siblings(self):
        got = group_constituency_clauses(
            seam_chunks(), "clause-adverbial", SEAM_DOC, SEAM_INDEX, TokenSpan(0, 11)
        )
        self.assertEqual([chunk["role"] for chunk in got],
                         ["adverbial", "clause-adverbial", "conjunction", "clause-adverbial"])

    def test_a_comma_glued_onto_a_card_does_not_eject_it_from_its_clause(self):
        # LEARNINGS #42: comparing raw `_hi` against the Benepar span end drops
        # the card carrying the trailing comma, and the wrapper then reads
        # "because she was" with the complement stranded beside it.
        got = group_constituency_clauses(
            seam_chunks(), "clause-adverbial", SEAM_DOC, SEAM_INDEX, TokenSpan(0, 11)
        )
        wrapper = got[1]
        self.assertEqual((wrapper["_lo"], wrapper["_hi"]), (1, 5))
        self.assertEqual([child["text"] for child in wrapper["children"]],
                         ["because", "she", "was hardworking,"])

    def test_no_token_lives_in_a_wrapper_and_in_a_sibling_at_once(self):
        got = group_constituency_clauses(
            seam_chunks(), "clause-adverbial", SEAM_DOC, SEAM_INDEX, TokenSpan(0, 11)
        )
        seen = set()
        for chunk in got:
            span = set(range(chunk["_lo"], chunk["_hi"] + 1))
            self.assertFalse(span & seen, f"{chunk['text']} repeats tokens {span & seen}")
            seen |= span
        self.assertEqual(seen, set(range(11)))

    def test_clauses_without_a_conjunction_between_them_are_not_grouped(self):
        chunks = [chunk for chunk in seam_chunks() if chunk["text"] != "but"]
        got = group_constituency_clauses(
            chunks, "clause-adverbial", SEAM_DOC, SEAM_INDEX, TokenSpan(0, 11)
        )
        self.assertEqual(got, chunks)

    def test_a_single_benepar_clause_is_not_a_coordinated_family(self):
        index = ConstituencyIndex([TokenSpan(1, 5, frozenset({"SBAR"}))])
        chunks = seam_chunks()
        got = group_constituency_clauses(
            chunks, "clause-adverbial", SEAM_DOC, index, TokenSpan(0, 11)
        )
        self.assertEqual(got, chunks)


# "he stayed home, for it was raining"
FOR_DOC = _Doc(["he", "stayed", "home", ",", "for", "it", "was", "raining"])


def for_chunks():
    return [
        card("he", "subject", 0, 0),
        card("stayed", "verb", 1, 1),
        card("home,", "adverbial", 2, 3),
        card("for", "conjunction", 4, 4),
        card("it", "subject", 5, 5),
        card("was", "verb", 6, 6),
        card("raining", "complement", 7, 7),
    ]


class ExplanatoryForTests(unittest.TestCase):
    def test_an_explanatory_for_clause_becomes_one_branch(self):
        got = group_explanatory_for_clause(
            for_chunks(), FOR_DOC, ConstituencyIndex([]), TokenSpan(0, 8)
        )
        self.assertEqual([chunk["role"] for chunk in got],
                         ["subject", "verb", "adverbial", "clause"])
        self.assertEqual(got[3]["text"], "for it was raining")
        self.assertEqual((got[3]["_lo"], got[3]["_hi"]), (4, 7))

    def test_a_for_without_its_own_subject_and_verb_is_a_preposition(self):
        chunks = [chunk for chunk in for_chunks() if chunk["role"] != "verb"
                  or chunk["_lo"] != 6]
        got = group_explanatory_for_clause(
            chunks, FOR_DOC, ConstituencyIndex([]), TokenSpan(0, 8)
        )
        self.assertEqual(got, chunks)

    def test_a_matrix_clause_without_a_verb_does_not_open_a_for_clause(self):
        chunks = [chunk for chunk in for_chunks() if chunk["_lo"] != 1]
        got = group_explanatory_for_clause(
            chunks, FOR_DOC, ConstituencyIndex([]), TokenSpan(0, 8)
        )
        self.assertEqual(got, chunks)


# "Reading books and writing essays"
GERUND_DOC = _Doc([
    ("Reading", "VERB", "VBG", "csubj", 0),
    ("books", "NOUN", "NNS", "dobj", 0),
    ("and", "CCONJ", "CC", "cc", 0),
    ("writing", "VERB", "VBG", "conj", 0),
    ("essays", "NOUN", "NNS", "dobj", 3),
])
GERUND_INDEX = ConstituencyIndex([
    TokenSpan(0, 5, frozenset({"S"})),
    TokenSpan(3, 5, frozenset({"VP"})),
])


class CoordinatedGerundSubjectTests(unittest.TestCase):
    def test_a_coordinated_gerund_subject_splits_at_its_conjunction(self):
        got = coordinated_gerund_subject_children(
            GERUND_DOC[0], GERUND_DOC, GERUND_INDEX, TokenSpan(0, 5)
        )
        self.assertEqual([(chunk["text"], chunk["role"]) for chunk in got], [
            ("Reading books", "subject"),
            ("and", "conjunction"),
            ("writing essays", "subject"),
        ])
        self.assertEqual([(chunk["_lo"], chunk["_hi"]) for chunk in got],
                         [(0, 1), (2, 2), (3, 4)])

    def test_a_gerund_that_does_not_open_the_span_is_declined(self):
        self.assertIsNone(coordinated_gerund_subject_children(
            GERUND_DOC[3], GERUND_DOC, GERUND_INDEX, TokenSpan(0, 5)
        ))

    def test_without_a_benepar_verb_phrase_the_split_is_declined(self):
        # No VP over "writing essays" means Benepar did not see a second
        # predicate there; guessing one from the dependency chain alone is what
        # this guard exists to prevent.
        index = ConstituencyIndex([TokenSpan(0, 5, frozenset({"S"}))])
        self.assertIsNone(coordinated_gerund_subject_children(
            GERUND_DOC[0], GERUND_DOC, index, TokenSpan(0, 5)
        ))


if __name__ == "__main__":
    unittest.main()

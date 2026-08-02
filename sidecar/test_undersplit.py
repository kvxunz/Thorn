"""Fixtures only -- no model. The corpus run is what exercises real trees."""
import unittest

from teaching_tree import ConstituentEvidence, SyntaxToken, TeachingEvidence
from undersplit import classify_leaf, find_undersplit


def evidence(spec):
    """spec: (text, pos, tag, dep, head) per token."""
    tokens = tuple(
        SyntaxToken(
            index=index,
            text=text,
            lemma=text.lower(),
            pos=pos,
            tag=tag,
            dep=dep,
            head=head,
        )
        for index, (text, pos, tag, dep, head) in enumerate(spec)
    )
    return TeachingEvidence(tokens=tokens, constituents=(ConstituentEvidence(0, len(tokens), frozenset({"S"})),))


# "the committee had already voted" -- subject and its tensed verb in one span.
CLAUSE = evidence([
    ("the", "DET", "DT", "det", 1),
    ("committee", "NOUN", "NN", "nsubj", 4),
    ("had", "AUX", "VBD", "aux", 4),
    ("already", "ADV", "RB", "advmod", 4),
    ("voted", "VERB", "VBN", "ROOT", 4),
])

# "the man in the black hat over there" -- long but genuinely one card.
FLAT_NP = evidence([
    ("the", "DET", "DT", "det", 1),
    ("man", "NOUN", "NN", "ROOT", 1),
    ("in", "ADP", "IN", "prep", 1),
    ("the", "DET", "DT", "det", 5),
    ("black", "ADJ", "JJ", "amod", 5),
    ("hat", "NOUN", "NN", "pobj", 2),
    ("over", "ADV", "RB", "advmod", 1),
    ("there", "ADV", "RB", "advmod", 6),
])


CLAUSE_TOKENS = ["the", "committee", "had", "already", "voted"]


class ClassifyLeafTests(unittest.TestCase):
    def test_a_tensed_verb_with_its_own_subject_is_an_undrawn_clause(self):
        self.assertEqual(classify_leaf(0, 5, CLAUSE), "clause-in-one-card")

    def test_a_subject_whose_verb_lives_in_a_sibling_card_is_fine(self):
        # Same tokens, but the card stops before the verb: this is exactly the
        # subject/predicate split the tree is supposed to produce.
        self.assertIsNone(classify_leaf(0, 2, CLAUSE))

    def test_a_wh_word_marks_a_boundary_the_tree_never_drew(self):
        relative = evidence([
            ("the", "DET", "DT", "det", 1),
            ("people", "NOUN", "NNS", "ROOT", 1),
            ("who", "PRON", "WP", "nsubj", 3),
            ("care", "VERB", "VBP", "relcl", 1),
        ])
        # Reported even though it is under the wide-leaf threshold.
        self.assertEqual(classify_leaf(0, 4, relative), "clause-in-one-card")
        self.assertEqual(classify_leaf(0, 3, relative), "wh-word-in-leaf")

    def test_a_card_that_is_only_the_wh_word_is_a_boundary_drawn_right(self):
        relative = evidence([
            ("the", "DET", "DT", "det", 1),
            ("people", "NOUN", "NNS", "ROOT", 1),
            ("who", "PRON", "WP", "nsubj", 3),
            ("care", "VERB", "VBP", "relcl", 1),
        ])
        # The tree gave "who" its own card: that is the split working.
        self.assertIsNone(classify_leaf(2, 3, relative))

    def test_a_long_flat_noun_phrase_is_only_the_weakest_signal(self):
        self.assertEqual(classify_leaf(0, 8, FLAT_NP), "wide-leaf")

    def test_a_short_phrase_is_not_reported(self):
        self.assertIsNone(classify_leaf(0, 6, FLAT_NP))

    def test_punctuation_does_not_push_a_leaf_over_the_width_threshold(self):
        padded = evidence([
            *[(t.text, t.pos, t.tag, t.dep, t.head) for t in FLAT_NP.tokens[:7]],
            (",", "PUNCT", ",", "punct", 1),
        ])
        self.assertIsNone(classify_leaf(0, 8, padded))


class FindUndersplitTests(unittest.TestCase):
    def test_only_leaves_are_judged(self):
        # A parent that spans the whole clause is fine precisely because it
        # split; judging it too would report every well-formed tree.
        chunks = [{
            "role": "clause-main", "text": "the committee had already voted",
            "s": 0, "e": 5,
            "children": [
                {"role": "subject", "text": "the committee", "s": 0, "e": 2},
                {"role": "verb", "text": "had already voted", "s": 2, "e": 5},
            ],
        }]
        self.assertEqual(find_undersplit(chunks, CLAUSE, CLAUSE_TOKENS), [])

    def test_evidence_from_a_different_document_is_refused(self):
        # A dash or exotic space makes _prepare_document retokenize, so spans
        # built from raw-text evidence read the wrong words -- and still look
        # legal. The token count is what gives it away.
        chunks = [{
            "role": "subject", "text": "the committee", "s": 0, "e": 2,
            "children": None,
        }]
        with self.assertRaisesRegex(ValueError, "different document"):
            find_undersplit(chunks, CLAUSE, CLAUSE_TOKENS[:4])

    def test_normalized_characters_do_not_trip_the_text_check(self):
        # evidence saw "--", the user wrote "—": index-aligned, chars differ.
        dashed = evidence([
            ("--", "PUNCT", ":", "punct", 1),
            ("like", "ADP", "IN", "prep", 1),
        ])
        chunks = [{"role": "insertion", "text": "—like", "s": 0, "e": 2,
                   "children": None}]
        self.assertEqual(find_undersplit(chunks, dashed, ["—", "like"]), [])

    def test_an_undrawn_clause_is_reported_with_its_text(self):
        chunks = [{
            "role": "clause-main", "text": "the committee had already voted",
            "s": 0, "e": 5, "children": None,
        }]
        found = find_undersplit(chunks, CLAUSE, CLAUSE_TOKENS)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].signal, "clause-in-one-card")
        self.assertEqual(found[0].text, "the committee had already voted")


if __name__ == "__main__":
    unittest.main()

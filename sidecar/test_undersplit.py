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

    def test_a_long_flat_noun_phrase_is_not_a_miss_however_long(self):
        # Width alone used to report this, and on a real corpus that buried
        # the true findings under correct cards -- then invited "fixes" that
        # would have split phrases the tree had already got right.
        self.assertIsNone(classify_leaf(0, 8, FLAT_NP))

    def test_a_wide_leaf_holding_a_separator_is_a_boundary_never_drawn(self):
        listed = evidence([
            *[(t.text, t.pos, t.tag, t.dep, t.head) for t in FLAT_NP.tokens[:4]],
            (",", "PUNCT", ",", "punct", 1),
            ("a", "DET", "DT", "det", 6),
            ("friend", "NOUN", "NN", "appos", 1),
            ("of", "ADP", "IN", "prep", 6),
            ("mine", "PRON", "PRP", "pobj", 7),
        ])
        self.assertEqual(classify_leaf(0, 9, listed), "wide-leaf")

    def test_a_wide_leaf_holding_a_clause_dependency_is_reported(self):
        reduced = evidence([
            *[(t.text, t.pos, t.tag, t.dep, t.head) for t in FLAT_NP.tokens[:6]],
            ("bought", "VERB", "VBN", "relcl", 5),
            ("yesterday", "NOUN", "NN", "npadvmod", 6),
            ("downtown", "ADV", "RB", "advmod", 6),
        ])
        self.assertEqual(classify_leaf(0, 9, reduced), "wide-leaf")

    def test_a_subjectless_gerund_inside_a_prep_phrase_is_not_a_miss(self):
        # "no incentives for buying stock in certain industries": `buying` is
        # a pcomp, but with no subject of its own it is a gerund, not a layer.
        gerund = evidence([
            ("no", "DET", "DT", "det", 1),
            ("incentives", "NOUN", "NNS", "attr", 1),
            ("for", "ADP", "IN", "prep", 1),
            ("buying", "VERB", "VBG", "pcomp", 2),
            ("stock", "NOUN", "NN", "dobj", 3),
            ("in", "ADP", "IN", "prep", 3),
            ("certain", "ADJ", "JJ", "amod", 7),
            ("industries", "NOUN", "NNS", "pobj", 5),
        ])
        self.assertIsNone(classify_leaf(0, 8, gerund))

    def test_a_pcomp_with_its_own_subject_is_a_clause_never_shown(self):
        # "no incentives for the government funding research locally" -- the
        # gerund has a subject, so it is a clause. Non-finite on purpose: a
        # tensed verb would trip the stronger clause-in-one-card signal first
        # and this path would never be exercised.
        clausal = evidence([
            ("no", "DET", "DT", "det", 1),
            ("incentives", "NOUN", "NNS", "attr", 1),
            ("for", "ADP", "IN", "prep", 1),
            ("the", "DET", "DT", "det", 4),
            ("government", "NOUN", "NN", "nsubj", 5),
            ("funding", "VERB", "VBG", "pcomp", 2),
            ("research", "NOUN", "NN", "dobj", 5),
            ("locally", "ADV", "RB", "advmod", 5),
        ])
        self.assertEqual(classify_leaf(0, 8, clausal), "wide-leaf")

    def test_a_serial_list_is_one_slot_however_many_commas(self):
        # "in energy, labor, and other inputs of crop production": every comma
        # is followed by a conjunct, so none of them opens a slot.
        serial = evidence([
            ("in", "ADP", "IN", "prep", 1),
            ("energy", "NOUN", "NN", "pobj", 0),
            (",", "PUNCT", ",", "punct", 1),
            ("labor", "NOUN", "NN", "conj", 1),
            (",", "PUNCT", ",", "punct", 1),
            ("and", "CCONJ", "CC", "cc", 1),
            ("other", "ADJ", "JJ", "amod", 7),
            ("inputs", "NOUN", "NNS", "conj", 1),
            ("of", "ADP", "IN", "prep", 7),
            ("crop", "NOUN", "NN", "compound", 10),
            ("production", "NOUN", "NN", "pobj", 8),
        ])
        self.assertIsNone(classify_leaf(0, 11, serial))

    def test_a_list_item_reached_through_its_modifier_still_continues(self):
        # "by The Globe and Mail, January Magazine, and The Tyee": the token
        # after the comma is a bare `compound`, and the dependency that says
        # what it is sits one hop up on "Magazine".
        listed = evidence([
            ("by", "ADP", "IN", "prep", 3),
            ("The", "DET", "DT", "det", 2),
            ("Globe", "PROPN", "NNP", "pobj", 0),
            ("and", "CCONJ", "CC", "cc", 2),
            ("Mail", "PROPN", "NNP", "conj", 2),
            (",", "PUNCT", ",", "punct", 2),
            ("January", "PROPN", "NNP", "compound", 7),
            ("Magazine", "PROPN", "NNP", "conj", 2),
            (",", "PUNCT", ",", "punct", 2),
            ("and", "CCONJ", "CC", "cc", 7),
            ("The", "DET", "DT", "det", 11),
            ("Tyee", "PROPN", "NNP", "conj", 7),
        ])
        self.assertIsNone(classify_leaf(0, 12, listed))

    def test_a_place_name_is_not_an_appositive_worth_a_card(self):
        # "at The Spirit Room in Rossie, New York" -- spaCy calls "York" an
        # appositive of "Rossie". It is an address, not a second naming.
        place = evidence([
            ("at", "ADP", "IN", "prep", 3),
            ("The", "DET", "DT", "det", 3),
            ("Spirit", "PROPN", "NNP", "compound", 3),
            ("Room", "PROPN", "NNP", "pobj", 0),
            ("in", "ADP", "IN", "prep", 3),
            ("Rossie", "PROPN", "NNP", "pobj", 4),
            (",", "PUNCT", ",", "punct", 5),
            ("New", "PROPN", "NNP", "compound", 8),
            ("York", "PROPN", "NNP", "appos", 5),
        ])
        self.assertIsNone(classify_leaf(0, 9, place))

    def test_an_appositive_that_introduces_its_noun_is_still_reported(self):
        # "Lloyd Nickson, a 54-year-old Darwin resident" -- the determiner is
        # what separates a teaching appositive from the address convention.
        named = evidence([
            ("Lloyd", "PROPN", "NNP", "compound", 1),
            ("Nickson", "PROPN", "NNP", "nsubj", 1),
            (",", "PUNCT", ",", "punct", 1),
            ("a", "DET", "DT", "det", 6),
            ("54-year-old", "ADJ", "JJ", "amod", 6),
            ("Darwin", "PROPN", "NNP", "compound", 6),
            ("resident", "NOUN", "NN", "appos", 1),
            ("of", "ADP", "IN", "prep", 6),
            ("the", "DET", "DT", "det", 9),
            ("territory", "NOUN", "NN", "pobj", 7),
        ])
        self.assertEqual(classify_leaf(0, 10, named), "wide-leaf")

    def test_an_exemplifying_comma_still_opens_a_slot(self):
        # "proper adjustment of some parameters, such as penalisation" -- the
        # comma introduces examples, which is a layer, not a continuation.
        exemplified = evidence([
            ("proper", "ADJ", "JJ", "amod", 1),
            ("adjustment", "NOUN", "NN", "nsubj", 1),
            ("of", "ADP", "IN", "prep", 1),
            ("some", "DET", "DT", "det", 4),
            ("parameters", "NOUN", "NNS", "pobj", 2),
            (",", "PUNCT", ",", "punct", 4),
            ("such", "ADJ", "JJ", "amod", 7),
            ("as", "ADP", "IN", "prep", 4),
            ("penalisation", "NOUN", "NN", "pobj", 7),
        ])
        self.assertEqual(classify_leaf(0, 9, exemplified), "wide-leaf")

    def test_an_inserted_she_said_is_one_card_on_purpose(self):
        # "Human nature, they say, is not easily changed by law." The reporting
        # clause is the interruption; showing "they" and "say" as two cards
        # would teach nothing about what interrupted the sentence.
        reported = evidence([
            ("Human", "ADJ", "JJ", "amod", 1),
            ("nature", "NOUN", "NN", "nsubjpass", 9),
            (",", "PUNCT", ",", "punct", 4),
            ("they", "PRON", "PRP", "nsubj", 4),
            ("say", "VERB", "VBP", "parataxis", 9),
            (",", "PUNCT", ",", "punct", 4),
            ("is", "AUX", "VBZ", "auxpass", 9),
            ("not", "PART", "RB", "neg", 9),
            ("easily", "ADV", "RB", "advmod", 9),
            ("changed", "VERB", "VBN", "ROOT", 9),
        ])
        self.assertIsNone(classify_leaf(2, 6, reported))

    def test_a_reporting_clause_keeps_its_particle_and_its_quotes(self):
        # ",” he went on, “" -- the closing quote belongs to the speech, not to
        # the insertion, so its head sits outside the card.
        quoted = evidence([
            ("I", "PRON", "PRP", "nsubj", 1),
            ("got", "VERB", "VBD", "ROOT", 1),
            ("home", "NOUN", "NN", "npadvmod", 1),
            (",", "PUNCT", ",", "punct", 6),
            ("”", "PUNCT", "''", "punct", 6),
            ("he", "PRON", "PRP", "nsubj", 6),
            ("went", "VERB", "VBD", "parataxis", 1),
            ("on", "ADP", "RP", "advmod", 6),
            (",", "PUNCT", ",", "punct", 6),
            ("“", "PUNCT", "``", "punct", 1),
        ])
        self.assertIsNone(classify_leaf(3, 10, quoted))

    def test_an_inserted_clause_with_content_of_its_own_still_splits(self):
        # "--for some reason it was the gloomiest event of my day--" is also
        # `parataxis`, but it says something instead of naming a speaker, so
        # one card really is hiding a layer.
        aside = evidence([
            ("I", "PRON", "PRP", "nsubj", 2),
            ("never", "ADV", "RB", "neg", 2),
            ("saw", "VERB", "VBD", "ROOT", 2),
            ("--", "PUNCT", ":", "punct", 8),
            ("for", "ADP", "IN", "prep", 8),
            ("some", "DET", "DT", "det", 6),
            ("reason", "NOUN", "NN", "pobj", 4),
            ("it", "PRON", "PRP", "nsubj", 8),
            ("was", "AUX", "VBD", "parataxis", 2),
            ("the", "DET", "DT", "det", 10),
            ("event", "NOUN", "NN", "attr", 8),
            ("--", "PUNCT", ":", "punct", 8),
        ])
        self.assertEqual(classify_leaf(3, 12, aside), "clause-in-one-card")

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

    def test_a_card_that_names_both_slots_is_not_a_miss(self):
        # "I'm supposed" holds a subject and a verb and says so. There is no
        # split to draw -- the boundary is inside a written word -- so
        # reporting it invites a fix that does not exist.
        chunks = [{
            "role": "subject-verb", "text": "the committee had already voted",
            "s": 0, "e": 5, "children": None,
        }]
        self.assertEqual(find_undersplit(chunks, CLAUSE, CLAUSE_TOKENS), [])

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

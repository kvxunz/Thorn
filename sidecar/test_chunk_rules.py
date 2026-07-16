import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from chunk_rules import (
    is_clausal_pcomp,
    is_comitative_participle,
    is_concessive_however_clause,
    is_fixed_adverbial_particle,
    is_left_edge_introducer,
    is_left_edge_introducer_token,
    merge_or_so,
    split_false_list_appos_subject,
    verb_group_indices,
)


class _FakeTok:
    def __init__(self, tag, lemma, children=None):
        self.tag_ = tag
        self.lemma_ = lemma
        self.children = children or []


class _FakeChild:
    def __init__(self, dep, lower):
        self.dep_ = dep
        self.lower_ = lower
        self.text = lower


class ChunkRuleTests(unittest.TestCase):
    def test_look_back_stays_in_the_verb_group(self):
        self.assertTrue(is_fixed_adverbial_particle("look", "back", "advmod"))
        self.assertFalse(is_fixed_adverbial_particle("look", "only", "advmod"))

    def test_however_degree_clause_overrides_false_relative_attachment(self):
        tokens = [
            ("however", "advmod", "SCONJ", "ADJ", "RB"),
            ("disputable", "acomp", "ADJ", "AUX", "JJ"),
            ("results", "nsubj", "NOUN", "AUX", "NNS"),
            ("be", "relcl", "AUX", "NOUN", "VB"),
        ]

        self.assertTrue(is_concessive_however_clause("relcl", tokens))

    def test_real_relative_clause_is_not_overridden(self):
        tokens = [
            ("which", "nsubj", "PRON", "VERB", "WDT"),
            ("seems", "relcl", "VERB", "NOUN", "VBZ"),
            ("irritating", "acomp", "ADJ", "VERB", "JJ"),
        ]

        self.assertFalse(is_concessive_however_clause("relcl", tokens))


class ComitativeParticipleTests(unittest.TestCase):
    def test_coupled_with_is_comitative(self):
        tok = _FakeTok("VBN", "couple", [_FakeChild("prep", "with")])
        self.assertTrue(is_comitative_participle(tok))

    def test_written_by_is_not_comitative(self):
        tok = _FakeTok("VBN", "write", [_FakeChild("agent", "by")])
        self.assertFalse(is_comitative_participle(tok))


class _VGTok:
    """Minimal spaCy-like token for verb_group_indices unit tests."""

    def __init__(self, i, text, dep, head_i, doc_ref, lemma=None):
        self.i = i
        self.text = text
        self.dep_ = dep
        self._head_i = head_i
        self.lemma_ = lemma or text.lower()
        self._doc_ref = doc_ref

    @property
    def doc(self):
        return self._doc_ref

    @property
    def head(self):
        return self._doc_ref[self._head_i]

    @property
    def children(self):
        return [t for t in self._doc_ref if t._head_i == self.i and t.i != self.i]


def _make_doc(specs):
    """specs: list of (text, dep, head_i)."""
    doc = []
    for i, (text, dep, head_i) in enumerate(specs):
        doc.append(_VGTok(i, text, dep, head_i, doc))
    return doc


class VerbGroupTests(unittest.TestCase):
    def test_would_almost_certainly_bring_is_one_group(self):
        # indices: 0 would aux→3, 1 almost advmod→2, 2 certainly advmod→3, 3 bring ROOT
        doc = _make_doc([
            ("would", "aux", 3),
            ("almost", "advmod", 2),
            ("certainly", "advmod", 3),
            ("bring", "ROOT", 3),
        ])
        got = verb_group_indices(doc[3])
        self.assertEqual(got, {0, 1, 2, 3})

    def test_can_hardly_be_classed_sandwich(self):
        # can aux, hardly advmod→classed, be aux, classed
        doc = _make_doc([
            ("can", "aux", 3),
            ("hardly", "advmod", 3),
            ("be", "aux", 3),
            ("classed", "ROOT", 3),
        ])
        self.assertEqual(verb_group_indices(doc[3]), {0, 1, 2, 3})

    def test_postverbal_adverb_stays_out(self):
        # bring carefully — carefully after verb, not mid-complex
        doc = _make_doc([
            ("would", "aux", 1),
            ("bring", "ROOT", 1),
            ("carefully", "advmod", 1),
        ])
        self.assertEqual(verb_group_indices(doc[1]), {0, 1})

    def test_no_aux_does_not_swallow_preverbal_adverbs(self):
        # almost certainly bring with no aux — leave degree adverbs free
        doc = _make_doc([
            ("almost", "advmod", 1),
            ("certainly", "advmod", 2),
            ("bring", "ROOT", 2),
        ])
        self.assertEqual(verb_group_indices(doc[2]), {2})


class OrSoAndWhenTests(unittest.TestCase):
    def test_when_is_left_edge_introducer_token(self):
        class T:
            lower_ = "when"
            dep_ = "advmod"
        self.assertTrue(is_left_edge_introducer_token(T()))

    def test_when_left_of_xcomp_holding_is_stripped(self):
        """when juries began holding… — when must not nest under holding."""
        class Holding:
            i = 19
            dep_ = "xcomp"

        class When:
            i = 16
            lower_ = "when"
            dep_ = "advmod"

        self.assertTrue(is_left_edge_introducer(When(), Holding()))

    def test_when_on_finite_advcl_is_not_stripped_from_host(self):
        class Began:
            i = 18
            dep_ = "advcl"

        class When:
            i = 16
            lower_ = "when"
            dep_ = "advmod"

        # Finite advcl is not a lower non-finite host for the strip rule.
        self.assertFalse(is_left_edge_introducer(When(), Began()))

    def test_merge_or_so_fuses_discourse_hedge(self):
        chunks = [
            {"text": "or", "role": "conjunction", "gloss": "", "children": None},
            {"text": "so", "role": "adverbial", "gloss": "", "children": None},
            {"text": "the ad", "role": "subject", "gloss": "", "children": None},
        ]
        out = merge_or_so(chunks)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["text"], "or so")
        self.assertEqual(out[0]["role"], "insertion")
        self.assertEqual(out[0]["gloss"], "")


class SplitFalseListApposTests(unittest.TestCase):
    def test_splits_bmw_list_from_the_locations_subject(self):
        chunks = [
            {
                "text": "summer homes, European travel, BMWs the locations, "
                        "place names and name brands",
                "role": "subject",
                "gloss": "",
                "children": None,
            },
            {"text": "may change", "role": "verb", "gloss": "", "children": None},
        ]
        out = split_false_list_appos_subject(chunks)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["role"], "insertion")
        self.assertEqual(out[0]["text"], "summer homes, European travel, BMWs")
        self.assertEqual(out[1]["role"], "subject")
        self.assertTrue(out[1]["text"].startswith("the locations"))
        self.assertEqual(out[2]["role"], "verb")

    def test_does_not_split_normal_coordinated_the_subjects(self):
        chunks = [{
            "text": "the locations, the names and the brands",
            "role": "subject",
            "gloss": "",
            "children": None,
        }]
        out = split_false_list_appos_subject(chunks)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "subject")


class _PcompTok:
    def __init__(self, dep, pos, child_deps=()):
        self.dep_ = dep
        self.pos_ = pos
        self.children = [_FakeChild(dep, "") for dep in child_deps]


class ClausalPcompTests(unittest.TestCase):
    def test_pcomp_with_own_subject_is_a_clause(self):
        # "in how well it can control expression" — control: pcomp, VERB, nsubj it
        self.assertTrue(is_clausal_pcomp(_PcompTok("pcomp", "VERB", ("advmod", "nsubj", "dobj"))))

    def test_subjectless_gerund_pcomp_stays_flat(self):
        # "in doing so" — no own subject
        self.assertFalse(is_clausal_pcomp(_PcompTok("pcomp", "VERB", ("dobj",))))

    def test_non_pcomp_and_non_verbal_are_rejected(self):
        self.assertFalse(is_clausal_pcomp(_PcompTok("pobj", "NOUN", ("nsubj",))))
        self.assertFalse(is_clausal_pcomp(_PcompTok("pcomp", "NOUN", ("nsubj",))))


if __name__ == "__main__":
    unittest.main()

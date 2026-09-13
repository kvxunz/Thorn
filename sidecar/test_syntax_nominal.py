"""Fixtures only -- no model.

``analyze_nominal`` cuts a noun phrase into cards using punctuation and
appositive structure, and hands each embedded clause to a callback. The
callback and the Benepar index are both parameters, so a stub for each makes
the whole splitter reachable without weights.
"""
import unittest

from constituency import TokenSpan
from syntax_nominal import analyze_nominal, split_prep_core


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
    def __init__(self, rows):
        self._tokens = [_Token(index, *row) for index, row in enumerate(rows)]
        for token in self._tokens:
            token.doc = self

    def __getitem__(self, key):
        if isinstance(key, slice):
            return _Span(self._tokens[key])
        return self._tokens[key]

    def __iter__(self):
        return iter(self._tokens)

    def __len__(self):
        return len(self._tokens)

    @property
    def span(self):
        return TokenSpan(0, len(self._tokens))


class _Constituency:
    """Answers the one question ``analyze_nominal`` asks of Benepar."""

    def __init__(self, spans=None):
        self._spans = spans or {}

    def resolve(self, *, root, role, parent, required, blocked, dependency_indices):
        return self._spans.get(root, parent)


class _ClauseRecorder:
    """Stands in for ``analyze_clause`` and keeps what it was asked."""

    def __init__(self, children=()):
        self.children = list(children)
        self.calls = []

    def __call__(self, head, doc, *, clause_role_of_head, constituency, parent_span):
        self.calls.append((head.i, clause_role_of_head, parent_span))
        return [dict(child) for child in self.children]


def kid(text):
    return {"text": text, "role": "other", "gloss": "", "children": None}


def run_nominal(doc, head_index, role, constituency=None, clauses=None, span=None):
    recorder = clauses or _ClauseRecorder()
    chunks = analyze_nominal(
        doc[head_index],
        doc,
        role,
        constituency or _Constituency(),
        span or doc.span,
        analyze_clause=recorder,
    )
    return chunks, recorder


class PlainNominalTests(unittest.TestCase):
    def test_a_phrase_without_a_clause_stays_one_card(self):
        doc = _Doc([
            ("the", "DET", "DT", "det", 3),
            ("tired", "ADJ", "JJ", "amod", 3),
            ("old", "ADJ", "JJ", "amod", 3),
            ("dog", "NOUN", "NN", "ROOT", 3),
        ])
        chunks, recorder = run_nominal(doc, 3, "subject")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["role"], "subject")
        self.assertEqual((chunks[0]["_lo"], chunks[0]["_hi"]), (0, 3))
        self.assertEqual(recorder.calls, [])


def relative_doc():
    """the decision that surprised everyone"""
    return _Doc([
        ("the", "DET", "DT", "det", 1),
        ("decision", "NOUN", "NN", "ROOT", 1),
        ("that", "PRON", "WDT", "nsubj", 3),
        ("surprised", "VERB", "VBD", "relcl", 1),
        ("everyone", "PRON", "NN", "dobj", 3),
    ])


class EmbeddedClauseTests(unittest.TestCase):
    def test_an_embedded_clause_becomes_its_own_card(self):
        doc = relative_doc()
        constituency = _Constituency({3: TokenSpan(2, 5)})
        clauses = _ClauseRecorder([kid("that"), kid("surprised everyone")])
        chunks, recorder = run_nominal(doc, 1, "object", constituency, clauses)
        self.assertEqual([chunk["role"] for chunk in chunks],
                         ["object", "clause-relative"])
        self.assertEqual((chunks[0]["_lo"], chunks[0]["_hi"]), (0, 1))
        self.assertEqual((chunks[1]["_lo"], chunks[1]["_hi"]), (2, 4))
        self.assertEqual(recorder.calls,
                         [(3, "clause-relative", TokenSpan(2, 5))])
        self.assertEqual(len(chunks[1]["children"]), 2)

    def test_a_clause_the_callback_cannot_split_keeps_no_children(self):
        doc = relative_doc()
        constituency = _Constituency({3: TokenSpan(2, 5)})
        chunks, _ = run_nominal(doc, 1, "object", constituency,
                                _ClauseRecorder([kid("that surprised everyone")]))
        self.assertIsNone(chunks[1]["children"])

    def test_each_conjunct_keeps_its_own_subject(self):
        doc = _Doc([
            ("people", "NOUN", "NNS", "ROOT", 0),
            ("who", "PRON", "WP", "nsubj", 3),
            ("had", "AUX", "VBD", "aux", 3),
            ("retired", "VERB", "VBN", "relcl", 0),
            ("and", "CCONJ", "CC", "cc", 3),
            ("who", "PRON", "WP", "nsubj", 6),
            ("had", "VERB", "VBD", "conj", 3),
            ("relations", "NOUN", "NNS", "dobj", 6),
        ])
        # Both SBARs open at the first `who`: the overwide one must give the
        # second subject back before either clause is recursed.
        constituency = _Constituency({3: TokenSpan(1, 8), 6: TokenSpan(5, 8)})
        chunks, recorder = run_nominal(doc, 0, "subject", constituency)
        self.assertEqual([(call[0], call[2]) for call in recorder.calls],
                         [(3, TokenSpan(1, 5)), (6, TokenSpan(5, 8))])
        claimed = [index for chunk in chunks
                   for index in range(chunk["_lo"], chunk["_hi"] + 1)]
        self.assertEqual(sorted(claimed), list(range(len(doc))))
        self.assertEqual(len(claimed), len(set(claimed)))


class AppositiveTests(unittest.TestCase):
    def test_a_fenced_renaming_gets_its_own_card(self):
        doc = _Doc([
            ("Lloyd", "PROPN", "NNP", "compound", 1),
            ("Nickson", "PROPN", "NNP", "ROOT", 1),
            (",", "PUNCT", ",", "punct", 1),
            ("a", "DET", "DT", "det", 4),
            ("resident", "NOUN", "NN", "appos", 1),
        ])
        chunks, _ = run_nominal(doc, 1, "subject")
        self.assertEqual([chunk["role"] for chunk in chunks],
                         ["subject", "appositive"])
        self.assertEqual([chunk["_lo"] for chunk in chunks], [0, 2])

    def test_a_bare_renaming_is_one_phrase(self):
        doc = _Doc([
            ("the", "DET", "DT", "det", 1),
            ("poet", "NOUN", "NN", "ROOT", 1),
            ("Milton", "PROPN", "NNP", "appos", 1),
        ])
        chunks, _ = run_nominal(doc, 1, "subject")
        self.assertEqual(len(chunks), 1)

    def test_an_enumeration_collapses_under_the_parent_role(self):
        doc = _Doc([
            ("the", "DET", "DT", "det", 1),
            ("version", "NOUN", "NN", "ROOT", 1),
            (":", "PUNCT", ":", "punct", 1),
            ("the", "DET", "DT", "det", 4),
            ("poverty", "NOUN", "NN", "appos", 1),
            (";", "PUNCT", ":", "punct", 1),
            ("the", "DET", "DT", "det", 7),
            ("father", "NOUN", "NN", "appos", 1),
        ])
        chunks, _ = run_nominal(doc, 1, "object")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["role"], "object")
        self.assertEqual((chunks[0]["_lo"], chunks[0]["_hi"]), (0, 7))
        self.assertEqual([child["role"] for child in chunks[0]["children"]],
                         ["object", "appositive", "appositive"])

    def test_a_parenthesis_is_never_cut_open(self):
        doc = _Doc([
            ("the", "DET", "DT", "det", 1),
            ("town", "NOUN", "NN", "ROOT", 1),
            ("(", "PUNCT", "-LRB-", "punct", 3),
            ("Seaside", "PROPN", "NNP", "appos", 1),
            (",", "PUNCT", ",", "punct", 5),
            ("Florida", "PROPN", "NNP", "conj", 3),
            (")", "PUNCT", "-RRB-", "punct", 3),
        ])
        chunks, _ = run_nominal(doc, 1, "subject")
        children = chunks[0]["children"]
        self.assertEqual([child["role"] for child in children],
                         ["subject", "insertion"])
        self.assertEqual(children[1]["text"], "( Seaside , Florida )")


class CommaSupplementTests(unittest.TestCase):
    def test_a_supplement_that_is_a_prepositional_phrase_is_named_so(self):
        doc = _Doc([
            ("cognitive", "ADJ", "JJ", "amod", 1),
            ("disability", "NOUN", "NN", "ROOT", 1),
            (",", "PUNCT", ",", "punct", 1),
            ("including", "ADP", "VBG", "prep", 1),
            ("deficits", "NOUN", "NNS", "pobj", 3),
            ("in", "ADP", "IN", "prep", 4),
            ("learning", "NOUN", "NN", "pobj", 5),
        ])
        chunks, _ = run_nominal(doc, 1, "object")
        self.assertEqual([chunk["role"] for chunk in chunks],
                         ["object", "prep-phrase"])
        self.assertEqual(chunks[1]["_lo"], 2)

    def test_a_supplement_that_is_not_a_phrase_of_its_own_kind_is_an_insertion(self):
        doc = _Doc([
            ("tip", "NOUN", "NN", "ROOT", 0),
            (",", "PUNCT", ",", "punct", 0),
            ("only", "ADV", "RB", "advmod", 4),
            ("fifty", "NUM", "CD", "nummod", 4),
            ("yards", "NOUN", "NNS", "npadvmod", 0),
            ("from", "ADP", "IN", "prep", 4),
            ("the", "DET", "DT", "det", 7),
            ("Sound", "PROPN", "NNP", "pobj", 5),
        ])
        chunks, _ = run_nominal(doc, 0, "object")
        self.assertEqual([chunk["role"] for chunk in chunks],
                         ["object", "insertion"])

    def test_a_comma_between_numbers_joins_them(self):
        doc = _Doc([
            ("March", "PROPN", "NNP", "ROOT", 0),
            ("16", "NUM", "CD", "nummod", 0),
            (",", "PUNCT", ",", "punct", 0),
            ("1998", "NUM", "CD", "npadvmod", 0),
        ])
        chunks, _ = run_nominal(doc, 0, "object")
        self.assertEqual(len(chunks), 1)

    def test_the_next_item_of_a_list_is_not_a_supplement(self):
        doc = _Doc([
            ("incentives", "NOUN", "NNS", "ROOT", 0),
            (",", "PUNCT", ",", "punct", 0),
            ("and", "CCONJ", "CC", "cc", 0),
            ("resources", "NOUN", "NNS", "conj", 0),
        ])
        chunks, _ = run_nominal(doc, 0, "object")
        self.assertEqual(len(chunks), 1)


def prep_doc():
    """from the fact"""
    return _Doc([
        ("from", "ADP", "IN", "prep", 0),
        ("the", "DET", "DT", "det", 2),
        ("fact", "NOUN", "NN", "pobj", 0),
    ])


def core(lo, hi, doc, role="prep-phrase", children=None):
    return {"text": doc[lo:hi + 1].text, "role": role, "gloss": "",
            "children": children, "_lo": lo, "_hi": hi}


class PrepCoreTests(unittest.TestCase):
    def test_a_wrapper_core_is_named_preposition_plus_object(self):
        doc = prep_doc()
        tail = {"text": "that …", "role": "clause-noun", "gloss": "",
                "children": None, "_lo": 3, "_hi": 5}
        result = split_prep_core([core(0, 2, doc), tail], doc[0], doc)
        self.assertEqual([chunk["role"] for chunk in result],
                         ["prep-phrase", "object", "clause-noun"])
        self.assertEqual(result[0]["text"], "from")
        self.assertEqual(result[1]["text"], "the fact")
        self.assertEqual(result[2], tail)

    def test_a_phrase_that_stays_one_card_is_left_alone(self):
        doc = prep_doc()
        expanded = [core(0, 2, doc, children=[kid("from"), kid("the fact")])]
        self.assertEqual(split_prep_core(expanded, doc[0], doc), expanded)

    def test_a_compound_preposition_is_not_cut_at_its_light_noun(self):
        doc = _Doc([
            ("in", "ADP", "IN", "prep", 0),
            ("spite", "NOUN", "NN", "pobj", 0),
            ("of", "ADP", "IN", "prep", 1),
            ("the", "DET", "DT", "det", 4),
            ("rain", "NOUN", "NN", "pobj", 2),
        ])
        sub = [core(0, 4, doc)]
        self.assertEqual(split_prep_core(sub, doc[0], doc), sub)


if __name__ == "__main__":
    unittest.main()

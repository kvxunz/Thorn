"""Fixtures only -- no model.

``analyze_clause`` assigns every token of a span to exactly one card, then
decides how each card is named and whether it opens. ``ConstituencyIndex``
holds nothing but spans, so the real resolver runs here; only the tokens are
fakes. The invariant checked after every case is the one the Swift side
re-checks before it draws: the cards tile the span, once each.
"""
import unittest

from constituency import ConstituencyIndex, TokenSpan
from syntax_clause import analyze_clause

NO_SPACE_BEFORE = frozenset({",", ".", ";", ":", "!", "?", ")", "]", "'s", "'"})
NO_SPACE_AFTER = frozenset({"(", "["})


class _Span:
    def __init__(self, doc, tokens):
        self._doc = doc
        self._tokens = tokens

    @property
    def text(self):
        if not self._tokens:
            return ""
        first, last = self._tokens[0], self._tokens[-1]
        return self._doc.text[first.idx: last.idx + len(last.text)]


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
        self.idx = 0
        self.doc = None

    @property
    def head(self):
        return self.doc[self.head_index]

    @property
    def ancestors(self):
        node = self
        while node.head_index != node.i:
            node = self.doc[node.head_index]
            yield node

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
    """Written the way the sentence would be, so card text matches slices."""

    def __init__(self, rows):
        self._tokens = [_Token(index, *row) for index, row in enumerate(rows)]
        pieces = []
        offset = 0
        for position, token in enumerate(self._tokens):
            previous = self._tokens[position - 1].text if position else None
            if position and token.text not in NO_SPACE_BEFORE and previous not in NO_SPACE_AFTER:
                pieces.append(" ")
                offset += 1
            token.idx = offset
            token.doc = self
            pieces.append(token.text)
            offset += len(token.text)
        self.text = "".join(pieces)

    def __getitem__(self, key):
        if isinstance(key, slice):
            return _Span(self, self._tokens[key])
        return self._tokens[key]

    def __iter__(self):
        return iter(self._tokens)

    def __len__(self):
        return len(self._tokens)

    @property
    def span(self):
        return TokenSpan(0, len(self._tokens))


def index(*spans):
    """A Benepar index from ``(start, end, label…)`` triples."""
    return ConstituencyIndex([
        TokenSpan(start, end, frozenset(labels)) for start, end, *labels in spans
    ])


class ClauseTestCase(unittest.TestCase):
    def cards(self, doc, head, span=None, role=None, constituency=None):
        chunks = analyze_clause(
            doc[head],
            doc,
            clause_role_of_head=role,
            constituency=constituency or index(),
            parent_span=span or doc.span,
        )
        self.assert_tiles(chunks, span or doc.span)
        return chunks

    def assert_tiles(self, chunks, span):
        covered = []
        for chunk in chunks:
            self.assertIn("_lo", chunk, chunk)
            covered.extend(range(chunk["_lo"], chunk["_hi"] + 1))
        self.assertEqual(covered, list(range(span.start, span.end)))

    def roles(self, chunks):
        return [chunk["role"] for chunk in chunks]

    def texts(self, chunks):
        return [chunk["text"] for chunk in chunks]


class BackboneTests(ClauseTestCase):
    def test_a_plain_sentence_becomes_subject_verb_object(self):
        doc = _Doc([
            ("The", "DET", "DT", "det", 1),
            ("dog", "NOUN", "NN", "nsubj", 2),
            ("chased", "VERB", "VBD", "ROOT", 2),
            ("the", "DET", "DT", "det", 4),
            ("cat", "NOUN", "NN", "dobj", 2),
            (".", "PUNCT", ".", "punct", 2),
        ])
        chunks = self.cards(doc, 2)
        self.assertEqual(self.roles(chunks), ["subject", "verb", "object"])
        self.assertEqual(self.texts(chunks), ["The dog", "chased", "the cat."])

    def test_the_whole_verb_complex_is_one_card(self):
        doc = _Doc([
            ("She", "PRON", "PRP", "nsubj", 3),
            ("has", "AUX", "VBZ", "aux", 3),
            ("not", "PART", "RB", "neg", 3),
            ("finished", "VERB", "VBN", "ROOT", 3),
            ("the", "DET", "DT", "det", 5),
            ("report", "NOUN", "NN", "dobj", 3),
            (".", "PUNCT", ".", "punct", 3),
        ])
        chunks = self.cards(doc, 3)
        self.assertEqual(self.texts(chunks),
                         ["She", "has not finished", "the report."])

    def test_no_internal_hint_reaches_the_caller(self):
        doc = _Doc([
            ("They", "PRON", "PRP", "nsubj", 1),
            ("made", "VERB", "VBD", "ROOT", 1),
            ("progress", "NOUN", "NN", "dobj", 1),
            (".", "PUNCT", ".", "punct", 1),
        ])
        for chunk in self.cards(doc, 1):
            self.assertNotIn("_lem", chunk)

    def test_a_head_outside_its_span_is_refused(self):
        doc = _Doc([
            ("Rain", "NOUN", "NN", "nsubj", 1),
            ("fell", "VERB", "VBD", "ROOT", 1),
        ])
        with self.assertRaises(ValueError):
            analyze_clause(doc[1], doc, parent_span=TokenSpan(0, 1),
                           constituency=index())


class IntroducerTests(ClauseTestCase):
    def test_a_relative_pronoun_is_named_and_glossed(self):
        doc = _Doc([
            ("the", "DET", "DT", "det", 1),
            ("man", "NOUN", "NN", "ROOT", 1),
            ("who", "PRON", "WP", "nsubj", 3),
            ("called", "VERB", "VBD", "relcl", 1),
            ("me", "PRON", "PRP", "dobj", 3),
        ])
        chunks = self.cards(doc, 3, TokenSpan(2, 5), "clause-relative")
        self.assertEqual(self.roles(chunks), ["relative", "verb", "object"])
        self.assertTrue(chunks[0]["gloss"])

    def test_a_subordinator_is_a_conjunction(self):
        doc = _Doc([
            ("because", "SCONJ", "IN", "mark", 2),
            ("he", "PRON", "PRP", "nsubj", 2),
            ("left", "VERB", "VBD", "ROOT", 2),
        ])
        chunks = self.cards(doc, 2, role="clause-adverbial")
        self.assertEqual(self.roles(chunks), ["conjunction", "subject", "verb"])

    def test_a_multi_word_subordinator_stays_one_connective(self):
        doc = _Doc([
            ("He", "PRON", "PRP", "nsubj", 1),
            ("waited", "VERB", "VBD", "ROOT", 1),
            ("as", "ADV", "RB", "advmod", 3),
            ("long", "ADV", "RB", "advmod", 1),
            ("as", "SCONJ", "IN", "mark", 6),
            ("she", "PRON", "PRP", "nsubj", 6),
            ("stayed", "VERB", "VBD", "advcl", 3),
            (".", "PUNCT", ".", "punct", 1),
        ])
        chunks = self.cards(doc, 6, TokenSpan(2, 7), "clause-adverbial")
        self.assertEqual(chunks[0]["text"], "as long as")
        self.assertEqual(chunks[0]["role"], "conjunction")


class EmbeddedClauseTests(ClauseTestCase):
    def test_an_object_clause_after_its_verb_keeps_its_own_card(self):
        doc = _Doc([
            ("He", "PRON", "PRP", "nsubj", 1),
            ("said", "VERB", "VBD", "ROOT", 1),
            ("he", "PRON", "PRP", "nsubj", 4),
            ("would", "AUX", "MD", "aux", 4),
            ("come", "VERB", "VB", "ccomp", 1),
            (".", "PUNCT", ".", "punct", 1),
        ])
        chunks = self.cards(doc, 1)
        self.assertEqual(self.roles(chunks), ["subject", "verb", "clause-noun"])
        self.assertEqual(self.roles(chunks[2]["children"]), ["subject", "verb"])


def coordinated_doc():
    """She opened the door and he walked in."""
    return _Doc([
        ("She", "PRON", "PRP", "nsubj", 1),
        ("opened", "VERB", "VBD", "ROOT", 1),
        ("the", "DET", "DT", "det", 3),
        ("door", "NOUN", "NN", "dobj", 1),
        ("and", "CCONJ", "CC", "cc", 1),
        ("he", "PRON", "PRP", "nsubj", 6),
        ("walked", "VERB", "VBD", "conj", 1),
        ("in", "ADV", "RB", "advmod", 6),
        (".", "PUNCT", ".", "punct", 6),
    ])


class CoordinationTests(ClauseTestCase):
    def test_a_top_level_conjunct_keeps_the_backbone_flat(self):
        chunks = self.cards(coordinated_doc(), 1)
        self.assertEqual(
            self.roles(chunks),
            ["subject", "verb", "object", "conjunction", "subject", "verb",
             "adverbial"],
        )

    def test_a_conjunct_inside_a_labelled_clause_is_one_block(self):
        chunks = self.cards(coordinated_doc(), 1, role="clause-noun")
        self.assertEqual(
            self.roles(chunks),
            ["subject", "verb", "object", "conjunction", "clause-noun"],
        )
        self.assertEqual(chunks[-1]["text"], "he walked in.")


class BracketTests(ClauseTestCase):
    def test_a_parenthesis_becomes_one_aside_of_its_own(self):
        doc = _Doc([
            ("The", "DET", "DT", "det", 1),
            ("novel", "NOUN", "NN", "nsubj", 5),
            ("(", "PUNCT", "-LRB-", "punct", 3),
            ("2000", "NUM", "CD", "npadvmod", 1),
            (")", "PUNCT", "-RRB-", "punct", 3),
            ("sold", "VERB", "VBD", "ROOT", 5),
            ("well", "ADV", "RB", "advmod", 5),
            (".", "PUNCT", ".", "punct", 5),
        ])
        # Benepar stops the subject NP at the bracket; without this pass the
        # card would read "novel (".
        chunks = self.cards(doc, 5, constituency=index((0, 2, "NP")))
        self.assertEqual(self.texts(chunks)[:2], ["The novel", "(2000)"])
        self.assertEqual(self.roles(chunks)[:2], ["subject", "insertion"])


if __name__ == "__main__":
    unittest.main()

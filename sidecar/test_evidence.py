import unittest

from evidence import build_analysis_evidence


class _Head:
    def __init__(self, index):
        self.i = index


class _Token:
    def __init__(self, index, text, start, pos, tag, dep, head):
        self.i = index
        self.text = text
        self.idx = start
        self.lemma_ = text.lower()
        self.pos_ = pos
        self.tag_ = tag
        self.morph = ""
        self.dep_ = dep
        self.head = _Head(head)


class _Extension:
    def __init__(self, constituents=None, labels=None):
        self.constituents = constituents or []
        self.labels = labels or []


class _Span:
    def __init__(self, start, end, labels):
        self.start = start
        self.end = end
        self._ = _Extension(labels=labels)


class _Sentence:
    def __init__(self, start, end, root, constituents):
        self.start = start
        self.end = end
        self.root = _Head(root)
        self._ = _Extension(constituents=constituents)


class _Doc(list):
    def __init__(self, tokens, sentences):
        super().__init__(tokens)
        self.sents = sentences


class AnalysisEvidenceTests(unittest.TestCase):
    def test_builds_compact_raw_parser_evidence_and_constituent_depth(self):
        constituents = [
            _Span(0, 4, ["S"]),
            _Span(0, 1, ["NP"]),
            _Span(1, 3, ["VP"]),
            _Span(1, 2, []),
        ]
        doc = _Doc(
            [
                _Token(0, "Mary", 0, "PROPN", "NNP", "nsubj", 1),
                _Token(1, "read", 5, "VERB", "VBD", "ROOT", 1),
                _Token(2, "it", 10, "PRON", "PRP", "dobj", 1),
                _Token(3, ".", 12, "PUNCT", ".", "punct", 1),
            ],
            [_Sentence(0, 4, 1, constituents)],
        )

        got = build_analysis_evidence(
            doc,
            "Mary read it.",
            spacy_model="en_core_web_trf",
            benepar_model="benepar_en3",
        )

        self.assertEqual(got["protocolVersion"], 4)
        self.assertEqual(got["tokens"][2]["d"], "dobj")
        self.assertEqual(got["sentences"], [{"sid": 0, "s": 0, "e": 4, "r": 1}])
        self.assertEqual(got["constituents"][0], {"s": 0, "e": 4, "l": ["S"], "d": 0})
        self.assertEqual(got["constituents"][1]["d"], 1)
        self.assertEqual(len(got["constituents"]), 3)

        mapped = build_analysis_evidence(
            doc,
            "Mary  read it.",
            spacy_model="en_core_web_trf",
            benepar_model="benepar_en3",
            source_token_offsets=((0, 4), (6, 10), (11, 13), (13, 14)),
        )
        self.assertEqual(
            [(token["a"], token["b"]) for token in mapped["tokens"]],
            [(0, 4), (6, 10), (11, 13), (13, 14)],
        )

        dash_doc = _Doc(
            [_Token(0, "--", 0, "PUNCT", ":", "ROOT", 0)],
            [_Sentence(0, 1, 0, [])],
        )
        dash = build_analysis_evidence(
            dash_doc,
            "—",
            spacy_model="en_core_web_trf",
            benepar_model="benepar_en3",
            source_token_offsets=((0, 1),),
        )
        self.assertEqual(dash["tokens"][0]["t"], "—")


if __name__ == "__main__":
    unittest.main()

import re
import unittest

from alignment import annotate_chunk_spans
from teaching_tree import (
    ConstituentEvidence,
    SyntaxToken,
    TeachingEvidence,
    TokenSource,
    compile_teaching_tree,
)


def token_source(text):
    matches = list(re.finditer(r"--|[—–―]|\w+|[^\w\s]", text))
    return TokenSource(
        text=text,
        token_offsets=tuple((match.start(), match.end()) for match in matches),
    )


def teaching_evidence(rows, constituents=()):
    return TeachingEvidence(
        tokens=tuple(
            SyntaxToken(
                index=index,
                text=text,
                lemma=lemma,
                pos=pos,
                tag=tag,
                dep=dep,
                head=head,
            )
            for index, (text, lemma, pos, tag, dep, head) in enumerate(rows)
        ),
        constituents=tuple(
            ConstituentEvidence(start, end, frozenset(labels))
            for start, end, labels in constituents
        ),
    )


class TeachingTreeContractTests(unittest.TestCase):
    def compile_result(self, text, builder_chunks):
        source = token_source(text)
        compiled = compile_teaching_tree(source, builder_chunks)
        return annotate_chunk_spans(
            source.text,
            compiled,
            source.token_offsets,
        )

    def test_compilation_derives_text_from_spans_and_preserves_v4_contract(self):
        source = token_source("The book works.")
        builder_chunks = [
            {
                "text": "stale subject text",
                "role": "subject",
                "gloss": "",
                "children": None,
                "_lo": 0,
                "_hi": 1,
            },
            {
                "text": "stale predicate text",
                "role": "verb",
                "gloss": "",
                "children": None,
                "_lo": 2,
                "_hi": 3,
            },
        ]

        compiled = compile_teaching_tree(source, builder_chunks)
        result = annotate_chunk_spans(
            source.text,
            compiled,
            source.token_offsets,
        )

        self.assertEqual([node["text"] for node in result], ["The book", "works."])
        self.assertEqual(
            [(node["s"], node["e"]) for node in result],
            [(0, 2), (2, 4)],
        )
        self.assertTrue(all("_lo" not in node and "_hi" not in node for node in result))

    def test_subject_aux_inversion_is_one_expandable_predicate(self):
        result = self.compile_result(
            "Why does he think?",
            [
                {
                    "text": "Why",
                    "role": "adverbial",
                    "gloss": "",
                    "children": None,
                    "_lo": 0,
                    "_hi": 0,
                },
                {
                    "text": "does",
                    "role": "verb",
                    "gloss": "",
                    "children": None,
                    "_lo": 1,
                    "_hi": 1,
                },
                {
                    "text": "he",
                    "role": "subject",
                    "gloss": "",
                    "children": None,
                    "_lo": 2,
                    "_hi": 2,
                },
                {
                    "text": "think?",
                    "role": "verb",
                    "gloss": "",
                    "children": None,
                    "_lo": 3,
                    "_hi": 4,
                },
            ],
        )

        self.assertEqual([node["role"] for node in result], ["adverbial", "verb"])
        predicate = result[1]
        self.assertEqual(predicate["text"], "does he think?")
        self.assertEqual(
            [child["text"] for child in predicate["children"]],
            ["does", "he", "think?"],
        )
        self.assertEqual((predicate["s"], predicate["e"]), (1, 5))

    def test_inversion_grouping_never_crosses_a_sentence_boundary(self):
        # Two selected sentences: "... he will." + "The boy can go ... up".
        # The sentence-final "will." must not be read as an inversion
        # auxiliary for the next sentence's subject and predicate.
        result = self.compile_result(
            "Indeed and he will. The boy can go nowhere but up",
            [
                {
                    "text": "Indeed", "role": "adverbial", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "and", "role": "conjunction", "gloss": "",
                    "children": None, "_lo": 1, "_hi": 1,
                },
                {
                    "text": "he", "role": "subject", "gloss": "",
                    "children": None, "_lo": 2, "_hi": 2,
                },
                {
                    "text": "will.", "role": "verb", "gloss": "",
                    "children": None, "_lo": 3, "_hi": 4,
                },
                {
                    "text": "The boy", "role": "subject", "gloss": "",
                    "children": None, "_lo": 5, "_hi": 6,
                },
                {
                    "text": "can go nowhere but", "role": "verb", "gloss": "",
                    "children": None, "_lo": 7, "_hi": 10,
                },
                {
                    "text": "up", "role": "adverbial", "gloss": "",
                    "children": None, "_lo": 11, "_hi": 11,
                },
            ],
        )

        self.assertEqual(
            [node["role"] for node in result],
            [
                "adverbial", "conjunction", "subject", "verb",
                "subject", "verb", "adverbial",
            ],
        )
        self.assertEqual(result[3]["text"], "will.")
        self.assertIsNone(result[3]["children"])

    def test_coordination_grouping_never_crosses_a_sentence_boundary(self):
        # "He will." + "But wait." must stay two clauses, not fuse into one
        # coordinated predicate spanning the period.
        result = self.compile_result(
            "He will. But wait.",
            [
                {
                    "text": "He", "role": "subject", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "will.", "role": "verb", "gloss": "",
                    "children": None, "_lo": 1, "_hi": 2,
                },
                {
                    "text": "But", "role": "conjunction", "gloss": "",
                    "children": None, "_lo": 3, "_hi": 3,
                },
                {
                    "text": "wait.", "role": "verb", "gloss": "",
                    "children": None, "_lo": 4, "_hi": 5,
                },
            ],
        )

        self.assertEqual(
            [node["role"] for node in result],
            ["subject", "verb", "conjunction", "verb"],
        )
        self.assertTrue(all(node["children"] is None for node in result))

    def test_coordinated_predicates_and_trailing_object_form_one_group(self):
        result = self.compile_result(
            "They sneer and nudge each other.",
            [
                {
                    "text": "They", "role": "subject", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "sneer", "role": "verb", "gloss": "",
                    "children": None, "_lo": 1, "_hi": 1,
                },
                {
                    "text": "and", "role": "conjunction", "gloss": "",
                    "children": None, "_lo": 2, "_hi": 2,
                },
                {
                    "text": "nudge", "role": "verb", "gloss": "",
                    "children": None, "_lo": 3, "_hi": 3,
                },
                {
                    "text": "each other.", "role": "object", "gloss": "",
                    "children": None, "_lo": 4, "_hi": 6,
                },
            ],
        )

        self.assertEqual([node["role"] for node in result], ["subject", "verb"])
        predicate = result[1]
        self.assertEqual(predicate["text"], "sneer and nudge each other.")
        self.assertEqual(
            [child["role"] for child in predicate["children"]],
            ["verb", "conjunction", "verb", "object"],
        )
        self.assertEqual((predicate["s"], predicate["e"]), (1, 7))

    def test_predicate_grouping_applies_inside_nested_clauses(self):
        result = self.compile_result(
            "They said that we try and learn.",
            [
                {
                    "text": "They", "role": "subject", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "said", "role": "verb", "gloss": "",
                    "children": None, "_lo": 1, "_hi": 1,
                },
                {
                    "text": "that we try and learn.",
                    "role": "clause-noun",
                    "gloss": "",
                    "_lo": 2,
                    "_hi": 7,
                    "children": [
                        {
                            "text": "that", "role": "conjunction", "gloss": "",
                            "children": None, "_lo": 2, "_hi": 2,
                        },
                        {
                            "text": "we", "role": "subject", "gloss": "",
                            "children": None, "_lo": 3, "_hi": 3,
                        },
                        {
                            "text": "try", "role": "verb", "gloss": "",
                            "children": None, "_lo": 4, "_hi": 4,
                        },
                        {
                            "text": "and", "role": "conjunction", "gloss": "",
                            "children": None, "_lo": 5, "_hi": 5,
                        },
                        {
                            "text": "learn.", "role": "verb", "gloss": "",
                            "children": None, "_lo": 6, "_hi": 7,
                        },
                    ],
                },
            ],
        )

        clause = result[2]
        self.assertEqual(
            [child["role"] for child in clause["children"]],
            ["conjunction", "subject", "verb"],
        )
        self.assertEqual(
            [child["text"] for child in clause["children"][2]["children"]],
            ["try", "and", "learn."],
        )

    def test_semicolon_separated_predicates_become_collapsible_clauses(self):
        result = self.compile_result(
            "He came; she left.",
            [
                {
                    "text": "He", "role": "subject", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "came;", "role": "verb", "gloss": "",
                    "children": None, "_lo": 1, "_hi": 2,
                },
                {
                    "text": "she", "role": "subject", "gloss": "",
                    "children": None, "_lo": 3, "_hi": 3,
                },
                {
                    "text": "left.", "role": "verb", "gloss": "",
                    "children": None, "_lo": 4, "_hi": 5,
                },
            ],
        )

        self.assertEqual([node["role"] for node in result], ["clause", "clause"])
        self.assertEqual([node["text"] for node in result], ["He came;", "she left."])
        self.assertEqual(
            [[child["role"] for child in node["children"]] for node in result],
            [["subject", "verb"], ["subject", "verb"]],
        )

    def test_paired_dash_parenthetical_splits_by_token_spans(self):
        result = self.compile_result(
            "Ways -- all that work -- are useful.",
            [
                {
                    "text": "Ways -- all that work --",
                    "role": "subject",
                    "gloss": "",
                    "children": None,
                    "_lo": 0,
                    "_hi": 5,
                },
                {
                    "text": "are", "role": "verb", "gloss": "",
                    "children": None, "_lo": 6, "_hi": 6,
                },
                {
                    "text": "useful.", "role": "complement", "gloss": "",
                    "children": None, "_lo": 7, "_hi": 8,
                },
            ],
        )

        self.assertEqual(
            [node["role"] for node in result],
            ["subject", "insertion", "verb", "complement"],
        )
        self.assertEqual(
            [node["text"] for node in result],
            ["Ways", "-- all that work --", "are", "useful."],
        )
        self.assertEqual(
            [(node["s"], node["e"]) for node in result],
            [(0, 1), (1, 6), (6, 7), (7, 9)],
        )

    def test_standalone_question_word_is_an_adverbial_not_a_conjunction(self):
        result = self.compile_result(
            "Why leave?",
            [
                {
                    "text": "Why", "role": "conjunction", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "leave?", "role": "verb", "gloss": "",
                    "children": None, "_lo": 1, "_hi": 2,
                },
            ],
        )

        self.assertEqual(result[0]["role"], "adverbial")

    def test_adverbial_clause_introducer_remains_a_conjunction(self):
        result = self.compile_result(
            "When they arrive, we leave.",
            [
                {
                    "text": "When they arrive,",
                    "role": "clause-adverbial",
                    "gloss": "",
                    "_lo": 0,
                    "_hi": 3,
                    "children": [
                        {
                            "text": "When", "role": "conjunction", "gloss": "",
                            "children": None, "_lo": 0, "_hi": 0,
                        },
                        {
                            "text": "they", "role": "subject", "gloss": "",
                            "children": None, "_lo": 1, "_hi": 1,
                        },
                        {
                            "text": "arrive,", "role": "verb", "gloss": "",
                            "children": None, "_lo": 2, "_hi": 3,
                        },
                    ],
                },
                {
                    "text": "we", "role": "subject", "gloss": "",
                    "children": None, "_lo": 4, "_hi": 4,
                },
                {
                    "text": "leave.", "role": "verb", "gloss": "",
                    "children": None, "_lo": 5, "_hi": 6,
                },
            ],
        )

        self.assertEqual(result[0]["children"][0]["role"], "conjunction")

    def test_overlapping_builder_siblings_are_rejected(self):
        source = token_source("one two")
        chunks = [
            {
                "text": "one two", "role": "subject", "gloss": "",
                "children": None, "_lo": 0, "_hi": 1,
            },
            {
                "text": "two", "role": "verb", "gloss": "",
                "children": None, "_lo": 1, "_hi": 1,
            },
        ]

        with self.assertRaisesRegex(ValueError, "overlap"):
            compile_teaching_tree(source, chunks)

    def test_builder_child_outside_parent_is_rejected(self):
        source = token_source("parent escaped")
        chunks = [{
            "text": "parent", "role": "subject", "gloss": "",
            "_lo": 0, "_hi": 0,
            "children": [{
                "text": "escaped", "role": "other", "gloss": "",
                "children": None, "_lo": 1, "_hi": 1,
            }],
        }]

        with self.assertRaisesRegex(ValueError, "escapes"):
            compile_teaching_tree(source, chunks)

    def test_top_level_tree_must_cover_every_source_token(self):
        source = token_source("covered missing")
        chunks = [{
            "text": "covered", "role": "other", "gloss": "",
            "children": None, "_lo": 0, "_hi": 0,
        }]

        with self.assertRaisesRegex(ValueError, "cover"):
            compile_teaching_tree(source, chunks)

    def test_wh_infinitive_uses_dependency_role_and_constituency_form(self):
        source = token_source("We know what to do")
        chunks = [
            {
                "text": "We", "role": "subject", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "know", "role": "verb", "gloss": "",
                "children": None, "_lo": 1, "_hi": 1,
            },
            {
                "text": "what to do", "role": "complement", "gloss": "",
                "_lo": 2, "_hi": 4,
                "children": [
                    {
                        "text": "what", "role": "adverbial", "gloss": "",
                        "children": None, "_lo": 2, "_hi": 2,
                    },
                    {
                        "text": "to do", "role": "verb", "gloss": "",
                        "children": None, "_lo": 3, "_hi": 4,
                    },
                ],
            },
        ]
        evidence = teaching_evidence(
            [
                ("We", "we", "PRON", "PRP", "nsubj", 1),
                ("know", "know", "VERB", "VBP", "ROOT", 1),
                ("what", "what", "PRON", "WP", "dobj", 4),
                ("to", "to", "PART", "TO", "aux", 4),
                ("do", "do", "VERB", "VB", "xcomp", 1),
            ],
            [(2, 5, {"SBAR"})],
        )

        result = compile_teaching_tree(source, chunks, evidence=evidence)
        wh_clause = result[2]
        self.assertEqual((wh_clause["function"], wh_clause["form"]),
                         ("object", "wh-infinitive"))
        self.assertEqual(
            (
                wh_clause["children"][0]["role"],
                wh_clause["children"][0]["function"],
                wh_clause["children"][0]["form"],
            ),
            ("object", "object", "wh-word"),
        )
        self.assertEqual(
            wh_clause["children"][1]["form"],
            "infinitive-predicate",
        )

    def test_with_participial_clause_is_annotated_only_with_dual_evidence(self):
        source = token_source("with retirees trading")
        chunks = [{
            "text": "with retirees trading", "role": "prep-phrase", "gloss": "",
            "_lo": 0, "_hi": 2,
            "children": [
                {
                    "text": "with", "role": "prep-phrase", "gloss": "",
                    "children": None, "_lo": 0, "_hi": 0,
                },
                {
                    "text": "retirees trading", "role": "clause-noun",
                    "gloss": "", "_lo": 1, "_hi": 2,
                    "children": [
                        {
                            "text": "retirees", "role": "subject", "gloss": "",
                            "children": None, "_lo": 1, "_hi": 1,
                        },
                        {
                            "text": "trading", "role": "verb", "gloss": "",
                            "children": None, "_lo": 2, "_hi": 2,
                        },
                    ],
                },
            ],
        }]
        evidence = teaching_evidence(
            [
                ("with", "with", "ADP", "IN", "prep", 0),
                ("retirees", "retiree", "NOUN", "NNS", "nsubj", 2),
                ("trading", "trade", "VERB", "VBG", "pcomp", 0),
            ],
            [(0, 3, {"PP"}), (1, 3, {"S"})],
        )

        result = compile_teaching_tree(source, chunks, evidence=evidence)[0]
        self.assertEqual(
            (result["role"], result["function"], result["form"]),
            ("adverbial", "adverbial", "with-complex"),
        )
        self.assertEqual(result["children"][0]["form"], "preposition")
        inner = result["children"][1]
        self.assertEqual((inner["role"], inner["form"]),
                         ("clause", "participial-clause"))
        self.assertEqual(
            inner["children"][0]["function"],
            "logical-subject",
        )
        self.assertEqual(
            inner["children"][1]["form"],
            "present-participle",
        )

    def test_plain_with_phrase_keeps_generic_fallback(self):
        source = token_source("with retirees")
        chunks = [{
            "text": "with retirees", "role": "prep-phrase", "gloss": "",
            "children": None, "_lo": 0, "_hi": 1,
        }]
        evidence = teaching_evidence(
            [
                ("with", "with", "ADP", "IN", "prep", 0),
                ("retirees", "retiree", "NOUN", "NNS", "pobj", 0),
            ],
            [(0, 2, {"PP"})],
        )

        result = compile_teaching_tree(source, chunks, evidence=evidence)[0]
        self.assertEqual(result["role"], "prep-phrase")
        self.assertNotIn("function", result)
        self.assertEqual(result["form"], "prepositional-phrase")

    def test_comma_led_speech_content_is_direct_quotation(self):
        source = token_source("He said, We agree")
        chunks = [
            {
                "text": "He", "role": "subject", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "said,", "role": "verb", "gloss": "",
                "children": None, "_lo": 1, "_hi": 2,
            },
            {
                "text": "We agree", "role": "clause-noun", "gloss": "",
                "children": None, "_lo": 3, "_hi": 4,
            },
        ]
        evidence = teaching_evidence(
            [
                ("He", "he", "PRON", "PRP", "nsubj", 1),
                ("said", "say", "VERB", "VBD", "ROOT", 1),
                (",", ",", "PUNCT", ",", "punct", 1),
                ("We", "we", "PRON", "PRP", "nsubj", 4),
                ("agree", "agree", "VERB", "VBP", "ccomp", 1),
            ],
            [(3, 5, {"S"})],
        )

        quote = compile_teaching_tree(source, chunks, evidence=evidence)[2]
        self.assertEqual(
            (quote["function"], quote["form"]),
            ("content", "direct-quotation"),
        )

    def test_participial_acl_is_a_reduced_relative_modifier(self):
        source = token_source("payments depending on returns")
        chunks = [
            {
                "text": "payments", "role": "object", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "depending on returns", "role": "clause-relative",
                "gloss": "", "_lo": 1, "_hi": 3,
                "children": [
                    {
                        "text": "depending", "role": "verb", "gloss": "",
                        "children": None, "_lo": 1, "_hi": 1,
                    },
                    {
                        "text": "on returns", "role": "prep-phrase",
                        "gloss": "", "children": None, "_lo": 2, "_hi": 3,
                    },
                ],
            },
        ]
        evidence = teaching_evidence(
            [
                ("payments", "payment", "NOUN", "NNS", "dobj", 0),
                ("depending", "depend", "VERB", "VBG", "acl", 0),
                ("on", "on", "ADP", "IN", "prep", 1),
                ("returns", "return", "NOUN", "NNS", "pobj", 2),
            ],
            [(1, 4, {"PP"})],
        )

        modifier = compile_teaching_tree(source, chunks, evidence=evidence)[1]
        self.assertEqual(
            (modifier["function"], modifier["form"]),
            ("modifier", "reduced-relative"),
        )
        self.assertEqual(
            modifier["children"][0]["form"],
            "present-participle",
        )

    def test_participial_acl_without_constituent_boundary_keeps_fallback(self):
        source = token_source("payments depending")
        chunks = [
            {
                "text": "payments", "role": "object", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "depending", "role": "clause-relative", "gloss": "",
                "children": None, "_lo": 1, "_hi": 1,
            },
        ]
        evidence = teaching_evidence([
            ("payments", "payment", "NOUN", "NNS", "dobj", 0),
            ("depending", "depend", "VERB", "VBG", "acl", 0),
        ])

        modifier = compile_teaching_tree(source, chunks, evidence=evidence)[1]
        self.assertEqual(modifier["function"], "modifier")
        self.assertEqual(modifier["form"], "relative-clause")


if __name__ == "__main__":
    unittest.main()

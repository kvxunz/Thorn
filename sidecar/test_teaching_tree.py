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

    def test_subject_aux_inversion_keeps_subject_outside_predicate(self):
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

        self.assertEqual([node["role"] for node in result], ["adverbial", "verb", "subject", "verb"])
        self.assertEqual(
            [node["text"] for node in result],
            ["Why", "does", "he", "think?"],
        )
        self.assertEqual((result[2]["s"], result[2]["e"]), (2, 3))

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

    def test_object_subject_of_to_infinitive_stays_on_matrix_backbone(self):
        source = token_source("We expect Dotty to lash")
        chunks = [
            {
                "text": "We", "role": "subject", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "expect", "role": "verb", "gloss": "",
                "children": None, "_lo": 1, "_hi": 1,
            },
            {
                "text": "Dotty to lash", "role": "clause-noun", "gloss": "",
                "_lo": 2, "_hi": 4,
                "children": [
                    {
                        "text": "Dotty", "role": "subject", "gloss": "",
                        "children": None, "_lo": 2, "_hi": 2,
                    },
                    {
                        "text": "to lash", "role": "verb", "gloss": "",
                        "children": None, "_lo": 3, "_hi": 4,
                    },
                ],
            },
        ]
        evidence = teaching_evidence(
            [
                ("We", "we", "PRON", "PRP", "nsubj", 1),
                ("expect", "expect", "VERB", "VBP", "ROOT", 1),
                ("Dotty", "Dotty", "PROPN", "NNP", "nsubj", 4),
                ("to", "to", "PART", "TO", "aux", 4),
                ("lash", "lash", "VERB", "VB", "ccomp", 1),
            ],
            [(2, 5, {"S"}), (3, 5, {"VP"})],
        )

        result = compile_teaching_tree(source, chunks, evidence=evidence)

        self.assertEqual(
            [(node["text"], node["role"]) for node in result],
            [
                ("We", "subject"),
                ("expect", "verb"),
                ("Dotty", "object"),
                ("to lash", "complement"),
            ],
        )
        self.assertEqual(result[2]["function"], "object")
        self.assertEqual(result[3]["function"], "complement")
        self.assertEqual(result[3]["form"], "infinitive-predicate")

    def test_object_infinitive_split_survives_sentence_final_punctuation(self):
        """The live shape: merge_tiny hands the node a trailing period.

        Benepar's S/VP spans stop before it, so comparing labels against the
        raw node span made the split fire only mid-sentence — invisible to a
        fixture that omits the period, and to nothing else.
        """
        source = token_source("We expect Dotty to lash .")
        chunks = [
            {
                "text": "We", "role": "subject", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "expect", "role": "verb", "gloss": "",
                "children": None, "_lo": 1, "_hi": 1,
            },
            {
                "text": "Dotty to lash .", "role": "clause-noun", "gloss": "",
                "_lo": 2, "_hi": 5,
                "children": [
                    {
                        "text": "Dotty", "role": "subject", "gloss": "",
                        "children": None, "_lo": 2, "_hi": 2,
                    },
                    {
                        "text": "to lash", "role": "verb", "gloss": "",
                        "children": None, "_lo": 3, "_hi": 4,
                    },
                ],
            },
        ]
        evidence = teaching_evidence(
            [
                ("We", "we", "PRON", "PRP", "nsubj", 1),
                ("expect", "expect", "VERB", "VBP", "ROOT", 1),
                ("Dotty", "Dotty", "PROPN", "NNP", "nsubj", 4),
                ("to", "to", "PART", "TO", "aux", 4),
                ("lash", "lash", "VERB", "VB", "ccomp", 1),
                (".", ".", "PUNCT", ".", "punct", 1),
            ],
            [(2, 5, {"S"}), (3, 5, {"VP"})],
        )

        result = compile_teaching_tree(source, chunks, evidence=evidence)

        self.assertEqual(
            [(node["text"], node["role"]) for node in result],
            [
                ("We", "subject"),
                ("expect", "verb"),
                ("Dotty", "object"),
                ("to lash .", "complement"),
            ],
        )
        self.assertEqual(result[3]["form"], "infinitive-predicate")

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

    def clause_after_noun(self, text, rows):
        """One noun followed by one clause chunk, compiled and returned."""
        source = token_source(text)
        last = len(rows) - 1
        chunks = [
            {
                "text": rows[0][0], "role": "object", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": text, "role": "clause-relative", "gloss": "",
                "children": None, "_lo": 1, "_hi": last,
            },
        ]
        compiled = compile_teaching_tree(
            source, chunks, evidence=teaching_evidence(rows),
        )
        return compiled[1]

    def test_that_complementizer_on_a_noun_is_an_appositive_clause(self):
        """"the fact that Parliament governs advertising".

        ``that`` is a bare ``mark`` here — the clause is complete without it,
        which is exactly what distinguishes 同位语从句 from 定语从句.
        """
        clause = self.clause_after_noun(
            "fact that Parliament governs advertising",
            [
                ("fact", "fact", "NOUN", "NN", "pobj", 0),
                ("that", "that", "SCONJ", "IN", "mark", 3),
                ("Parliament", "Parliament", "PROPN", "NNP", "nsubj", 3),
                ("governs", "govern", "VERB", "VBZ", "acl", 0),
                ("advertising", "advertising", "NOUN", "NN", "dobj", 3),
            ],
        )

        self.assertEqual(clause["form"], "appositive-clause")
        # 同位语从句 already names the slot; a "定语" chip beside it would
        # contradict the note the grammar-notes layer puts on ``that``.
        self.assertNotIn("function", clause)

    def test_relative_that_keeps_the_relative_clause_form(self):
        """"a product that fails": ``relcl``, and ``that`` is its subject."""
        clause = self.clause_after_noun(
            "product that fails",
            [
                ("product", "product", "NOUN", "NN", "dobj", 0),
                ("that", "that", "PRON", "WDT", "nsubj", 2),
                ("fails", "fail", "VERB", "VBZ", "relcl", 0),
            ],
        )

        self.assertEqual(
            (clause["function"], clause["form"]),
            ("modifier", "relative-clause"),
        )

    def test_finite_verb_under_a_complementizer_is_not_a_participle(self):
        """"The news that he had won": ``won`` is VBN under ``acl`` too.

        Without the complementizer guard the reduced-relative pass claims it
        first and relabels a past-perfect predicate 过去分词 — backwards, and
        it survives the outer rename because the two passes write to
        different nodes.
        """
        source = token_source("news that he had won")
        chunks = [
            {
                "text": "news", "role": "subject", "gloss": "",
                "children": None, "_lo": 0, "_hi": 0,
            },
            {
                "text": "that he had won", "role": "clause-relative",
                "gloss": "", "_lo": 1, "_hi": 4,
                "children": [
                    {
                        "text": "that", "role": "conjunction", "gloss": "",
                        "children": None, "_lo": 1, "_hi": 1,
                    },
                    {
                        "text": "he", "role": "subject", "gloss": "",
                        "children": None, "_lo": 2, "_hi": 2,
                    },
                    {
                        "text": "had won", "role": "verb", "gloss": "",
                        "children": None, "_lo": 3, "_hi": 4,
                    },
                ],
            },
        ]
        evidence = teaching_evidence(
            [
                ("news", "news", "NOUN", "NN", "nsubj", 0),
                ("that", "that", "SCONJ", "IN", "mark", 4),
                ("he", "he", "PRON", "PRP", "nsubj", 4),
                ("had", "have", "AUX", "VBD", "aux", 4),
                ("won", "win", "VERB", "VBN", "acl", 0),
            ],
            [(1, 5, {"SBAR"})],
        )

        clause = compile_teaching_tree(source, chunks, evidence=evidence)[1]
        self.assertEqual(clause["form"], "appositive-clause")
        predicate = clause["children"][2]
        self.assertEqual((predicate["function"], predicate.get("form")),
                         ("predicate", None))

    def test_acl_without_a_complementizer_stays_a_relative_clause(self):
        """"the mother moaning by the fire": an ``acl``, but no ``mark``.

        Reduced relatives are the other construction spaCy files under
        ``acl``; without the complementizer they must not be renamed.
        """
        clause = self.clause_after_noun(
            "mother moaning by the fire",
            [
                ("mother", "mother", "NOUN", "NN", "dobj", 0),
                ("moaning", "moan", "VERB", "VBG", "acl", 0),
                ("by", "by", "ADP", "IN", "prep", 1),
                ("the", "the", "DET", "DT", "det", 4),
                ("fire", "fire", "NOUN", "NN", "pobj", 2),
            ],
        )

        self.assertEqual(clause["form"], "relative-clause")

    def prep_wrapper(self, text, rows, cut):
        """A prep wrapper split into a preposition card and an object card."""
        source = token_source(text)
        last = len(rows) - 1
        chunks = [{
            "text": text, "role": "prep-phrase", "gloss": "",
            "_lo": 0, "_hi": last,
            "children": [
                {
                    "text": text, "role": "prep-phrase", "gloss": "",
                    "children": None, "_lo": 0, "_hi": cut - 1,
                },
                {
                    "text": text, "role": "object", "gloss": "",
                    "children": None, "_lo": cut, "_hi": last,
                },
            ],
        }]
        compiled = compile_teaching_tree(
            source, chunks, evidence=teaching_evidence(rows),
        )
        return compiled[0]

    def test_card_holding_only_the_preposition_is_labelled_a_preposition(self):
        """"Apart from | the fact": the phrase label belongs to the parent.

        The child card has no object on it, so calling it 介词短语 would name
        a phrase that is not there.
        """
        wrapper = self.prep_wrapper(
            "Apart from the fact",
            [
                ("Apart", "apart", "ADV", "RB", "advmod", 3),
                ("from", "from", "ADP", "IN", "prep", 3),
                ("the", "the", "DET", "DT", "det", 3),
                ("fact", "fact", "NOUN", "NN", "pobj", 1),
            ],
            cut=2,
        )

        self.assertEqual(wrapper["form"], "prepositional-phrase")
        self.assertEqual(wrapper["children"][0]["form"], "preposition")
        self.assertEqual(wrapper["children"][1]["function"], "object")

    def test_prep_card_carrying_its_object_stays_a_phrase(self):
        """An unsplit core keeps 介词短语 — the object is on the card."""
        wrapper = self.prep_wrapper(
            "in spite of the rain",
            [
                ("in", "in", "ADP", "IN", "prep", 0),
                ("spite", "spite", "NOUN", "NN", "pobj", 0),
                ("of", "of", "ADP", "IN", "prep", 1),
                ("the", "the", "DET", "DT", "det", 4),
                ("rain", "rain", "NOUN", "NN", "pobj", 2),
            ],
            cut=3,
        )

        self.assertEqual(wrapper["children"][0]["form"], "prepositional-phrase")


if __name__ == "__main__":
    unittest.main()

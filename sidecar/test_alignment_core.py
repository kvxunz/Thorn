import re
import unittest

from alignment import annotate_chunk_spans


def source_offsets(text):
    return [(match.start(), match.end()) for match in re.finditer(r"\w+|[^\w\s]", text)]


class ChunkSpanContractTests(unittest.TestCase):
    def test_repeated_that_gets_stable_parent_constrained_token_spans(self):
        sentence = "the fact that law governs a product that fails"
        chunks = [
            {"text": "the fact", "role": "object", "gloss": "", "children": None},
            {
                "text": "that law governs",
                "role": "clause-noun",
                "gloss": "",
                "children": [
                    {"text": "that", "role": "conjunction", "gloss": "", "children": None},
                    {"text": "law", "role": "subject", "gloss": "", "children": None},
                    {"text": "governs", "role": "verb", "gloss": "", "children": None},
                ],
            },
            {"text": "a product", "role": "object", "gloss": "", "children": None},
            {
                "text": "that fails",
                "role": "clause-relative",
                "gloss": "",
                "children": [
                    {"text": "that", "role": "relative", "gloss": "指代前述的 product", "children": None},
                    {"text": "fails", "role": "verb", "gloss": "", "children": None},
                ],
            },
        ]

        result = annotate_chunk_spans(sentence, chunks, source_offsets(sentence))

        self.assertEqual(result[1]["id"], "1")
        self.assertEqual((result[1]["s"], result[1]["e"]), (2, 5))
        self.assertEqual((result[1]["children"][0]["s"], result[1]["children"][0]["e"]), (2, 3))
        self.assertEqual((result[3]["children"][0]["s"], result[3]["children"][0]["e"]), (7, 8))

    def test_oversized_tree_and_escaped_child_are_rejected(self):
        sentence = " ".join(f"w{index}" for index in range(257))
        offsets = source_offsets(sentence)
        too_many = [
            {"text": f"w{index}", "role": "other", "gloss": "", "children": None}
            for index in range(257)
        ]
        with self.assertRaisesRegex(ValueError, "too large"):
            annotate_chunk_spans(sentence, too_many, offsets)

        escaped_child = [{
            "text": "w0", "role": "other", "gloss": "",
            "children": [{"text": "w1", "role": "other", "gloss": "", "children": None}],
        }]
        with self.assertRaisesRegex(ValueError, "outside its parent"):
            annotate_chunk_spans(sentence, escaped_child, offsets)

    def test_explicit_token_bounds_cannot_escape_their_parent(self):
        sentence = "parent escaped"
        offsets = source_offsets(sentence)
        chunks = [{
            "text": "parent",
            "role": "other",
            "gloss": "",
            "_lo": 0,
            "_hi": 1,
            "children": [{
                "text": "escaped",
                "role": "other",
                "gloss": "",
                "_lo": 1,
                "_hi": 2,
                "children": None,
            }],
        }]

        with self.assertRaisesRegex(ValueError, "outside its parent"):
            annotate_chunk_spans(sentence, chunks, offsets)


if __name__ == "__main__":
    unittest.main()

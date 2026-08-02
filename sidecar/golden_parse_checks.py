# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "spacy==3.7.5",
#     "benepar==0.2.0",
#     "torch>=2.2,<3",
#     "transformers==4.30.2",
#     "protobuf==3.20.3",
#     "sentencepiece>=0.1.99",
#     "fastapi>=0.110",
#     "uvicorn>=0.29",
#     "spacy-transformers>=1.3,<1.4",
#     "numpy<2",
#     "en-core-web-trf @ https://github.com/explosion/spacy-models/releases/download/en_core_web_trf-3.7.3/en_core_web_trf-3.7.3-py3-none-any.whl",
# ]
# ///
"""Live regression suite: real spaCy + Benepar, one case per documented issue.

Run: uv run --script golden_parse_checks.py

Deliberately *not* named ``test_*.py``.  ``python -m unittest discover -s
sidecar`` must stay hermetic and instant; this suite loads ~3.2 GB of model
weights and takes seconds per sentence, so it is opt-in.

Why it exists: every rule in the chunk builder is a claim about what a real
parse looks like, and the fast suite tests those rules against hand-written
fakes.  LEARNINGS #18 and #40 are the same lesson learned twice — a table or
heuristic can be green against fakes and never fire on a live parse.  Only
this file runs the claim against the model.

Two layers:

* ``test_client_contract`` applies the checks Sidecar.swift's ``validate``
  performs to every sentence.  A tree that fails those is rejected by the app
  and reaches the user as "引擎暂不可用" with a healthy engine (LEARNINGS #29),
  so it must fail here instead.
* One test per case, asserting the skeleton the issue list calls for.  The IDs
  match docs/parsing-issues.md.

Assertions address nodes by role and text, never by child index: a commit that
legitimately adds a card (a split-out object, say) must not break an unrelated
case.  A stale positional assertion is exactly how this suite's predecessor
came to report a correct tree as broken.
"""
from __future__ import annotations

import itertools
import re
import sys
import unittest
from typing import Any, ClassVar

import server

# Sentence corpus.  Keys ending in a documented ID carry a regression criterion
# from docs/parsing-issues.md; the rest are structural probes kept from the
# original --self-test.
CASES: dict[str, str] = {
    "relative": "The book that I bought yesterday was surprisingly expensive.",
    "stranded-wh": (
        "When juries began holding advertisers responsible for misleading claims, "
        "companies changed their practices."
    ),
    "coordinate": (
        "My father and mother should have stayed in New York "
        "where they met and married and where I was born."
    ),
    "vbg-relative": "She came to help the students who were struggling.",
    "notion": (
        "The notion is that people have failed to detect the massive changes "
        "which have happened in the ocean because they have been looking back "
        "only a relatively short time into the past."
    ),
    "however": (
        '"The test of any democratic society," he wrote in a Wall Street Journal '
        'column, "lies not in how well it can control expression but in whether it '
        "gives freedom of thought and expression the widest possible latitude, "
        "however disputable or irritating the results may sometimes be"
    ),
    "idiom": (
        "Last year Mitsuo Setoyama, who was then education minister, raised eyebrows "
        "when he argued that reforms had weakened the morality."
    ),
    "negated-coordinate": "The problem is not that we lack data but that we lack time.",
    "nested-relative": "The cat that chased the mouse that stole the cheese slept.",
    "correlative": "The harder he worked, the less he achieved.",
    "sooner": "The sooner we start, the sooner we finish.",
    "fronted-degree": "Much as I admire him, I cannot agree.",
    "elided-as": (
        "I have discovered, as perhaps Kelsey will after her much-publicized "
        "resignation from the editorship of She after a build-up of stress, "
        'that abandoning the doctrine of "juggling your life", and making '
        "the alternative move into downshifting brings with it far greater "
        "rewards than financial success and social status."
    ),
    "explanatory-for": (
        "When a new movement in art attains a certain fashion, it is advisable "
        "to find out what its advocates are aiming at, for, however farfetched "
        "and unreasonable their principles may seem today, it is possible that "
        "in years to come they may be regarded as normal."
    ),
    "two-sentences": (
        "Indeed and he will. The boy who wants to know something about the grace, "
        "elegance and beauty of Euclid can go nowhere but up"
    ),
    "railway-insertion": (
        "The railroad industry as a whole, despite its brightening fortunes, "
        "still does not earn enough to cover the cost of the capital it must "
        "invest to keep up with its surging traffic."
    ),
    "dash-parenthetical": (
        "This development--and its strong implication for US politics and "
        "economy in years ahead--has enthroned the South."
    ),
    "dash-em": (
        "The grand mediocrity of today—everyone being the same in survival "
        "and number of off-spring—means that natural selection has lost 80% "
        "of its power in upper-middle-class India compared to the tribe."
    ),
    "dash-while": (
        "While warnings are often appropriate and necessary--the dangers of "
        "drug interactions, for example--and many are required by state or "
        "federal regulations, it isn't clear that they actually protect the "
        "manufacturers and sellers from liability if a customer is injured."
    ),
    "dash-spacing-none": "The plan--his own--failed.",
    "dash-spacing-one": "The plan -- his own--failed.",
    "dash-spacing-both": "The plan -- his own -- failed.",
    "gerund-internal-coordinate": (
        "Comparing cats and dogs and making careful notes improves observation."
    ),
    "for-with-following-coordinate": (
        "When a new movement in art attains a certain fashion, it is advisable "
        "to find out what its advocates are aiming at, for, however farfetched "
        "and unreasonable their principles may seem today, it is possible that "
        "they may be regarded as normal, but critics disagree."
    ),
    "object-infinitive": (
        "The committee expects the government to publish the report before June."
    ),
    "extraposed-relative": (
        "To do so, the Tallinners sent a spy to his house, who heard Olev's "
        "name in a song his wife sang."
    ),
}


# ------------------------------------------------------------------ helpers

def walk(nodes: list[dict[str, Any]]):
    """Every node in the tree, parents before children."""
    for node in nodes:
        yield node
        yield from walk(node.get("children") or [])


def node_with_text(nodes, text: str) -> dict[str, Any] | None:
    return next((n for n in walk(nodes) if n["text"] == text), None)


def node_starting_with(nodes, prefix: str) -> dict[str, Any] | None:
    return next((n for n in walk(nodes) if n["text"].startswith(prefix)), None)


def children_with_role(node, role: str) -> list[dict[str, Any]]:
    return [c for c in (node.get("children") or []) if c["role"] == role]


def roles(nodes) -> list[str]:
    return [n["role"] for n in nodes]


def texts(nodes) -> list[str]:
    return [n["text"] for n in nodes]


class GoldenParseTests(unittest.TestCase):
    """Each test parses on demand; a case that raises fails only its own test."""

    # Shared so 21 tests cost 21 parses, not one per assertion.
    _trees: ClassVar[dict[str, Any]] = {}

    @classmethod
    def setUpClass(cls):
        server.load()

    @classmethod
    def parse(cls, name: str):
        if name not in cls._trees:
            cls._trees[name] = server.parse_text(CASES[name])
        return cls._trees[name]

    def tree(self, name: str) -> list[dict[str, Any]]:
        chunks, _tokens = self.parse(name)
        return chunks

    # -------------------------------------------------- the client contract

    def assert_client_contract(self, chunks, source_tokens):
        """Mirror of Sidecar.swift `validate` — plus the coverage rule.

        Kept as a transcription rather than an import so a change on either
        side shows up as a disagreement here instead of silently passing.
        """
        self.assertTrue(chunks, "empty tree")
        self.assertLessEqual(len(source_tokens), 512)
        self.assertTrue(all(token for token in source_tokens), "empty source token")

        seen_ids: set[str] = set()
        count = 0

        def normalized(text: str) -> str:
            return re.sub(r"\s+", "", text)

        def check(nodes, lo: int, hi: int, path: tuple[int, ...], depth: int):
            nonlocal count
            self.assertLessEqual(depth, 32, "tree is too deep")
            previous_end = lo
            for position, node in enumerate(nodes):
                count += 1
                self.assertLessEqual(count, 256, "too many nodes")

                expected_id = ".".join(str(p) for p in (*path, position))
                self.assertEqual(node["id"], expected_id, "node id is not its path")
                self.assertNotIn(node["id"], seen_ids, "duplicate node id")
                seen_ids.add(node["id"])

                start, end = node["s"], node["e"]
                self.assertTrue(
                    lo <= start < end <= hi,
                    f"span {start}:{end} escapes parent {lo}:{hi} at {node['id']}",
                )
                self.assertGreaterEqual(
                    start, previous_end,
                    f"span {start}:{end} overlaps its left sibling at {node['id']}",
                )
                self.assertEqual(
                    normalized(node["text"]),
                    normalized("".join(source_tokens[start:end])),
                    f"text is not its own span at {node['id']}",
                )
                check(node.get("children") or [], start, end, (*path, position), depth + 1)
                previous_end = end

        check(chunks, 0, len(source_tokens), (), 1)

        # teaching_tree guarantees the top level tiles the sentence; the Swift
        # side cannot check this, so a gap would silently drop words from the
        # panel instead of being rejected.
        covered = [(node["s"], node["e"]) for node in chunks]
        self.assertEqual(covered[0][0], 0, "top level does not start at token 0")
        self.assertEqual(covered[-1][1], len(source_tokens), "top level is short")
        for (_, end), (start, _) in itertools.pairwise(covered):
            self.assertEqual(start, end, f"top level has a gap at token {end}")

    def test_client_contract(self):
        """No sentence may produce a tree the app would reject."""
        for name in CASES:
            with self.subTest(case=name):
                chunks, source_tokens = self.parse(name)
                self.assert_client_contract(chunks, source_tokens)

    # ------------------------------------------------ documented issue list

    def test_p001_elided_as_clause_keeps_its_modifiers(self):
        """P-001: both `after` phrases stay inside the `as` clause."""
        chunks = self.tree("elided-as")
        as_clause = node_starting_with(chunks, "as perhaps")
        self.assertIsNotNone(as_clause, "no `as` clause")
        self.assertTrue(
            as_clause["text"].endswith("after a build-up of stress,"),
            f"`as` clause stops early: {as_clause['text']!r}",
        )
        self.assertFalse(
            [
                node for node in chunks
                if node["role"] == "prep-phrase" and node["text"].startswith("after her")
            ],
            "an `after` phrase was left beside the main clause",
        )

    def test_p002_coordinated_gerunds_form_one_subject(self):
        """P-002: both gerund phrases are one subject; no fake predicate."""
        chunks = self.tree("elided-as")
        subject = next(
            (
                node for node in walk(chunks)
                if node["role"] == "subject"
                and node["text"].startswith("abandoning the doctrine")
            ),
            None,
        )
        self.assertIsNotNone(subject, "coordinated gerund subject is missing")
        self.assertEqual(
            [child["text"].strip(" ,") for child in subject["children"]],
            [
                'abandoning the doctrine of "juggling your life"',
                "and",
                "making the alternative move into downshifting",
            ],
        )
        self.assertIsNone(
            node_with_text(chunks, "move"),
            "`move` became a predicate of its own again",
        )

    def test_p003_explanatory_for_owns_its_second_clause(self):
        """P-003: the concessive and `it is possible` sit under `for`."""
        chunks = self.tree("explanatory-for")
        branch = next(
            (
                node for node in chunks
                if node["role"] == "clause" and node["text"].lstrip(", ").startswith("for,")
            ),
            None,
        )
        self.assertIsNotNone(branch, "`for` did not open a clause of its own")
        self.assertTrue(
            children_with_role(branch, "clause-adverbial"),
            "the concessive clause is not inside the `for` branch",
        )
        self.assertTrue(
            [c for c in children_with_role(branch, "subject") if c["text"] == "it"],
            "`it` is not inside the `for` branch",
        )

    def test_p004_no_grouping_crosses_a_sentence_terminator(self):
        """P-004: two selected sentences never fuse into one predicate."""
        chunks = self.tree("two-sentences")
        for node in walk(chunks):
            self.assertNotRegex(
                node["text"],
                r"\.\s+\S",
                f"node {node['id']} spans a sentence boundary",
            )

    def test_r001_insertion_punctuation_is_covered(self):
        """R-001: the comma after an inserted phrase belongs to some node."""
        chunks, tokens = self.parse("railway-insertion")
        self.assert_client_contract(chunks, tokens)  # coverage is the criterion
        self.assertTrue(
            node_starting_with(chunks, "The railroad industry"),
            "the subject was not recovered",
        )

    def test_r003_dashes_survive_every_spacing(self):
        """R-003: no spacing variant produces a zero-length source token."""
        for name in (
            "dash-spacing-none", "dash-spacing-one", "dash-spacing-both",
            "dash-parenthetical", "dash-em", "dash-while",
        ):
            with self.subTest(case=name):
                chunks, tokens = self.parse(name)
                self.assertTrue(chunks)
                self.assertTrue(all(token.strip() for token in tokens))

    # ------------------------------------------------- structural skeletons

    def test_relative_clause_stays_folded_into_its_subject(self):
        chunks = self.tree("relative")
        self.assertEqual(roles(chunks), ["subject", "verb", "complement"])
        self.assertEqual(roles(chunks[0]["children"]), ["subject", "clause-relative"])

    def test_fronted_when_clause_keeps_its_conjunction(self):
        chunks = self.tree("stranded-wh")
        when_clause = chunks[0]
        first_child = when_clause["children"][0]
        self.assertEqual((first_child["text"], first_child["role"]), ("When", "conjunction"))
        self.assertTrue(
            node_starting_with([when_clause], "holding "),
            "the `holding` complement left the `when` clause",
        )

    def test_coordinated_relative_clauses_are_siblings(self):
        """LEARNINGS #29: a discontinuous conj must appear exactly once."""
        chunks = self.tree("coordinate")
        modifier = next(
            node for node in chunks
            if node["role"] == "prep-phrase" and node.get("children")
        )
        self.assertEqual(
            texts(children_with_role(modifier, "clause-relative")),
            ["where they met and married", "where I was born"],
        )
        self.assertEqual(texts(children_with_role(modifier, "conjunction")), ["and"])

    def test_relative_pronoun_opens_its_clause(self):
        who = node_with_text(self.tree("vbg-relative"), "who were struggling")
        self.assertIsNotNone(who)
        self.assertEqual(who["role"], "clause-relative")
        self.assertEqual(who["children"][0]["role"], "relative")

    def test_an_extraposed_relative_is_a_clause_not_part_of_the_prep_phrase(self):
        """A relative split from its noun is nobody's dependency child here.

        Before it got its own root, the leftover pass glued all eleven tokens
        onto the `to his house` card, so a finite clause was taught as part of
        a prepositional phrase — and the relative inside it never surfaced.
        """
        chunks = self.tree("extraposed-relative")
        relative = node_starting_with(chunks, "who heard")
        self.assertIsNotNone(relative, "the extraposed relative has no card")
        self.assertEqual(relative["role"], "clause-relative")
        self.assertEqual(relative["children"][0]["role"], "relative")
        self.assertEqual(
            [node["text"] for node in chunks if node["role"] == "prep-phrase"],
            ["to his house,"],
        )
        # The relative inside its own object surfaces too: it was buried in
        # the glue along with everything else.
        self.assertIsNotNone(node_with_text(chunks, "his wife sang"))

    def test_object_clause_exposes_its_relative_clause(self):
        self.assertTrue(
            [n for n in walk(self.tree("notion")) if n["role"] == "clause-relative"],
        )

    def test_trailing_however_is_adverbial(self):
        however = node_with_text(
            self.tree("however"),
            "however disputable or irritating the results may sometimes be",
        )
        self.assertIsNotNone(however)
        self.assertEqual(however["role"], "clause-adverbial")

    def test_idiom_stays_one_card(self):
        chunks = self.tree("idiom")
        self.assertIsNotNone(node_with_text(chunks, "raised eyebrows"))
        self.assertTrue([n for n in walk(chunks) if n["role"] == "clause-relative"])

    def test_negation_stays_with_the_verb(self):
        chunks = self.tree("negated-coordinate")
        self.assertEqual(chunks[1]["text"], "is not")
        self.assertNotIn("not", chunks[2]["text"])

    def test_nested_relative_clauses_nest(self):
        inner = node_starting_with(self.tree("nested-relative"), "that chased")
        self.assertIsNotNone(inner)
        self.assertEqual(inner["children"][0]["text"], "that")
        self.assertIn("the mouse", texts(inner["children"]))
        self.assertIn("that stole the cheese", texts(inner["children"]))

    def test_correlative_comparatives_open_their_clause(self):
        self.assertEqual(self.tree("correlative")[0]["children"][0]["text"], "The harder")
        self.assertEqual(self.tree("sooner")[0]["children"][0]["text"], "The sooner")

    def test_fronted_degree_clause_leads(self):
        self.assertTrue(self.tree("fronted-degree")[0]["text"].startswith("Much "))

    def test_internal_gerund_coordination_forms_one_subject(self):
        gerund = self.tree("gerund-internal-coordinate")[0]
        self.assertEqual(
            texts(gerund["children"]),
            ["Comparing cats and dogs", "and", "making careful notes"],
        )

    def test_explanatory_for_stops_before_a_following_coordinate(self):
        chunks = self.tree("for-with-following-coordinate")
        branch = next(
            node for node in chunks
            if node["role"] == "clause" and node["text"].lstrip(", ").startswith("for,")
        )
        self.assertNotIn("but critics disagree", branch["text"])
        self.assertTrue(
            [
                node for node in chunks
                if node["role"] == "conjunction" and node["text"].strip(" ,") == "but"
            ],
            "the trailing coordinate lost its conjunction",
        )

    def test_object_infinitive_exposes_the_matrix_object(self):
        """The split added in "expect NP to VP" — live, not against fakes."""
        chunks = self.tree("object-infinitive")
        government = node_with_text(chunks, "the government")
        self.assertIsNotNone(government, "the matrix object is still buried")
        self.assertEqual(government["role"], "object")
        self.assertTrue(
            node_starting_with(chunks, "to publish"),
            "the infinitive predicate did not become its own card",
        )


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    raise SystemExit(0 if result.wasSuccessful() else 1)

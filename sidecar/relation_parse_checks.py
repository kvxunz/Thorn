import unittest
from dataclasses import asdict
from unittest.mock import patch

import server
from syntax_assembly import analyze_structure
from teaching_policy import TeachingPolicy
from teaching_projection import project_structure
from teaching_tree import TeachingEvidence, TokenSource

CASES = (
    {
        "id": "main-relative", "family": "clause",
        "text": "The scientist who discovered the comet received a prize.",
        "root": "received",
        "required": [("subject", "received", "scientist"),
                     ("relative-modifier", "scientist", "discovered"),
                     ("subject", "discovered", "who"),
                     ("object", "discovered", "comet")],
        "forbidden": [("subject", "received", "who")],
    },
    {
        "id": "content-clause", "family": "clause",
        "text": "She believes that the plan will work.", "root": "believes",
        "required": [("subject", "believes", "She"),
                     ("content-clause", "believes", "work"),
                     ("subject", "work", "plan")],
        "forbidden": [("subject", "believes", "plan")],
    },
    {
        "id": "adverbial-clause", "family": "clause",
        "text": "Although the rain stopped, the roads remained wet.", "root": "remained",
        "required": [("subject", "remained", "roads"),
                     ("clausal-modifier", "remained", "stopped"),
                     ("subject", "stopped", "rain")],
        "forbidden": [("subject", "remained", "rain")],
    },
    {
        "id": "passive", "family": "backbone",
        "text": "The report was written by Alice.", "root": "written",
        "required": [("subject", "written", "report"),
                     ("preposition-modifier", "written", "by"),
                     ("preposition-object", "by", "Alice")],
        "forbidden": [("subject", "written", "Alice")],
    },
    {
        "id": "imperative", "family": "backbone",
        "text": "Close the door.", "root": "Close",
        "required": [("object", "Close", "door")],
        "forbidden": [("subject", "Close", "door")],
    },
    {
        "id": "question", "family": "backbone",
        "text": "Why did the engine stop?", "root": "stop",
        "required": [("subject", "stop", "engine"), ("auxiliary", "stop", "did")],
        "forbidden": [("subject", "did", "engine")],
    },
    {
        "id": "noun-preposition", "family": "attachment",
        "text": "The book on the table belongs to Mary.", "root": "belongs",
        "required": [("preposition-modifier", "book", "on"),
                     ("preposition-object", "on", "table")],
        "forbidden": [("preposition-modifier", "belongs", "on")],
    },
    {
        "id": "reduced-relative", "family": "attachment",
        "text": "The people waiting outside looked tired.", "root": "looked",
        "required": [("nominal-modifier", "people", "waiting")],
        "forbidden": [("clausal-modifier", "looked", "waiting")],
    },
    {
        "id": "nominal-coordinate", "family": "coordination",
        "text": "Cats and dogs sleep.", "root": "sleep",
        "required": [("coordinate", "Cats", "dogs")],
        "forbidden": [("object", "sleep", "dogs")],
        "groups": [["Cats", "dogs"]],
    },
    {
        "id": "predicate-coordinate", "family": "coordination",
        "text": "Alice sang and danced.", "root": "sang",
        "required": [("coordinate", "sang", "danced")],
        "forbidden": [("object", "sang", "danced")],
        "groups": [["sang", "danced"]],
    },
    {
        "id": "relative-vocabulary-variant", "family": "clause",
        "text": "The journalist who interviewed the actor won an award.", "root": "won",
        "required": [("subject", "won", "journalist"),
                     ("relative-modifier", "journalist", "interviewed"),
                     ("object", "interviewed", "actor")],
        "forbidden": [("subject", "won", "actor")],
    },
    {
        "id": "coordinate-separate-subjects", "family": "coordination",
        "text": "Alice sang and Bob danced.", "root": "sang",
        "required": [("subject", "sang", "Alice"), ("subject", "danced", "Bob")],
        "forbidden": [("subject", "danced", "Alice"), ("subject", "sang", "Bob")],
        "groups": [["sang", "danced"]],
    },
)


class RelationParseTests(unittest.TestCase):
    def test_closed_parenthesis_does_not_swallow_following_list(self):
        result = server.analyze_text("We provide bedding (sheets and pillows), towels and blankets.")
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get("children") or [])
        closing = result.source_tokens.index(")")
        blankets = result.source_tokens.index("blankets")
        asides = [node for node in walk(result.chunks) if node["role"] == "insertion"]
        self.assertTrue(asides)
        self.assertTrue(all(node["e"] <= closing + 2 for node in asides))
        self.assertTrue(any(node["role"] in ("object", "appositive") and node["s"] <= blankets < node["e"]
                            for node in walk(result.chunks)))

    def test_nominal_and_measure_complements_keep_their_owner(self):
        for text, phrase, role in (
            ("She uses a tool similar to a compass.", "a tool similar to a compass.", "object"),
            ("He discovered facts about how birds communicate.", "facts about how birds communicate.", "object"),
        ):
            with self.subTest(text=text):
                chunks = server.analyze_text(text).chunks
                self.assertIn((phrase, role), {(node["text"], node["role"]) for node in chunks})
        chunks = server.analyze_text("The dancer would run 40° to the left of the vertical line.").chunks
        self.assertIn("would run", {node["text"] for node in chunks if node["role"] == "verb"})
        self.assertFalse(any("40" in node["text"] for node in chunks if node["role"] == "verb"))

    def test_reconciliation_preserves_evidence_and_rejects_counterexamples(self):
        result = server.analyze_text("What did the new policy change?")
        self.assertTrue(result.evidence.repairs)
        predicate = result.source_tokens.index("change")
        subject = result.source_tokens.index("policy")
        self.assertEqual(result.evidence.relations.attachment(subject).head, predicate)
        self.assertEqual(result.evidence.relations.attachment(subject).kind, "subject")
        self.assertEqual(result.evidence.relations.attachment(subject).provenance, "benepar-do-question")
        self.assertFalse(result.evidence.relations.diagnostics)
        for text in (
            "What did the new policy do?",
            "In the office she was given a document.",
            "In the office they stored several documents.",
            "The richer family bought a house.",
        ):
            with self.subTest(text=text):
                result = server.analyze_text(text)
                self.assertFalse(result.evidence.repairs)
                self.assertFalse(result.evidence.relations.diagnostics)

    def test_remaining_structure_families(self):
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get("children") or [])

        for text, word, role in (
            ("Attached to this letter will be a schedule.", "will", "verb"),
            ("In the box were stored several documents.", "documents", "subject"),
            ("What did the new policy change?", "change", "verb"),
            ("The harder she worked, the greater her success.", "success", "subject"),
        ):
            with self.subTest(text=text):
                result = server.analyze_text(text)
                index = result.source_tokens.index(word)
                self.assertTrue(any(node["role"] == role and node["s"] <= index < node["e"]
                                    for node in result.chunks))
        for text, child_word, parent_word, child_role, parent_role in (
            ("We bought a device which records sound.", "records", "device", "clause-relative", "object"),
            ("The alarm rings each time the door opens.", "opens", "time", "clause-relative", "adverbial"),
            ("She knew that if he called, Alice would answer but Bob would remain silent.",
             "remain", "answer", "clause-noun", "clause-noun"),
        ):
            with self.subTest(text=text):
                result = server.analyze_text(text)
                child_index = result.source_tokens.index(child_word)
                parent_index = result.source_tokens.index(parent_word)
                self.assertTrue(any(
                    parent["role"] == parent_role and parent["s"] <= parent_index < parent["e"]
                    and any(child["role"] == child_role and child["s"] <= child_index < child["e"]
                            for child in parent.get("children") or [])
                    for parent in walk(result.chunks)
                ))

    def test_questions_preserve_subject_and_wh_argument_roles(self):
        for text, subject, opener, role in (
            ("What did the researcher discover?", "the researcher", "What", "object"),
            ("How was it happening?", "it", "How", "adverbial"),
            ("Who did the researcher interview?", "the researcher", "Who", "object"),
            ("Who discovered the answer?", "Who", "Who", "subject"),
        ):
            with self.subTest(text=text):
                chunks = server.analyze_text(text).chunks
                self.assertIn((subject, "subject"), {(node["text"], node["role"]) for node in chunks})
                self.assertIn((opener, role), {(node["text"], node["role"]) for node in chunks})

    def test_finite_progressive_zero_relatives_remain_nominal_modifiers(self):
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get("children") or [])

        for text, phrase in (
            ("This was the one they were looking for.", "they were looking for"),
            ("This is the document she is searching for.", "she is searching for"),
            ("That was the person we had been waiting for.", "we had been waiting for"),
            ("This was the one that they were looking for.", "that they were looking for"),
            ("This was the person for whom they were waiting.", "for whom they were waiting"),
        ):
            with self.subTest(text=text):
                analysis = server.analyze_text(text)
                clauses = [node for node in walk(analysis.chunks)
                           if node["text"].rstrip(".") == phrase and node["role"] == "clause-relative"]
                self.assertTrue(clauses)
                self.assertTrue(any(node["role"] == "complement" and clauses[0] in (node.get("children") or [])
                                    for node in walk(analysis.chunks)))

    def test_scent_content_clause_and_relative_keep_their_nominal_owners(self):
        text = ("The scent she carried in her samples and on her body was a message to the other bees "
                "that this was the one they were looking for.")
        chunks = server.analyze_text(text).chunks
        self.assertEqual([node["role"] for node in chunks], ["subject", "verb", "complement"])
        message = chunks[2]
        content = next(node for node in message["children"] if node["text"].startswith("that this"))
        self.assertEqual(content["form"], "appositive-clause")
        nominal = next(node for node in content["children"] if node["role"] == "complement")
        relative = next(node for node in nominal["children"] if node["text"].startswith("they"))
        self.assertEqual(relative["role"], "clause-relative")

    def test_finite_progressive_does_not_turn_real_asides_into_relatives(self):
        def walk(nodes):
            for node in nodes:
                yield node
                yield from walk(node.get("children") or [])

        for text, expected in (
            ("The meeting, everyone being exhausted, ended early.", "clause-adverbial"),
            ("The proposal, I believe, will succeed.", "insertion"),
        ):
            with self.subTest(text=text):
                chunks = server.analyze_text(text).chunks
                self.assertTrue(any(node["role"] == expected for node in walk(chunks)))
                self.assertFalse(any(node["role"] == "clause-relative" for node in walk(chunks)))
        chunks = server.analyze_text("She said that they were looking for the document.").chunks
        self.assertFalse(any(node["role"] == "clause-relative" for node in walk(chunks)))

    def test_display_depth_cannot_change_syntax_or_boundary_decisions(self):
        prepared, doc, offsets = server._prepare_document(
            "The smoke laced with dust and tinged with oil rose."
        )
        evidence = TeachingEvidence.from_doc(doc)
        source = TokenSource(prepared.surface, offsets)
        syntax_before = asdict(evidence.relations)
        structure = analyze_structure(doc, evidence.relations, trace=True)
        structure_before = asdict(structure)
        with patch("teaching_projection.analyze_structure", side_effect=AssertionError("must not reanalyze")):
            detailed = project_structure(structure, doc, source, evidence)
            summary = project_structure(structure, doc, source, evidence, policy=TeachingPolicy(max_depth=0))
        self.assertTrue(any(node.get("children") for node in detailed))
        self.assertTrue(summary)
        self.assertTrue(structure.boundary_decisions)
        self.assertTrue(all(node.get("children") is None for node in summary))
        self.assertEqual(structure_before, asdict(structure))
        self.assertEqual(syntax_before, asdict(evidence.relations))
        self.assertEqual(
            [(node["text"], node["role"], node["s"], node["e"]) for node in detailed],
            [(node["text"], node["role"], node["s"], node["e"]) for node in summary],
        )

    def test_nested_relative_preserves_main_clause_and_local_subject(self):
        analysis = server.analyze_text(
            "The smell was wafting in from the garden where children played."
        )
        self.assertEqual(analysis.chunks[0]["text"], "The smell")
        self.assertEqual(analysis.chunks[1]["text"], "was wafting")

        def descendants(nodes):
            for node in nodes:
                yield node
                yield from descendants(node.get("children") or [])

        clauses = [node for node in descendants(analysis.chunks)
                   if node["role"] == "clause-relative" and node["text"].startswith("where")]
        self.assertEqual(len(clauses), 1)
        self.assertIn(("children", "subject"), {
            (node["text"], node["role"]) for node in clauses[0]["children"]
        })

    def test_coordinated_modifiers_are_complete_sibling_phrases(self):
        for sentence, first, second in (
            ("The smoke laced with dust and tinged with oil rose.",
             "laced with dust", "tinged with oil"),
            ("The door covered with paint and damaged by rain collapsed.",
             "covered with paint", "damaged by rain"),
        ):
            with self.subTest(sentence=sentence):
                analysis = server.analyze_text(sentence)

                def walk(nodes):
                    for node in nodes:
                        yield node
                        yield from walk(node.get("children") or [])

                parents = [node for node in walk(analysis.chunks)
                           if {first, second}.issubset({
                               child["text"] for child in node.get("children") or []
                           })]
                self.assertTrue(parents, "parallel modifiers must retain their own complements")
                for child in parents[0]["children"]:
                    if child["text"] in {first, second}:
                        self.assertEqual(child["function"], "modifier")

    @classmethod
    def setUpClass(cls):
        server.load()

    def test_critical_relations(self):
        self.assertTrue(CASES)
        for case in CASES:
            with self.subTest(case=case["id"], family=case["family"]):
                analysis = server.analyze_text(case["text"])
                graph = analysis.evidence.relations
                tokens = analysis.source_tokens

                def anchor(word, tokens=tokens):
                    matches = [index for index, text in enumerate(tokens) if text == word]
                    self.assertEqual(len(matches), 1, f"ambiguous or absent gold anchor: {word}")
                    return matches[0]

                self.assertTrue(analysis.chunks)
                self.assertFalse(graph.diagnostics)
                self.assertIn(anchor(case["root"]), {
                    frame.predicate for frame in graph.clauses if frame.parent is None
                })
                actual = {(edge.kind, edge.head, edge.dependent) for edge in graph.edges}
                for kind, head, dependent in case["required"]:
                    self.assertIn((kind, anchor(head), anchor(dependent)), actual)
                for kind, head, dependent in case["forbidden"]:
                    self.assertNotIn((kind, anchor(head), anchor(dependent)), actual)
                groups = {frozenset(group.members) for group in graph.coordinations}
                for group in case.get("groups", []):
                    self.assertIn(frozenset(anchor(word) for word in group), groups)


if __name__ == "__main__":
    unittest.main()

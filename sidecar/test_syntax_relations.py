import unittest
from types import SimpleNamespace

from constituency import ConstituencyIndex, TokenSpan
from relation_evaluation import evaluate
from syntax_decomposition import has_complete_embedded_relative
from syntax_policy import backbone_role
from teaching_tree import (
    ConstituentEvidence,
    SyntaxToken,
    TeachingEvidence,
    TeachingNode,
    _project_coordinated_modifiers,
)


def evidence(rows):
    return TeachingEvidence(tuple(
        SyntaxToken(index, text, text.lower(), pos, tag, dep, head)
        for index, (text, pos, tag, dep, head) in enumerate(rows)
    ), ())


class SyntaxRelationsTests(unittest.TestCase):
    def test_backbone_policy_keeps_arguments_and_clauses_distinct(self):
        for dependency in ("nsubj", "nsubjpass", "expl"):
            self.assertEqual(backbone_role(dependency, "read"), ("subject", False))
        self.assertEqual(backbone_role("dobj", "read"), ("object", False))
        self.assertEqual(backbone_role("attr", "be"), ("complement", False))
        self.assertEqual(backbone_role("csubj", "matter"), ("clause-noun", True))
        self.assertEqual(backbone_role("xcomp", "want"), ("complement", True))
        self.assertIsNone(backbone_role("prep", "read"))

    def test_expansion_requires_whole_relative_and_local_target(self):
        graph = evidence([
            ("house", "NOUN", "NN", "ROOT", 0),
            ("where", "ADV", "WRB", "advmod", 3),
            ("we", "PRON", "PRP", "nsubj", 3),
            ("lived", "VERB", "VBD", "relcl", 0),
        ]).relations
        self.assertTrue(has_complete_embedded_relative(graph, 0, 0, 4))
        self.assertFalse(has_complete_embedded_relative(graph, 0, 0, 3))
        self.assertFalse(has_complete_embedded_relative(graph, 1, 1, 4))
        self.assertFalse(has_complete_embedded_relative(graph, 3, 0, 4))

    def test_evaluator_rejects_empty_dataset_and_broken_execution(self):
        with self.assertRaises(ValueError):
            evaluate([], lambda text: None)
        report = evaluate([{"id": "failure", "text": "test"}], lambda text: None)
        self.assertEqual(report["checks"]["execution"], {"passed": 0, "total": 1})
        self.assertTrue(report["failures"])

    def test_evaluator_fails_wrong_relation_instead_of_scoring_empty_green(self):
        source = evidence([("Birds", "NOUN", "NNS", "nsubj", 1),
                           ("fly", "VERB", "VBP", "ROOT", 1)])
        analysis = SimpleNamespace(source_tokens=["Birds", "fly"], evidence=source,
                                   chunks=[{"text": "Birds"}, {"text": "fly"}])
        case = {"id": "wrong", "text": "Birds fly", "root": "fly",
                "checks": [["backbone", "object", "fly", "Birds"]]}
        report = evaluate([case], lambda text: analysis)
        self.assertEqual(report["checks"]["backbone"], {"passed": 0, "total": 1})
        self.assertEqual(len(report["failures"]), 1)

    def test_modifiers_group_by_dependency_ownership_not_adjacency(self):
        source = evidence([
            ("smoke", "NOUN", "NN", "ROOT", 0),
            ("laced", "VERB", "VBN", "acl", 0),
            ("with", "ADP", "IN", "prep", 1),
            ("dust", "NOUN", "NN", "pobj", 2),
            ("and", "CCONJ", "CC", "cc", 1),
            ("tinged", "VERB", "VBN", "conj", 1),
            ("with", "ADP", "IN", "prep", 5),
            ("oil", "NOUN", "NN", "pobj", 6),
        ])
        children = (
            TeachingNode(1, 2, "verb"), TeachingNode(2, 4, "prep-phrase"),
            TeachingNode(4, 5, "conjunction"), TeachingNode(5, 6, "verb"),
            TeachingNode(6, 8, "prep-phrase"),
        )
        parent = TeachingNode(1, 8, "clause-relative", children=children)
        projected = _project_coordinated_modifiers((parent,), source)[0]
        self.assertEqual([(child.start, child.end) for child in projected.children],
                         [(1, 4), (4, 5), (5, 8)])
        self.assertEqual(projected.children[0].function, "modifier")
        self.assertEqual(projected.children[2].function, "modifier")
        ambiguous = TeachingNode(1, 8, "clause-relative", children=(
            children[0], TeachingNode(2, 6, "prep-phrase"), children[-1],
        ))
        self.assertEqual(_project_coordinated_modifiers((ambiguous,), source), (ambiguous,))

    def test_span_index_merges_labels_without_changing_evidence(self):
        source = evidence([("Go", "VERB", "VB", "ROOT", 0)])
        source = TeachingEvidence(source.tokens, (
            ConstituentEvidence(0, 1, frozenset({"S"})),
            ConstituentEvidence(0, 1, frozenset({"VP"})),
        ))
        self.assertEqual(source.labels_for(0, 1), frozenset({"S", "VP"}))
        self.assertEqual(source.labels_for(1, 2), frozenset())
        self.assertIs(source.relations, source.relations)

    def test_main_clause_and_relative_clause_have_separate_subjects(self):
        graph = evidence([
            ("People", "NOUN", "NNS", "nsubj", 4),
            ("who", "PRON", "WP", "nsubj", 2),
            ("read", "VERB", "VBP", "relcl", 0),
            ("books", "NOUN", "NNS", "dobj", 2),
            ("learn", "VERB", "VBP", "ROOT", 4),
        ]).relations
        frames = {frame.predicate: frame for frame in graph.clauses}
        self.assertEqual(frames[4].subjects, (0,))
        self.assertEqual(frames[2].subjects, (1,))
        self.assertEqual(frames[2].parent, 4)
        self.assertEqual(frames[2].objects, (3,))
        self.assertEqual(graph.attachment(2).head, 0)
        self.assertEqual(graph.clause_by_token, (4, 2, 2, 2, 4))

    def test_coordination_does_not_invent_shared_arguments(self):
        graph = evidence([
            ("She", "PRON", "PRP", "nsubj", 1),
            ("sang", "VERB", "VBD", "ROOT", 1),
            ("danced", "VERB", "VBD", "conj", 1),
            ("bowed", "VERB", "VBD", "conj", 2),
        ]).relations
        self.assertEqual(graph.coordinations[0].members, (1, 2, 3))
        self.assertEqual(graph.clauses[1].subjects, ())
        self.assertEqual(graph.clauses[2].subjects, ())

    def test_nominal_coordination_is_not_a_new_clause(self):
        graph = evidence([
            ("Cats", "NOUN", "NNS", "nsubj", 2),
            ("dogs", "NOUN", "NNS", "conj", 0),
            ("sleep", "VERB", "VBP", "ROOT", 2),
        ]).relations
        self.assertEqual(len(graph.clauses), 1)
        self.assertEqual(graph.coordinations[0].members, (0, 1))

    def test_participial_modifier_preserves_target_without_finite_predicate(self):
        graph = evidence([
            ("smoke", "NOUN", "NN", "nsubj", 2),
            ("rising", "VERB", "VBG", "acl", 0),
            ("vanished", "VERB", "VBD", "ROOT", 2),
        ]).relations
        self.assertEqual(graph.clauses[0].finiteness, "nonfinite")
        self.assertEqual(graph.clauses[1].finiteness, "finite")
        self.assertEqual(graph.attachment(1).head, 0)

    def test_auxiliary_marks_passive_as_finite(self):
        graph = evidence([
            ("was", "AUX", "VBD", "auxpass", 1),
            ("seen", "VERB", "VBN", "ROOT", 1),
        ]).relations
        self.assertEqual(graph.clauses[0].finiteness, "finite")
        self.assertEqual(graph.clauses[0].subjects, ())

    def test_bare_verb_does_not_get_guessed_finiteness(self):
        graph = evidence([("Go", "VERB", "VB", "ROOT", 0)]).relations
        self.assertEqual(graph.clauses[0].finiteness, "undetermined")

    def test_cycle_terminates_with_diagnostic(self):
        graph = evidence([
            ("one", "NOUN", "NN", "conj", 1),
            ("two", "NOUN", "NN", "conj", 0),
        ]).relations
        self.assertIn("dependency-cycle", graph.diagnostics)
        self.assertIn("coordination-cycle", graph.diagnostics)

    def test_trace_explains_boundary_fallback_without_changing_selection(self):
        parent = TokenSpan(0, 3)
        index = ConstituencyIndex([TokenSpan(0, 2, frozenset({"NP"}))], trace=True)
        selected = index.resolve(root=0, role="subject", parent=parent, dependency_indices=[0])
        self.assertEqual(selected.end, 2)
        self.assertEqual(index.decisions[0]["provenance"], "benepar-compatible-span")
        selected = index.resolve(root=2, role="subject", parent=parent, dependency_indices=[2])
        self.assertEqual(selected.start, 2)
        self.assertEqual(index.decisions[1]["provenance"], "dependency-contiguous-fallback")

    def test_empty_evidence_is_safe(self):
        graph = evidence([]).relations
        self.assertEqual(graph.clauses, ())
        self.assertEqual(graph.edges, ())

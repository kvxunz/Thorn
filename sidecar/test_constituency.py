import unittest

from constituency import ConstituencyIndex, TokenSpan


class ConstituencyBoundaryTests(unittest.TestCase):
    def test_expandable_subject_uses_outer_np_that_contains_its_clause(self):
        index = ConstituencyIndex([
            TokenSpan(0, 2, frozenset({"NP"})),
            TokenSpan(0, 6, frozenset({"NP"})),
            TokenSpan(2, 6, frozenset({"SBAR"})),
        ])
        got = index.resolve(
            root=1,
            role="subject",
            parent=TokenSpan(0, 10),
            required={4},
            blocked={6, 8},
            dependency_indices=range(6),
        )
        self.assertEqual((got.start, got.end), (0, 6))

    def test_plain_subject_prefers_the_smallest_compatible_np(self):
        index = ConstituencyIndex([
            TokenSpan(0, 2, frozenset({"NP"})),
            TokenSpan(0, 6, frozenset({"NP"})),
        ])
        got = index.resolve(
            root=1,
            role="subject",
            parent=TokenSpan(0, 10),
            blocked={6},
            dependency_indices=range(6),
        )
        self.assertEqual((got.start, got.end), (0, 2))

    def test_clause_prefers_sbar_over_its_inner_s(self):
        index = ConstituencyIndex([
            TokenSpan(2, 6, frozenset({"SBAR"})),
            TokenSpan(3, 6, frozenset({"S"})),
        ])
        got = index.resolve(
            root=4,
            role="clause-relative",
            parent=TokenSpan(0, 10),
            required={3, 4},
            dependency_indices=range(2, 6),
        )
        self.assertEqual((got.start, got.end), (2, 6))

    def test_constituency_excludes_stranded_dependency_introducer(self):
        index = ConstituencyIndex([
            TokenSpan(0, 9, frozenset({"SBAR"})),
            TokenSpan(3, 9, frozenset({"S", "VP"})),
        ])
        got = index.resolve(
            root=3,
            role="complement",
            parent=TokenSpan(0, 9),
            required={3, 5},
            blocked={1, 2},
            dependency_indices={0, 3, 4, 5, 6, 7, 8},
        )
        self.assertEqual((got.start, got.end), (3, 9))

    def test_overwide_constituent_cannot_swallow_a_sibling_root(self):
        index = ConstituencyIndex([
            TokenSpan(0, 5, frozenset({"NP"})),
        ])
        got = index.resolve(
            root=1,
            role="subject",
            parent=TokenSpan(0, 7),
            blocked={3},
            dependency_indices={0, 1},
        )
        self.assertEqual((got.start, got.end), (0, 2))

    def test_discontinuous_dependency_fallback_keeps_root_component(self):
        index = ConstituencyIndex([
            TokenSpan(11, 15, frozenset({"S"})),
            TokenSpan(12, 15, frozenset({"VP"})),
        ])
        got = index.resolve(
            root=14,
            role="__coord_clause__",
            parent=TokenSpan(10, 20),
            blocked={11, 12},
            dependency_indices={10, 14},
        )
        self.assertEqual((got.start, got.end), (14, 15))

    def test_wh_introducer_and_coordinate_clause_children_come_from_tree(self):
        index = ConstituencyIndex([
            TokenSpan(10, 20, frozenset({"SBAR"})),
            TokenSpan(10, 15, frozenset({"SBAR"})),
            TokenSpan(10, 11, frozenset({"WHADVP"})),
            TokenSpan(11, 15, frozenset({"S"})),
            TokenSpan(16, 20, frozenset({"SBAR"})),
            TokenSpan(17, 20, frozenset({"S"})),
        ])
        parent = TokenSpan(10, 20)
        wh = index.leading_wh_span(10, parent)
        self.assertIsNotNone(wh)
        self.assertEqual((wh.start, wh.end), (10, 11))
        children = index.coordinate_clause_children(parent)
        self.assertEqual([(span.start, span.end) for span in children], [(10, 15), (16, 20)])

    def test_adjacent_relative_clauses_are_not_assumed_to_be_coordinates(self):
        index = ConstituencyIndex([
            TokenSpan(2, 10, frozenset({"SBAR"})),
            TokenSpan(2, 6, frozenset({"SBAR"})),
            TokenSpan(6, 10, frozenset({"SBAR"})),
        ])
        self.assertEqual(index.coordinate_clause_children(TokenSpan(2, 10)), ())


if __name__ == "__main__":
    unittest.main()

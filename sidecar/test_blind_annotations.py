import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_blind_annotations", Path(__file__).resolve().parent.parent / "scripts/check_blind_annotations.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BlindAnnotationTests(unittest.TestCase):
    def rows(self):
        first = {"id": "one", "text": "Birds fly.", "source": "original",
                 "annotator": "first", "annotated_at": "2026-09-13", "model_output_seen": False,
                 "main_predicate": "fly", "subjects": ["Birds"], "objects_or_complements": [],
                 "modifiers": [], "coordination_groups": [], "acceptable_alternatives": [], "uncertainties": []}
        second = copy.deepcopy(first)
        second["annotator"] = "second"
        return [first, second]

    def test_valid_pair_does_not_claim_independence_verified(self):
        result = module.validate(self.rows())
        self.assertEqual(result["sentences"], 1)
        self.assertEqual(result["disagreements"], [])
        self.assertEqual(result["status"], "format-valid-awaiting-independent-verification")

    def test_disagreement_is_reported_without_overwriting_answers(self):
        rows = self.rows()
        rows[1]["uncertainties"] = ["context needed"]
        original = copy.deepcopy(rows)
        self.assertEqual(module.validate(rows)["disagreements"], [{"id": "one", "fields": ["uncertainties"]}])
        self.assertEqual(rows, original)

    def test_rejects_single_duplicate_exposed_or_invalid_annotations(self):
        for kind in ("single", "duplicate", "exposed", "phrase", "modifier", "coordination", "source"):
            rows = self.rows()
            if kind == "single":
                rows.pop()
            elif kind == "duplicate":
                rows[1]["annotator"] = "first"
            elif kind == "exposed":
                rows[0]["model_output_seen"] = True
            elif kind == "phrase":
                rows[0]["main_predicate"] = "swim"
            elif kind == "modifier":
                rows[0]["modifiers"] = [{"phrase": "fast", "modifies": "fly", "reason": "manner"}]
            elif kind == "coordination":
                rows[0]["coordination_groups"] = [["Birds"]]
            else:
                rows[1]["text"] = "Birds fly quickly."
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                module.validate(rows)

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "ielts_corpus_probe", Path(__file__).resolve().parent.parent / "scripts/ielts_corpus_probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class IELTSProbeTests(unittest.TestCase):
    def test_only_passage_prose_is_extracted(self):
        parser = probe.PassageParagraphs()
        parser.feed('<p>Outside text.</p><div id="ielts-reading-transcript-1">'
                    '<p><em>Read the instructions.</em></p><p>Monday morning opening hours.</p>'
                    '<p>A <strong>nested</strong> paragraph.</p>'
                    '<p class="ielts-reading-passage-subhead">Advertisements for local businesses</p>'
                    '<p>An advert.</p></div><div id="ielts-reading-transcript-2">'
                    '<p>Another paragraph.</p></div><p>Footer.</p>')
        self.assertEqual([text for _, text in parser.parts], ["A nested paragraph.", "Another paragraph."])

    def test_deduplication_and_split_are_deterministic(self):
        def segmenter(text):
            return SimpleNamespace(sents=[SimpleNamespace(text=text)])

        raw = (b'<div id="ielts-reading-transcript-1"><p>The small birds left before sunrise.</p>'
               b'<p>The small birds left before sunrise.</p><p>Short title</p></div>')
        first = probe.extract_cases(raw, segmenter)
        self.assertEqual(len(first), 1)
        self.assertEqual(first, probe.extract_cases(raw, segmenter))
        with self.assertRaises(ValueError):
            probe.extract_cases(b"<p>Not inside a transcript.</p>", segmenter)

    def test_semantic_check_requires_actual_role_and_parent(self):
        relative = {"s": 2, "e": 5, "role": "clause-relative"}
        parent = {"s": 0, "e": 5, "role": "subject", "children": [relative]}
        expected = [{"anchor": 3, "start": 2, "role": "clause-relative",
                     "parent_anchor": 1, "parent_role": "subject"}]
        self.assertEqual(probe.check_expectations([parent], expected), [])
        self.assertEqual(probe.check_expectations([relative], expected), expected)
        self.assertTrue(probe.check_expectations([parent], [{"anchor": 3, "role": "verb"}]))
        self.assertTrue(probe.check_expectations([parent], [{"anchor": 1, "role": "subject", "end": 2}]))
        self.assertEqual(probe.check_expectations([parent], [{"anchor": 1, "role": "subject", "end": 5}]), [])
        self.assertTrue(probe.check_expectations([parent], [
            {"anchor": 3, "role": "clause-relative", "top_level": True}
        ]))

    def test_structural_checks_reject_overlap_and_outside_children(self):
        analysis = SimpleNamespace(
            chunks=[{"s": 0, "e": 3, "children": [{"s": 2, "e": 4}]}],
            source_tokens=["a", "b", "c"],
            evidence=SimpleNamespace(relations=SimpleNamespace(diagnostics=[])),
        )
        self.assertEqual(probe.structural_errors(analysis), ["child containment or sibling overlap"])
        analysis.chunks = [{"s": 0, "e": 2}, {"s": 1, "e": 3}]
        self.assertEqual(probe.structural_errors(analysis), ["top-level token coverage"])


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark import peak_rss_bytes, summarize
from external_evaluation import convert, load_cases, select
from model_integrity import verify_directory, verify_ollama
from relation_evaluation import evaluate


class ReproducibilityTests(unittest.TestCase):
    def test_model_integrity_rejects_tampering_missing_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"known model")
            manifest = {"version": 1, "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}}
            verify_directory(directory, manifest)
            path.write_bytes(b"changed model")
            with self.assertRaises(ValueError):
                verify_directory(directory, manifest)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                verify_directory(directory, manifest)
            with self.assertRaises(ValueError):
                verify_directory(directory, {"version": 1, "files": {"../model.bin": "bad"}})
            with self.assertRaises(ValueError):
                verify_directory(directory, {"version": 1, "files": {}})

    def test_translation_digest_is_not_just_a_mutable_tag(self):
        expected = {"name": "model:tag", "digest": "locked"}
        verify_ollama({"models": [expected]}, expected)
        for payload in ({"models": []}, {"models": [{"name": "model:tag", "digest": "changed"}]}):
            with self.assertRaises(ValueError):
                verify_ollama(payload, expected)

    def test_benchmark_summary_and_memory_units(self):
        self.assertEqual(summarize([3, 1, 2]), {"samples": [3, 1, 2], "median": 2, "p95": 3})
        for values in ([], [-1], [float("nan")], [float("inf")]):
            with self.assertRaises(ValueError):
                summarize(values)
        self.assertEqual(peak_rss_bytes(4096, "Darwin"), 4096)
        self.assertEqual(peak_rss_bytes(4, "Linux"), 4096)

    def test_external_selection_requires_integrity_and_all_genres(self):
        with self.assertRaises(ValueError):
            select(b"", 20)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.conllu"
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_cases(path, {"source_sha256": "incorrect"})

    def test_unaligned_target_stays_in_evaluation_denominator(self):
        graph = SimpleNamespace(diagnostics=(), clauses=[SimpleNamespace(predicate=0, parent=None)], edges=[], coordinations=[])
        analysis = SimpleNamespace(source_tokens=["read"], evidence=SimpleNamespace(relations=graph), chunks=[{"text": "read"}])
        case = {"id": "alignment", "text": "example", "root": "read",
                "checks": [["backbone", "subject", "read", "missing"], ["backbone", "object", "read", "absent"]]}
        report = evaluate([case], lambda text: analysis, strict_anchors=False)
        self.assertEqual(report["checks"]["backbone"], {"passed": 0, "total": 2})
        self.assertEqual(report["checks"]["alignment"], {"passed": 0, "total": 2})

    def test_external_conversion_reads_gold_not_parser_output(self):
        rows = [
            ("The", "DET", 2, "det"), ("students", "NOUN", 3, "nsubj"),
            ("read", "VERB", 0, "root"), ("the", "DET", 6, "det"),
            ("long", "ADJ", 6, "amod"), ("report", "NOUN", 3, "obj"),
            ("yesterday", "ADV", 3, "advmod"), (".", "PUNCT", 3, "punct"),
        ]
        block = "# sent_id = email-test\n# text = The students read the long report yesterday.\n"
        block += "\n".join(f"{index}\t{word}\t_\t{pos}\t_\t_\t{head}\t{relation}\t_\t_"
                           for index, (word, pos, head, relation) in enumerate(rows, 1))
        case = convert(block)
        self.assertEqual(case["root"], "read")
        self.assertIn(["backbone", "subject", "read", "students"], case["checks"])
        self.assertIn(["backbone", "object", "read", "report"], case["checks"])
        self.assertIn(["attachment", "nominal-modifier", "report", "long"], case["checks"])
        self.assertIsNone(convert(block.replace("\tnsubj\t", "\tcop\t")))

    def test_lock_and_bundle_cover_runtime_artifacts(self):
        import tomllib

        root = Path(__file__).resolve().parent.parent
        lock = tomllib.loads((root / "sidecar/server.py.lock").read_text())
        self.assertGreater(len(lock["package"]), 50)
        for package in lock["package"]:
            self.assertTrue(package["version"])
            artifacts = package.get("wheels", []) + ([package["sdist"]] if "sdist" in package else [])
            self.assertTrue(artifacts, package["name"])
            self.assertTrue(all(artifact["hash"].startswith("sha256:") for artifact in artifacts), package["name"])
        bundle = (root / "scripts/bundle.sh").read_text()
        for artifact in ("server.py.lock", "model-lock.json", ".python-version", "benchmark_cases.json", "external_eval_manifest.json"):
            self.assertIn(f"cp sidecar/{artifact}", bundle)
        manifest = json.loads((root / "sidecar/external_eval_manifest.json").read_text())
        self.assertEqual(len(manifest["case_ids"]), 100)
        self.assertEqual(len(set(manifest["case_ids"])), 100)


if __name__ == "__main__":
    unittest.main()

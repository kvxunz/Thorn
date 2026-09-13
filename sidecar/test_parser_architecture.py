import ast
import copy
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from syntax_assembly import StructuralNode
from syntax_decomposition import plan_roots, requires_decomposition
from syntax_structure import StructureKind, SyntaxRoot, SyntaxStructure
from teaching_policy import TeachingPolicy


class ParserArchitectureTests(unittest.TestCase):
    def test_structural_payload_is_detached_from_projection_mutations(self):
        original = {"text": "a phrase", "role": "subject", "_lo": 0, "_hi": 1,
                    "children": [{"text": "a", "role": "subject", "_lo": 0, "_hi": 0,
                                  "children": None}]}
        structural = StructuralNode.from_payload(original)
        projected = structural.payload()
        projected["children"][0]["role"] = "object"
        projected["text"] = "changed"
        self.assertEqual(structural.payload(), original)
        with self.assertRaises(TypeError):
            StructuralNode((("mutable", []),))

    def test_display_policy_does_not_read_dependency_evidence(self):
        tree = ast.parse(Path(__file__).with_name("teaching_policy.py").read_text())
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"__future__", "dataclasses"})

    def test_structure_layers_cannot_import_projection_or_service(self):
        root = Path(__file__).parent
        for path in root.glob("syntax_*.py"):
            name = path.stem
            tree = ast.parse((root / f"{name}.py").read_text())
            type_only = {id(child) for node in ast.walk(tree)
                         if isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                         and node.test.id == "TYPE_CHECKING" for child in ast.walk(node)}
            modules = set()
            for node in ast.walk(tree):
                if id(node) in type_only:
                    continue
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.add(node.module.split(".")[0])
                elif isinstance(node, ast.Import):
                    modules.update(alias.name.split(".")[0] for alias in node.names)
            with self.subTest(module=name):
                self.assertFalse(modules & {
                    "server", "teaching_tree", "teaching_projection", "teaching_policy", "fastapi",
                })

    def test_service_no_longer_contains_builder_or_grammar_decisions(self):
        tree = ast.parse(Path(__file__).with_name("server.py").read_text())
        functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        self.assertFalse(functions & {
            "chunk_roots", "build_chunks", "np_expand", "clause_role_for",
            "expands_as_nominal", "expands_as_prep_phrase", "relative_role",
        })

    def test_syntax_root_has_no_display_flag_and_is_immutable(self):
        self.assertEqual({field.name for field in fields(SyntaxRoot)}, {"index", "role", "kind"})
        spec = SyntaxRoot(0, "subject", StructureKind.NOMINAL)
        with self.assertRaises(FrozenInstanceError):
            spec.role = "object"

    def test_structure_is_cached_independently_of_display_policy(self):
        doc = [SimpleNamespace(i=0)]
        roots = (SyntaxRoot(0, "subject", StructureKind.NOMINAL),)
        structure = SyntaxStructure(doc)
        with patch("syntax_structure.collect_roots", return_value=roots) as collect:
            self.assertIs(structure.roots(0), roots)
            TeachingPolicy(max_depth=0).project([{"text": "example", "children": None}])
            self.assertIs(structure.roots(0), roots)
            collect.assert_called_once_with(doc[0], None)

    def test_display_policy_copies_tree_without_changing_roles_or_spans(self):
        chunks = [{"id": "0", "s": 0, "e": 3, "role": "subject", "text": "a nested phrase",
                   "children": [{"id": "0.0", "s": 0, "e": 1, "role": "subject", "text": "a",
                                 "children": None}]}]
        original = copy.deepcopy(chunks)
        projected = TeachingPolicy(max_depth=0).project(chunks)
        self.assertIsNone(projected[0]["children"])
        self.assertEqual(chunks, original)
        for key in ("id", "s", "e", "role", "text"):
            self.assertEqual(projected[0][key], chunks[0][key])
        self.assertEqual(TeachingPolicy().project(chunks), chunks)
        with self.assertRaises(ValueError):
            TeachingPolicy(max_depth=-1)

    def test_decomposition_dispatch_covers_every_structure_kind(self):
        token = SimpleNamespace(i=0, text="word", dep_="ROOT", pos_="NOUN", lower_="word",
                                children=[], subtree=[])
        token.subtree = [token]
        token.doc = [token]
        token.head = token
        for kind in StructureKind:
            with self.subTest(kind=kind):
                spec = SyntaxRoot(0, "subject", kind)
                result = requires_decomposition(spec, token.doc)
                self.assertEqual(result, kind == StructureKind.CLAUSAL)
                self.assertEqual(plan_roots((spec,), token.doc), [(token, "subject", result)])

    def test_structure_roots_never_depend_on_display_depth(self):
        tree = ast.parse(Path(__file__).with_name("syntax_clause.py").read_text())
        calls = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "roots":
                calls += 1
                self.assertEqual(len(node.args), 1)
                self.assertFalse(node.keywords)
        self.assertGreater(calls, 0)

    def test_snapshot_gate_includes_all_structure_and_projection_modules(self):
        root = Path(__file__).resolve().parent.parent
        gate = (root / "scripts/githooks/pre-commit").read_text()
        for module in ("syntax_features", "syntax_structure", "syntax_assembly", "syntax_decomposition",
                       "syntax_boundaries", "syntax_clause", "syntax_nominal", "syntax_grouping",
                       "syntax_policy", "syntax_relations", "teaching_projection", "teaching_policy"):
            with self.subTest(module=module):
                self.assertIn(f"sidecar/{module}.py", gate)

    def test_recursive_nominal_analysis_has_no_back_import(self):
        root = Path(__file__).parent
        nominal = ast.parse((root / "syntax_nominal.py").read_text())
        imports = {node.module for node in ast.walk(nominal) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imports & {"syntax_clause", "syntax_assembly"})
        entry = next(node for node in nominal.body if isinstance(node, ast.FunctionDef) and node.name == "analyze_nominal")
        self.assertIn("analyze_clause", [arg.arg for arg in entry.args.kwonlyargs])
        for name in ("syntax_assembly", "syntax_boundaries", "syntax_nominal", "syntax_grouping", "syntax_clause"):
            self.assertLess(len((root / f"{name}.py").read_text().splitlines()), 750)


if __name__ == "__main__":
    unittest.main()

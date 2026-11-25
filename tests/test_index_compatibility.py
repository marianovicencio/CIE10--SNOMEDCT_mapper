"""Source refactors never authorize arbitrary builders, encoders or manifests."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cie10.mapping_context import ContextError
from cie10.retrieval_core import sha256
from cie10.retrieval_configuration import verify_index_implementation

ROOT = Path(__file__).resolve().parents[1]

class IndexImplementationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "cie10").mkdir()
        (self.root / "config").mkdir()
        for name in ["full_retrieval.py", "retrieval_core.py"]:
            (self.root / "cie10" / name).write_text("versioned implementation: " + name)
        self.current = {
            "builder": sha256(self.root / "cie10/full_retrieval.py"),
            "encoder": sha256(self.root / "cie10/retrieval_core.py"),
        }
        self.original = {"builder": "original-builder", "encoder": "original-encoder"}

    def info(self, pair):
        return {"implementation_sha256": pair["builder"],
                "encoder_implementation_sha256": pair["encoder"]}

    def migration(self):
        (self.root / "config/index-compatibility.json").write_text(json.dumps({
            "policy": "unchanged_algorithms_source_refactor_v1",
            "original": self.original, "refactored": self.current,
        }))

    def test_exact_new_build_needs_no_legacy_exception(self):
        self.assertEqual(verify_index_implementation(self.info(self.current), self.root), "exact_source_hashes")

    def test_audited_refactor_preserves_original_manifest(self):
        self.migration()
        info = self.info(self.original)
        before = json.dumps(info, sort_keys=True)
        self.assertEqual(verify_index_implementation(info, self.root), "verified_refactor_compatibility")
        self.assertEqual(json.dumps(info, sort_keys=True), before)

    def test_legacy_without_explicit_migration_is_rejected(self):
        with self.assertRaises(ContextError):
            verify_index_implementation(self.info(self.original), self.root)

    def test_changed_current_builder_or_encoder_is_rejected(self):
        self.migration()
        for name in ["full_retrieval.py", "retrieval_core.py"]:
            with self.subTest(file=name):
                path = self.root / "cie10" / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaises(ContextError):
                    verify_index_implementation(self.info(self.original), self.root)
                path.write_bytes(original)

    def test_unknown_and_mixed_source_pairs_are_rejected(self):
        self.migration()
        for pair in [{"builder": "unknown", "encoder": "unknown"},
                     {"builder": self.current["builder"], "encoder": self.original["encoder"]}]:
            with self.subTest(pair=pair), self.assertRaises(ContextError):
                verify_index_implementation(self.info(pair), self.root)

    def test_unknown_compatibility_policy_is_rejected(self):
        self.migration()
        path = self.root / "config/index-compatibility.json"
        path.write_text(path.read_text().replace("unchanged_algorithms_source_refactor_v1", "unreviewed"))
        with self.assertRaises(ContextError):
            verify_index_implementation(self.info(self.original), self.root)

    def test_committed_refactor_hashes_and_definition_proofs_match_code(self):
        migration = json.loads((ROOT / "config/index-compatibility.json").read_text())
        for key, path in [("builder", "cie10/full_retrieval.py"), ("encoder", "cie10/retrieval_core.py")]:
            self.assertEqual(sha256(ROOT / path), migration["refactored"][key])
        for definition, expected in migration["verified_definitions_sha256"].items():
            path, name = definition.split(":")
            node = next(n for n in ast.parse((ROOT / path).read_text()).body
                        if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
            actual = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
            self.assertEqual(actual, expected, definition)

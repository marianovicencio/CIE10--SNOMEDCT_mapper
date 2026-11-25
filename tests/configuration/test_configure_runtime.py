"""Portable setup must bind only complete, matching local assets."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("configure_public_runtime", ROOT / "scripts/configuration/configure_runtime.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class RuntimeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = self.root / "data/indexes/snomed/test"
        self.index.mkdir(parents=True)
        self.info = {"status": "completed", "schema_version": "0.2.0",
                     "catalog": {"version": module.EDITION},
                     "files": {"aliases.sqlite": "aliases", "embeddings.npy": "vectors"},
                     "implementation_sha256": "builder", "encoder_implementation_sha256": "encoder"}

    def invoke(self, flags=(), corrupt=False):
        (self.index / "index.json").write_text(json.dumps(self.info))
        def digest(path):
            return {"full_retrieval.py": "builder", "retrieval_core.py": "encoder"}.get(path.name, "fingerprint")
        def streamed(path):
            return "corrupt" if corrupt else {"aliases.sqlite": "aliases", "embeddings.npy": "vectors"}[path.name]
        store = Mock()
        store.context.return_value = {"source_snapshot_sha256": "this-installation-snapshot"}
        with patch.object(module, "ROOT", self.root), patch.object(module, "sha256", side_effect=digest), patch("cie10.retrieval.retrieval_configuration.sha256", side_effect=digest), patch.object(module, "streamed_sha256", side_effect=streamed), patch.object(module, "ContextStore", return_value=store), patch.object(sys, "argv", ["configure_runtime.py", "--index", "data/indexes/snomed/test", *flags]), contextlib.redirect_stdout(io.StringIO()):
            module.main()
        return self.root / "infra/retrieval"

    def test_complete_assets_write_machine_local_bindings(self):
        folder = self.invoke()
        self.assertEqual(len(list(folder.glob("active*.json"))), 3)
        config = json.loads((folder / "active-component-alignment.json").read_text())
        self.assertEqual(config["source_snapshot_sha256"], "this-installation-snapshot")
        self.assertFalse(config["clinical_validation"])

    def test_corrupt_index_never_writes_activation(self):
        with self.assertRaises(ValueError): self.invoke(corrupt=True)
        self.assertFalse((self.root / "infra/retrieval").exists())

    def test_other_edition_never_writes_activation(self):
        self.info["catalog"]["version"] = "different-edition"
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse((self.root / "infra/retrieval").exists())

    def test_changed_builder_never_writes_activation(self):
        self.info["implementation_sha256"] = "different-builder"
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse((self.root / "infra/retrieval").exists())

    def test_missing_optional_model_does_not_partially_activate(self):
        with self.assertRaises(ValueError): self.invoke(["--enable-reranker"])
        self.assertFalse((self.root / "infra/retrieval").exists())

    def test_incomplete_index_is_rejected(self):
        self.info["status"] = "running"
        with self.assertRaises(ValueError): self.invoke()
        self.assertFalse((self.root / "infra/retrieval").exists())

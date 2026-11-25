"""Bind locally prepared data to this checkout; no historical reports required.

This records technical consistency only. It does not certify clinical accuracy.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from cie10.api.context_api import ContextStore
from cie10.retrieval.full_retrieval_runtime import streamed_sha256
from cie10.retrieval.retrieval_configuration import EDITION, verify_index_implementation
from cie10.retrieval.retrieval_core import sha256
from cie10.retrieval.retrieval_title_fragments import POLICY as FRAGMENT_POLICY
from cie10.terminology.terminology_alignment import POLICY as COMPONENT_POLICY


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending.json")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def fingerprints(paths):
    return {name: sha256(ROOT / name) for name in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default="data/indexes/snomed/full-es-20261110-v1")
    parser.add_argument("--enable-reranker", action="store_true")
    args = parser.parse_args()
    index = (ROOT / args.index).resolve()
    if not index.is_relative_to(ROOT / "data/indexes/snomed"):
        raise ValueError("El índice debe estar en data/indexes/snomed.")
    info = json.loads((index / "index.json").read_text())
    if info.get("status") != "completed" or info.get("schema_version") != "0.2.0":
        raise ValueError("Se requiere un índice completo de formato 0.2.0.")
    if info.get("catalog", {}).get("version") != EDITION:
        raise ValueError("El índice no pertenece a la edición configurada.")
    for name in ("aliases.sqlite", "embeddings.npy"):
        if streamed_sha256(index / name) != info["files"][name]:
            raise ValueError("Archivo de índice modificado: " + name)
    verify_index_implementation(info, ROOT)
    # A fresh compilation has its own documentary snapshot. Never reuse the
    # developer's snapshot hash as an assertion about a different installation.
    snapshot = ContextStore().context("C76.4", "morbidity", 1, 0)["source_snapshot_sha256"]
    manifest = sha256(index / "index.json")
    common = {"status": "enabled_local_experimental", "index_manifest_sha256": manifest,
              "clinical_validation": False}
    fragment_files = ["cie10/retrieval/retrieval_title_fragments.py", "cie10/retrieval/retrieval_queries.py",
                      "cie10/retrieval/full_retrieval_runtime.py", "scripts/web/web_retrieval.py"]
    component_files = ["cie10/terminology/terminology_alignment.py", "cie10/explanations/explanation_contract.py",
                       "cie10/explanations/explanation_service.py", "cie10/explanations/explanation_attribution.py",
                       "cie10/explanations/explanation_focus.py", "cie10/explanations/explanation_limits.py"]
    component_files += [str(path.relative_to(ROOT)) for path in sorted((ROOT / "cie10/reasoning").glob("*.py"))]
    pending = {
        "active-index.json": {"path": str(index.relative_to(ROOT)), "index_manifest_sha256": manifest},
        "active-query-variants.json": {**common, "policy": FRAGMENT_POLICY,
                                       "implementation_sha256": fingerprints(fragment_files)},
        "active-component-alignment.json": {**common, "policy": COMPONENT_POLICY,
            "version": EDITION, "source_snapshot_sha256": snapshot,
            "implementation_sha256": fingerprints(component_files)},
    }
    if args.enable_reranker:
        from cie10.retrieval.shortlist_reranker import REPOSITORY, REVISION, POLICY
        downloaded = ROOT / "infra/retrieval/model-cache/download-manifests/bge-reranker-v2-m3.json"
        if not downloaded.is_file():
            raise ValueError("Descarga y verifica el reranker antes de habilitarlo.")
        model = json.loads(downloaded.read_text())
        if model.get("status") != "completed" or model.get("revision") != REVISION:
            raise ValueError("El reranker descargado tiene otra revisión.")
        pending["active-reranker.json"] = {**common, "repository": REPOSITORY,
            "revision": REVISION, "policy": POLICY,
            "implementation_sha256": fingerprints(["cie10/retrieval/shortlist_reranker.py", "cie10/retrieval/reranker_service.py"])}
    for name, value in pending.items():
        write(ROOT / "infra/retrieval" / name, value)
    print(json.dumps({"status": "configured", "index": str(index.relative_to(ROOT)),
                      "version": EDITION, "clinical_validation": False}))


if __name__ == "__main__":
    main()

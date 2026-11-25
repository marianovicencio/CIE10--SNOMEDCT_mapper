"""Review-only semantic proposals. Similarity never creates a verified binding.

The original assertion spans and scope travel beside each proposal. No diagnosis,
request or generated explanation is written to disk by this module.
"""

import importlib.metadata
import sqlite3
from pathlib import Path

from . import full_retrieval as stored
from .full_retrieval import semantic_search_batch
from .full_retrieval_runtime import StreamedMatrix, streamed_sha256
from .mapping_context import ContextError, digest
from .reasoning.assertions import extract_assertions
from .retrieval_configuration import load_active_index
from .retrieval_evaluation import TransformerRetriever, sha256
from .terminology_alignment import ComponentResolver, canonical, match_kind

POLICY = "review_only_semantic_phrase_proposals_v1"


def prepare_phrases(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        raise ContextError("Se requiere un texto de entre 1 y 1.000 caracteres.")
    frames = extract_assertions(text, "INPUT", input_text=True)
    phrases = {}
    for frame in frames:
        start, end = frame.body_span
        key = (start, end)
        if key not in phrases:
            phrases[key] = {
                "span": [start, end],
                "text": text[start:end],
                "assertions": [],
            }
        phrases[key]["assertions"].append(frame.trace())
    if not phrases or len(phrases) > 4:
        raise ContextError("Usa de una a cuatro frases breves y explícitas.")
    for phrase in phrases.values():
        scopes = phrase["assertions"]
        # A feature's absence is not absence of the whole condition.
        denied = any(
            x["construction"] == "condition" and x["value"] == "absent" for x in scopes
        )
        if any(x["subject"] != "patient" for x in scopes):
            scope = "other_subject"
        elif any(x["modality"] == "hypothetical" for x in scopes):
            scope = "hypothetical"
        elif any(x["modality"] == "historical" for x in scopes):
            scope = "historical"
        elif any(x["modality"] != "asserted" for x in scopes):
            scope = "uncertain"
        elif denied:
            scope = "negated"
        else:
            scope = "asserted"
        phrase["scope"] = scope
        phrase["scope_is_exhaustive"] = False
    return list(phrases.values())


def published_attributes(verified, resolver):
    """Expose published attributes without inferring new anatomy from the input.

    This is a FHIR lookup projection, not a complete role-group representation.
    Every part is retained for selected properties; no relationship is invented.
    """
    if "_proposal_attributes" not in verified:
        data = resolver.verifier.get(verified["request_path"])
        if digest(data) != verified["response_sha256"]:
            raise ContextError("Cambió la respuesta de origen al leer sus atributos.")
        attributes = []
        for prop in data.get("parameter", []):
            if prop.get("name") != "property":
                continue
            codes = [
                p.get("valueCode")
                for p in prop.get("part", [])
                if p.get("name") == "code"
            ]
            if (
                len(codes) == 1
                and isinstance(codes[0], str)
                and (codes[0].isdigit() or codes[0] == "parent")
            ):
                attributes.append(prop)
        verified["_proposal_attributes"] = attributes
    return verified["_proposal_attributes"]


def review_candidate(candidate, phrase, resolver):
    verified = resolver._concept(candidate["concept_id"])
    if candidate["term"] not in verified["labels"]:
        raise ContextError("El término recuperado no aparece en la edición verificada.")
    kind = match_kind(canonical(phrase["text"]), canonical(candidate["term"]))
    if not canonical(phrase["text"]):
        kind = None
    clinical = verified["clinical_finding_scope"]
    return {
        "concept_id": candidate["concept_id"],
        "matched_description": candidate["term"],
        "description_id": candidate["description_id"],
        "official_spanish_descriptions": verified["labels"],
        "published_fhir_attributes": published_attributes(verified, resolver),
        "attributes_are_lookup_projection": True,
        "complete_role_groups": False,
        "similarity": candidate["score"],
        "score_is_probability": False,
        "match_basis": kind or "semantic_similarity_only",
        "status": "review_required" if clinical else "outside_clinical_finding_scope",
        "clinical_finding_scope": clinical,
        "input_scope": phrase["scope"],
        "input_scope_restricted": phrase["scope"] != "asserted",
        "patient_assertion": False,
        "implies_clinical_equivalence": False,
        "usable_as_verified_component_binding": False,
        "evidence": {
            "lookup_path": verified["request_path"],
            "lookup_sha256": verified["response_sha256"],
            "activity": verified["active_check"],
            "clinical_finding_subsumption": verified["scope_verification"],
        },
    }


class PhraseProposalEngine:
    def __init__(self, root, device="cuda"):
        self.root = Path(root).resolve()
        self.index, self.info = load_active_index(self.root)
        self.device = device
        self.engine = self.db = self.matrix = self.resolver = None

    def __enter__(self):
        try:
            info, index = self.info, self.index
            if (
                info["schema_version"] != "0.2.0"
                or info["catalog"]["kind"] != "snomed_rf2_snapshot"
            ):
                raise ContextError("Se requiere el índice completo RF2 verificado.")
            if info["implementation_sha256"] != sha256(stored.__file__) or info[
                "encoder_implementation_sha256"
            ] != sha256(Path(__file__).with_name("retrieval_evaluation.py")):
                raise ContextError("Cambió el constructor o el codificador del índice.")
            if any(
                importlib.metadata.version(p) != v for p, v in info["packages"].items()
            ):
                raise ContextError("El entorno no corresponde al índice activo.")
            for name in ("aliases.sqlite", "embeddings.npy"):
                if streamed_sha256(index / name) != info["files"][name]:
                    raise ContextError("Cambió un archivo del índice semántico.")
            import numpy as np

            header = np.load(
                index / "embeddings.npy", mmap_mode="r", allow_pickle=False
            )
            try:
                if (
                    header.shape != (info["aliases"], info["embedding_dimension"])
                    or header.dtype != np.float32
                ):
                    raise ContextError("Forma o tipo incorrecto del índice.")
                self.matrix = StreamedMatrix(
                    index / "embeddings.npy", header.offset, header.shape, header.dtype
                )
            finally:
                header._mmap.close()
            self.db = sqlite3.connect(
                (index / "aliases.sqlite").as_uri() + "?mode=ro", uri=True
            )
            self.resolver = ComponentResolver(index, version=info["catalog"]["version"])
            self.resolver.verifier.require_version()
            self.resolver.checked_version = True
            self.engine = TransformerRetriever(
                info["model"],
                self.device,
                str(self.root / "infra/retrieval/model-cache"),
                64,
                8,
            )
            return self
        except BaseException:
            self.close()
            raise

    def propose_batch(self, texts, top_k=5):
        if not isinstance(texts, list) or not 1 <= len(texts) <= 16:
            raise ContextError("El lote admite de 1 a 16 entradas.")
        if type(top_k) is not int or not 1 <= top_k <= 5:
            raise ContextError("Se admiten de 1 a 5 propuestas.")
        prepared = [prepare_phrases(text) for text in texts]
        phrases = [phrase for group in prepared for phrase in group]
        if len(phrases) > 16:
            raise ContextError("El lote supera las 16 frases.")
        raw = self.engine.tokenizer(
            [p["text"] for p in phrases], add_special_tokens=True, truncation=False
        )["input_ids"]
        if any(len(tokens) > 64 for tokens in raw):
            raise ContextError(
                "Una frase supera los 64 tokens. Acórtala sin perder sus calificadores."
            )
        encoded = self.engine.encode(
            [p["text"] for p in phrases], [str(i) for i in range(len(phrases))], "query"
        )
        rankings = semantic_search_batch(self.db, self.matrix, encoded, top_k)
        offset = 0
        answers = []
        for group in prepared:
            reviewed = []
            for phrase in group:
                candidates = [
                    review_candidate(c, phrase, self.resolver) for c in rankings[offset]
                ]
                reviewed.append(
                    {
                        **phrase,
                        "candidates": [
                            dict(c, rank=i) for i, c in enumerate(candidates, 1)
                        ],
                    }
                )
                offset += 1
            answers.append(
                {
                    "status": "semantic_proposals_unreviewed",
                    "policy": POLICY,
                    "version": self.info["catalog"]["version"],
                    "index_manifest_sha256": sha256(self.index / "index.json"),
                    "model": self.info["model"],
                    "phrases": reviewed,
                    "automatic_selection": False,
                    "clinical_validation": False,
                    "limitations": [
                        "La similitud no demuestra equivalencia clínica ni valida el código CIE-10.",
                        "La extracción de alcance reconoce construcciones explícitas; requiere revisión humana.",
                        "La anatomía, los atributos y las reglas de los tres tomos deben contrastarse antes del mapeo.",
                        "El top 5 puede omitir la interpretación correcta; no se inventa un destino cuando falta.",
                    ],
                }
            )
        return answers

    def close(self):
        for resource in (self.engine, self.db, self.matrix, self.resolver):
            if resource is not None:
                resource.close()
        self.engine = self.db = self.matrix = self.resolver = None

    def __exit__(self, *_):
        self.close()

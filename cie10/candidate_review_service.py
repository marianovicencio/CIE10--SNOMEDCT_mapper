"""Adapt the existing context reviewer to an already retrieved candidate pool.

No second embedding search, model generation or persisted diagnosis. No new
clinical rule is introduced here; original retrieval positions are retained.
"""

from pathlib import Path
import re

from .mapping_context import CODE, HASH, ContextError
from .retrieval_configuration import load_active_index, EDITION
from .full_retrieval_runtime import streamed_sha256
from .terminology_alignment import ComponentResolver
from .semantic_proposals import published_attributes
from .reasoning.assertions import extract_assertions
from .proposal_context import CIEContextReviewer, sites
from .reasoning.comparisons import label_comparison_kind


def validate_request(request):
    fields = {
        "code",
        "diagnostic_text",
        "concept_ids",
        "source_snapshot_sha256",
        "target_version",
    }
    if not isinstance(request, dict) or set(request) - fields:
        raise ContextError("Consulta contextual inválida.")
    code = request.get("code")
    ids = request.get("concept_ids")
    text = request.get("diagnostic_text", "")
    snapshot = request.get("source_snapshot_sha256")
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise ContextError("Código inválido.")
    if not isinstance(text, str) or len(text) > 4000:
        raise ContextError("Texto demasiado largo.")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= 5
        or any(
            not isinstance(cid, str) or not re.fullmatch(r"[0-9]{6,18}", cid)
            for cid in ids
        )
        or len(set(ids)) != len(ids)
    ):
        raise ContextError("Se requieren entre uno y cinco candidatos distintos.")
    if (
        not isinstance(snapshot, str)
        or not HASH.fullmatch(snapshot)
        or request.get("target_version") != EDITION
    ):
        raise ContextError("Faltan las versiones de la búsqueda.")
    return dict(request, diagnostic_text=text)


def input_scope(text):
    if not text.strip():
        return "not_provided"
    frames = extract_assertions(text, "INPUT", input_text=True)
    if not frames:
        return "uncertain"
    if any(x.subject != "patient" for x in frames):
        return "other_subject"
    for mode in ["hypothetical", "historical", "uncertain"]:
        if any(x.modality == mode for x in frames):
            return mode
    if any(x.construction == "condition" and x.value == "absent" for x in frames):
        return "negated"
    return "asserted"


def review_candidates(request, root):
    request = validate_request(request)
    index, info = load_active_index(root)
    if streamed_sha256(index / "aliases.sqlite") != info["files"]["aliases.sqlite"]:
        raise ContextError("Cambió el catálogo local de términos.")
    resolver = ComponentResolver(
        index, version=request["target_version"], relation_budget=32
    )
    try:
        reviewer = CIEContextReviewer(
            root, request["code"], request["diagnostic_text"], resolver
        )
        if reviewer.snapshot != request["source_snapshot_sha256"]:
            raise ContextError("La documentación cambió desde la búsqueda.")
        candidates = []
        scope = input_scope(request["diagnostic_text"])
        for rank, cid in enumerate(request["concept_ids"], 1):
            concept = resolver._concept(cid)
            attributes = published_attributes(concept, resolver)
            review = reviewer.review(
                {
                    "concept_id": cid,
                    "clinical_finding_scope": concept["clinical_finding_scope"],
                    "published_fhir_attributes": attributes,
                },
                {"scope": scope},
            )
            review["finding_sites"] = {
                "cie": reviewer.anchor["sites"],
                "candidate": sites(attributes),
            }
            # Available before explanation generation, using version-verified labels.
            title = reviewer.title
            kind = next(
                (
                    kind
                    for label in concept.get("labels", [])
                    if (kind := label_comparison_kind(title, label))
                ),
                None,
            )
            review["automatic_comparison"] = (
                {
                    "kind": kind,
                    "text": (
                        "Coincidencia de nombres"
                        if kind == "literal"
                        else "Coincidencia de nombres al normalizar artículos y contracciones"
                    ),
                }
                if kind
                and not review.get("constraint")
                and review["status"] != "excluded_by_explicit_constraint"
                else None
            )
            candidates.append({"id": cid, "retrieval_rank": rank, "review": review})
        return {
            "status": "candidate_context_review_available",
            "code": request["code"],
            "source_snapshot_sha256": reviewer.snapshot,
            "target_version": resolver.version,
            "candidates": [dict(c, rank=i) for i, c in enumerate(candidates, 1)],
            "candidate_set_preserved": True,
            "automatic_selection": False,
            "clinical_validation": False,
            "anatomical_anchor": reviewer.anchor,
            "coverage": "implemented_documentary_constraints_not_exhaustive_clinical_validation",
        }
    finally:
        resolver.close()

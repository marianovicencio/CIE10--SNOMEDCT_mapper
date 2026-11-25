"""Public explanation error, source anchors and response schema."""

from cie10.reasoning.policy import anatomical_exclusion
from cie10.explanations.explanation_limits import MAX_CLAIMS, MAX_CLAIM_CHARACTERS
from cie10.reasoning.assertion_comparison import assertion_constraint
from cie10.reasoning.grounded_alignment import grounded_constraint


class ExplanationError(ValueError):
    """A response cannot be presented as a validated explanation."""


def comparison_anchors(evidence, diagnostic):
    anchors = []
    for kind, role in [("CIE10", "title"), ("SNOMED", "candidate_term")]:
        item = next(
            (x for x in evidence if x["type"] == kind and x.get("role") == role), None
        )
        item = item or next((x for x in evidence if x["type"] == kind), None)
        if not item:
            raise ExplanationError(
                "Falta una fuente de base para comparar CIE-10 y SNOMED."
            )
        anchors.append(item["id"])
    if diagnostic:
        item = next((x for x in evidence if x["type"] == "INPUT"), None)
        if not item:
            raise ExplanationError("Falta la fuente del diagnóstico aportado.")
        anchors.append(item["id"])
    return anchors


def response_schema(concept_id, diagnostic, evidence):
    """Constrain references by source type; the server supplies verbatim quotes."""
    ids = [item["id"] for item in evidence]
    anchors = comparison_anchors(evidence, diagnostic)
    claim = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "maxLength": MAX_CLAIM_CHARACTERS},
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "enum": ids},
                "minItems": len(anchors),
                "maxItems": min(len(ids), len(anchors) + 3),
                "uniqueItems": True,
            },
        },
        "required": ["text", "evidence_refs"],
        "additionalProperties": False,
    }
    # Fixed-prefix tuple alternatives keep mandatory anchors in local decoding.
    # Optional context slots use known IDs; the validator also checks uniqueness.
    context_ids = [ref for ref in ids if ref not in anchors]
    references = claim["properties"]["evidence_refs"]
    references["anyOf"] = [
        {"type": "array", "items":
            [{"type": "string", "enum": [ref]} for ref in anchors]
            + [{"type": "string", "enum": context_ids} for _ in range(extra)],
         "minItems": len(anchors) + extra, "maxItems": len(anchors) + extra,
         "additionalItems": False}
        for extra in range(min(3, len(context_ids)) + 1)
    ]
    structured = assertion_constraint(evidence) or grounded_constraint(evidence)
    allowed_assessments = (
        [structured["assessment"]]
        if structured
        else (
            ["incompatible", "undetermined"]
            if anatomical_exclusion(evidence)
            else ["compatible", "incompatible", "undetermined"]
        )
    )
    properties = {
        "concept_id": {"type": "string", "enum": [concept_id]},
        "assessment": {
            "type": "string",
            "enum": allowed_assessments,
        },
        "claims": {"type": "array", "items": claim, "minItems": 1, "maxItems": MAX_CLAIMS},
        "additional_detail_needed": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }

"""Compare source-aligned assertions; this layer can reject/defer, never approve."""

from .assertions import extract_assertions, align
from ..explanation_constraints import source


def compare_sources(left, right):
    aligned = []
    for a in left:
        for b in right:
            pair = align(a, b)
            if pair:
                aligned.append(pair)
    return aligned


def heading_conflict(title, term):
    a = extract_assertions(title, "heading")
    b = extract_assertions(term, "candidate")
    return any(
        x.value != y.value and {x.value, y.value} == {"present", "absent"}
        for x, y in compare_sources(a, b)
    )


def assertion_constraint(evidence):
    title = source(evidence, "CIE10", "title", "cie-title")
    term = source(evidence, "SNOMED", "candidate_term", "snomed-term")
    entry = next((x for x in evidence if x["type"] == "INPUT"), None)
    if not title or not term:
        return None
    left = extract_assertions(title["text"], title["id"])
    right = extract_assertions(term["text"], term["id"])
    for alias in evidence:
        if (
            alias.get("role") == "candidate_alias"
            and alias.get("concept_id") == term.get("concept_id")
            and alias.get("concept_id")
        ):
            right.extend(extract_assertions(alias["text"], alias["id"]))
    input_frames = extract_assertions(entry["text"], entry["id"], True) if entry else []
    refs = [title["id"], term["id"]] + ([entry["id"]] if entry else [])

    def decision(kind, assessment, pair):
        a, b = pair
        reason = {
            "polarity_conflict": "CIE-10 y SNOMED, o su contexto de entrada, expresan valores opuestos de una misma característica en la misma afección. La presencia y la ausencia explícitas no respaldan una correspondencia compatible.",
            "hypothetical_scope": "La afección comparada aparece en una hipótesis, no como afirmación actual del paciente. Coincidir en palabras con CIE-10 y SNOMED no basta para proponer la correspondencia.",
            "unasserted_scope": "El contexto no afirma esa característica como un hecho actual del paciente. La comparación CIE-10 y SNOMED requiere aclarar su sujeto o su alcance.",
            "contradictory_input": "La entrada afirma y niega la misma característica para la misma afección. Esa contradicción debe aclararse antes de proponer la correspondencia.",
        }[kind]
        own_refs = list(dict.fromkeys(refs + [a.source_id, b.source_id]))
        return {
            "rule_id": "assertion_" + kind,
            "assessment": assessment,
            "justification": reason,
            "additional_detail_needed": (
                []
                if assessment == "incompatible"
                else ["Aclarar la afirmación actual y a quién corresponde la afección."]
            ),
            "evidence_refs": own_refs,
            "comparison_trace": {
                "policy": "aligned_literal_assertions_v1",
                "left": a.trace(),
                "right": b.trace(),
                "alignment": "same_condition_and_feature",
                "clinical_synonym_inference": False,
            },
        }

    for a, b in compare_sources(left, right):
        if {a.value, b.value} == {"present", "absent"}:
            return decision("polarity_conflict", "incompatible", (a, b))
    # Contradictory actual patient statements take precedence over a single clause.
    for a, b in compare_sources(input_frames, input_frames):
        if (
            a.subject == b.subject == "patient"
            and a.modality == b.modality == "asserted"
            and {a.value, b.value} == {"present", "absent"}
        ):
            return decision("contradictory_input", "undetermined", (a, b))
    pending = []
    for a, b in compare_sources(left + right, input_frames):
        if b.subject != "patient" or b.modality != "asserted":
            pending.append((a, b))
            continue
        if {a.value, b.value} == {"present", "absent"}:
            return decision("polarity_conflict", "incompatible", (a, b))
        if b.value == "unknown":
            pending.append((a, b))
    if pending:
        pair = pending[0]
        kind = (
            "hypothetical_scope"
            if pair[1].modality == "hypothetical"
            else "unasserted_scope"
        )
        return decision(kind, "undetermined", pair)
    return None

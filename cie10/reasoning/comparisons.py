"""Source-bound literal/grammatical compatibility and conservative uncertainty.

Literal compatibility is not a validated clinical equivalence. The conservative
response preserves abstention after failed generation; it never approves a map."""

import re
from cie10.explanations.explanation_constraints import normalize, source
from cie10.reasoning.text import clean


def grammatical_label(text):
    """Normalize Spanish articles only within a de-phrase before a lowercase word.

    Preserve content words, their order, negations and other prepositions. Do not
    strip articles globally: El Tor and names such as de la Cruz are meaningful.
    Capitalized or unfamiliar constructions deliberately retain the fallback.
    Sources and quotations are never rewritten.
    """
    text = re.sub(r"\bdel(?=\s+[a-záéíóúüñ])", "de", text)
    text = re.sub(r"\bde\s+(?:el|la|los|las)(?=\s+[a-záéíóúüñ])", "de", text)
    return clean(text)


def label_comparison_kind(left, right):
    if clean(left) == clean(right):
        return "literal"
    if grammatical_label(left) == grammatical_label(right):
        return "grammatical"
    return None


def literal_label_analysis(concept_id, diagnostic, evidence):
    title = source(evidence, "CIE10", "title", "cie-title")
    term = source(evidence, "SNOMED", "candidate_term", "snomed-term")
    if not title or not term:
        return None
    kind = label_comparison_kind(title["text"], term["text"])
    if not kind:
        return None
    # Literal identity is documentary compatibility, never proof of clinical equivalence.
    matched_alias = None
    if diagnostic:
        phrases = [
            (grammatical_label(term["text"]), None),
            (grammatical_label(title["text"]), None),
        ] + [
            (grammatical_label(x["text"]), x["id"])
            for x in evidence
            if x.get("role") == "candidate_alias" and x.get("concept_id") == concept_id
        ]
        supported = False
        for clause in re.split(r"[.;:!?\n]+", normalize(diagnostic)):
            text = grammatical_label(clause)
            for phrase, alias_id in phrases:
                match = (
                    re.search(
                        r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text
                    )
                    if phrase
                    else None
                )
                if not match:
                    continue
                prefix = text[: match.start()]
                if not re.search(
                    r"\b(?:madre|padre|familiar|antecedente|sospecha|niega|descarta|no|sin)\b",
                    prefix,
                ):
                    supported = True
                    matched_alias = alias_id
        if not supported:
            return None
    refs = [title["id"], term["id"]] + (
        [x["id"] for x in evidence if x["type"] == "INPUT"] if diagnostic else []
    )
    if matched_alias:
        refs.append(matched_alias)
    sources = {x["id"]: x for x in evidence}
    return dict(
        concept_id=concept_id,
        assessment="compatible",
        selection="proposed" if diagnostic else "not_requested",
        justification=(
            "El título CIE-10 y el término SNOMED coinciden literalmente en la afección, sin añadir un subtipo."
            if kind == "literal"
            else "El título CIE-10 y el término SNOMED coinciden al normalizar artículos y contracciones; conservan los términos de la afección y sus calificadores."
        )
        + " Esta coincidencia respalda la comparación documental."
        + (" La entrada menciona esa misma afección." if diagnostic else ""),
        evidence_refs=refs,
        quotes=[dict(evidence_id=r, text=sources[r]["text"]) for r in refs],
        additional_detail_needed=[],
    )

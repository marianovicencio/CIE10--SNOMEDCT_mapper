"""Explicit scope and qualifier checks. Unknown paraphrases remain unhandled.

These rules recognize limited written forms; they are not a clinical NLP model.
A returned restriction can reject or defer a proposal, never confirm disease."""

import re
from ..explanation_constraints import normalize, source
from .text import STOP, clean, absence, core


HYPOTHETICAL = re.compile(
    r"\bsi\b[^.;,]{0,70}\b(?:tuviera|tuviese|presentara|presentase|apareciera|desarrollara|se diagnosticara)\b[^.;,]*|\b(?:hipotesis|hipotetic[ao]|posible|sospecha de)\b[^.;,]*"
)


def qualifier_conflict(title, term):
    a, b = clean(title), clean(term)
    common = set(a.split()) & set(b.split()) - STOP - {"senil"}
    if not common:
        return False
    return bool(
        re.search(r"\bsenil\b", a)
        and re.search(r"\bsenil\b", b)
        and bool(re.search(r"\bno senil\b", a)) != bool(re.search(r"\bno senil\b", b))
    )


def scope_marker(text):
    return bool(HYPOTHETICAL.search(normalize(text)))


def safety_constraint(evidence):
    title = source(evidence, "CIE10", "title", "cie-title")
    term = source(evidence, "SNOMED", "candidate_term", "snomed-term")
    entry = next((x for x in evidence if x["type"] == "INPUT"), None)
    if not title or not term:
        return None
    refs = [title["id"], term["id"]] + ([entry["id"]] if entry else [])

    def result(rule, assessment, reason, missing=None):
        return dict(
            rule_id="safety_" + rule,
            assessment=assessment,
            justification=reason,
            additional_detail_needed=missing or [],
            evidence_refs=refs,
        )

    if qualifier_conflict(title["text"], term["text"]):
        return result(
            "opposed_senility",
            "incompatible",
            "El título CIE-10 y el candidato SNOMED expresan calificadores opuestos: senil frente a no senil. Esa contradicción impide respaldar la correspondencia.",
        )
    t = normalize(term["text"])
    phrase = clean(term["text"])
    text = normalize(entry["text"]) if entry else ""
    # Match a literal candidate phrase, not a broad window around any negation.
    if entry:
        for clause in re.split(r"[.;:!?\n]+|\bpero\b", text):
            m = re.search(
                r"\b(?:no (?:hay|tiene|presenta|padece)|niega|se descarta)\s+(?:la |el |una |un )?"
                + re.escape(phrase)
                + r"\s*$",
                clause,
            )
            if m and not re.search(
                r"\b(?:si|cuando|no|madre|padre|familiar)\b", clause[: m.start()]
            ):
                return result(
                    "literal_candidate_denied",
                    "incompatible",
                    "La entrada niega expresamente la afección nombrada por el candidato SNOMED. Aunque el título CIE-10 la mencione, esa contradicción impide proponer la correspondencia.",
                )
        anchor_words = set(core(term["text"]).split()) - STOP
        for m in HYPOTHETICAL.finditer(text):
            if anchor_words & set(clean(m[0]).split()):
                return result(
                    "hypothetical_condition",
                    "undetermined",
                    "La entrada presenta la afección del candidato SNOMED como hipótesis o posibilidad, no como diagnóstico actual. La coincidencia con el título CIE-10 no basta para proponer la correspondencia.",
                    [
                        "Aclarar si la afección es un diagnóstico actual confirmado en la entrada."
                    ],
                )
        if qualifier_conflict(title["text"], text) or qualifier_conflict(
            term["text"], text
        ):
            return result(
                "diagnostic_senility_conflict",
                "incompatible",
                "El diagnóstico y los términos comparados expresan calificadores opuestos de senilidad. Debe resolverse esa contradicción antes de proponer la correspondencia.",
            )
    # Explicit absence qualifiers: apply only within a shared literal condition head.
    same_core = core(title["text"]) == core(term["text"])
    if same_core:
        absent = absence(title["text"]) | absence(term["text"])
        if entry:
            heads = set(core(title["text"]).split()) - STOP
            for clause in re.split(r"[.;:!?\n]+", text):
                words = set(core(clause).split())
                if not heads & words:
                    continue
                for word in absent:
                    if re.search(
                        r"\bcon " + re.escape(word) + r"\b", clause
                    ) and word not in absence(clause):
                        return result(
                            "explicit_absence_contradicted",
                            "incompatible",
                            "El título CIE-10 o el candidato SNOMED exige ausencia de una afección que el diagnóstico afirma expresamente. Esa contradicción entre con y sin impide proponer la correspondencia.",
                        )
        extra = absence(term["text"]) - absence(title["text"]) - absence(text)
        if extra:
            return result(
                "additional_absence_unconfirmed",
                "undetermined",
                "El candidato SNOMED añade una ausencia que el título CIE-10 y la entrada no especifican: "
                + ", ".join(sorted(extra))
                + ". Ese detalle requiere revisión antes de proponer la correspondencia.",
                [
                    "Precisar la presencia o ausencia de "
                    + ", ".join(sorted(extra))
                    + "."
                ],
            )
    return None

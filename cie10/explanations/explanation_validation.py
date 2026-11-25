"""Validate structured explanations and readable source references.

Mechanical citation checks are separate from clinical validation."""

import re
from cie10.explanations.explanation_limits import MAX_EXPLANATION_WORDS
from cie10.explanations.explanation_contract import ExplanationError
from cie10.reasoning.policy import anatomical_exclusion, effective_constraint
from cie10.explanations.explanation_constraints import normalize, unasserted, scope_notes
from cie10.reasoning.manual_reasoning import allowed as manual_scope_allowed


def validate_explanation(answer, concept_id, diagnostic, evidence):
    if not isinstance(answer, dict):
        raise ExplanationError("La respuesta debe ser un objeto JSON.")
    fields = {
        "concept_id",
        "assessment",
        "justification",
        "selection",
        "quotes",
        "evidence_refs",
        "additional_detail_needed",
    }
    if set(answer) != fields:
        raise ExplanationError("La respuesta contiene campos ausentes o desconocidos.")
    for name in ("concept_id", "assessment", "justification", "selection"):
        if not isinstance(answer[name], str):
            raise ExplanationError("Un campo textual tiene un tipo incorrecto.")
    for name in ("evidence_refs", "additional_detail_needed"):
        if not isinstance(answer[name], list) or any(
            not isinstance(x, str) or not x.strip() for x in answer[name]
        ):
            raise ExplanationError("Una lista contiene valores inválidos.")
    if answer["concept_id"] != concept_id:
        raise ExplanationError(
            "El identificador no corresponde al candidato solicitado."
        )
    if answer["assessment"] not in ("compatible", "incompatible", "undetermined"):
        raise ExplanationError("La valoración no es válida.")
    if answer["selection"] not in (
        ["proposed", "abstained"] if diagnostic else ["not_requested"]
    ):
        raise ExplanationError(
            "Con solo código, No selecciones un diagnóstico ni inventes un texto del usuario."
        )
    if not answer["justification"].strip() or len(answer["justification"].split()) > MAX_EXPLANATION_WORDS:
        raise ExplanationError(f"La explicación debe tener entre 1 y {MAX_EXPLANATION_WORDS} palabras.")
    refs = answer["evidence_refs"]
    sources = {item["id"]: item for item in evidence}
    if len(sources) != len(evidence):
        raise ExplanationError("La evidencia tiene identificadores duplicados.")
    if (
        len(set(refs)) != len(refs)
        or not refs
        or any(ref not in sources for ref in refs)
    ):
        raise ExplanationError(
            "Las referencias contienen duplicados o identificadores desconocidos."
        )
    if not {"CIE10", "SNOMED"} <= {sources[ref]["type"] for ref in refs}:
        raise ExplanationError("Se requieren evidencias CIE-10 y SNOMED del candidato.")
    quotes = answer["quotes"]
    if not isinstance(quotes, list) or not quotes:
        raise ExplanationError("Faltan citas literales.")
    cited = set()
    for quote in quotes:
        if not isinstance(quote, dict) or set(quote) != {"evidence_id", "text"}:
            raise ExplanationError("Una cita tiene una estructura incorrecta.")
        ref, text = quote["evidence_id"], quote["text"]
        if (
            not isinstance(ref, str)
            or ref not in refs
            or not isinstance(text, str)
            or not text.strip()
        ):
            raise ExplanationError("Una cita carece de texto o referencia válida.")
        if text not in sources[ref]["text"]:
            raise ExplanationError("Una cita no reproduce literalmente la fuente.")
        cited.add(ref)
    if cited != set(refs):
        raise ExplanationError("Cada evidencia referida debe incluir una cita literal.")
    excluded_site = anatomical_exclusion(evidence)
    if excluded_site and answer["assessment"] == "compatible":
        raise ExplanationError(
            "El sitio anatómico SNOMED coincide con la exclusión explícita "
            + excluded_site
            + "."
        )
    constraint = effective_constraint(evidence)
    if constraint and answer["assessment"] != constraint["assessment"]:
        raise ExplanationError(
            "La valoración contradice la comprobación documental "
            + constraint["rule_id"]
            + "."
        )
    if len(answer["additional_detail_needed"]) > 3:
        raise ExplanationError("Se admiten hasta tres datos faltantes.")
    if answer["assessment"] == "compatible" and any(
        x.get("role") == "title" for x in evidence
    ):
        if not any(sources[ref].get("role") == "title" for ref in refs):
            raise ExplanationError(
                "Una compatibilidad debe citar el título CIE-10 y sus calificadores."
            )
    if answer["assessment"] == "compatible" and any(
        x.get("role") == "candidate_term" for x in evidence
    ):
        if not any(sources[ref].get("role") == "candidate_term" for ref in refs):
            raise ExplanationError(
                "Una compatibilidad debe citar el término del candidato, no solo sus padres o atributos."
            )
    for ref in refs:
        item = sources[ref]
        if (
            item.get("volume") == 3
            and item.get("requires_documentary_review")
            and answer["assessment"] != "undetermined"
        ):
            raise ExplanationError(
                "Una ambigüedad o remisión incompleta del índice exige revisión documental; no justifica una decisión definitiva."
            )
        if item.get("volume") == 2:
            if not manual_scope_allowed(item.get("scope")):
                raise ExplanationError(
                    "Una regla de mortalidad no puede justificar la consulta de morbilidad."
                )
            if (
                item.get("role") == "manual_example"
                and answer["assessment"] != "undetermined"
            ):
                raise ExplanationError(
                    "Un ejemplo del manual no demuestra hechos del paciente ni una correspondencia."
                )
    prose = normalize(answer["justification"])
    if re.search(
        r"se incluyen referencias|se incluye la informacion|para contextualizar la clasificacion|se incluyen tambien otras inclusiones",
        prose,
    ):
        raise ExplanationError(
            "Explica la diferencia o coincidencia concreta; elimina frases sobre referencias y listas de ejemplos que no forman parte de la entrada."
        )
    certainty = re.search(r"confirman? (?:la )?presencia", prose)
    if certainty and not unasserted(prose, certainty.start()):
        raise ExplanationError(
            "Se evalúa una correspondencia documental; no se confirma la presencia de una enfermedad en el paciente."
        )
    index_refs = [ref for ref in refs if sources[ref].get("volume") == 3]
    if (
        re.search(
            r"indice alfabetico|indice cie(?:-?10)?|ruta del indice|tomo (?:3|iii)\b|volumen (?:3|iii)\b|tabla de (?:tumores|medicamentos)",
            prose,
        )
        and not index_refs
    ):
        raise ExplanationError(
            "Si invocas el índice o sus tablas, cita la fuente del tomo 3 utilizada."
        )
    if (
        index_refs
        and re.search(
            r"(?:indice|ruta|remision|tomo 3)[^.;]{0,100}(?:sinonim|equivalencia clinica)",
            prose,
        )
        and not re.search(r"\bno\b[^.;]{0,50}(?:sinonim|equivalencia)", prose)
    ):
        raise ExplanationError(
            "Una ruta o remisión del índice no demuestra sinonimia ni equivalencia clínica."
        )
    manual_refs = [ref for ref in refs if sources[ref].get("volume") == 2]
    if (
        re.search(r"\b(?:manual|guia|tomo (?:2|ii)|volumen (?:2|ii))\b", prose)
        and not manual_refs
    ):
        raise ExplanationError(
            "Si invocas el manual o una guía, cita el pasaje del tomo 2 utilizado; no basta citar jerarquía tabular."
        )
    anchors = [
        item
        for item in evidence
        if item.get("role") in ("title", "candidate_term") or item["type"] == "INPUT"
    ]
    explicit_pair = any("†" in item["text"] or "*" in item["text"] for item in anchors)
    if not explicit_pair and re.search(
        r"(?:se utiliza|se aplica|se usa|utilizamos)[^.;]{0,100}(?:daga|asterisco)",
        prose,
    ):
        raise ExplanationError(
            "La convención de daga y asterisco no demuestra una manifestación en este paciente. Compara el término SNOMED con el título y los datos recibidos sin aplicar una pareja de códigos."
        )
    if re.search(
        r"\b(?:recodifique|recodificar|sustituya|reemplace|cambie el codigo)\b", prose
    ):
        raise ExplanationError(
            "La explicación no ejecuta una recodificación del caso; conserva el código solicitado."
        )
    if re.search(
        r"\b[0-9]{6,18}\b|\b(?:cie|snomed)-(?:title|exclusions|inclusions|term|hierarchy)",
        prose,
    ):
        raise ExplanationError(
            "La justificación debe usar nombres; los identificadores se muestran en las referencias."
        )
    polarity_prose = re.sub(
        r"\b[a-z][0-9]{2}(?:\.[a-z0-9-]+)?(?:-[a-z]?[0-9]{2}(?:\.[a-z0-9-]+)?)?",
        "",
        prose,
    )
    polarity = re.search(
        r"(?:exclusion(?:es)?|excluye)[^.;]{0,100}\b(?:confirman?|respaldan?|apoyan?|demuestran?)\b",
        polarity_prose,
    )
    if polarity and not re.search(
        r"\bno\s+(?:confirman?|respaldan?|apoyan?|demuestran?)\b", polarity[0]
    ):
        raise ExplanationError(
            "Una exclusión NO confirma una correspondencia. Basa la comparación en el título, el término y el sitio SNOMED. Si no puedes respaldarla, usa undetermined y abstained con diagnóstico."
        )
    if scope_notes(evidence) and answer["assessment"] == "incompatible":
        if ("sitio no especificado" in prose or "c80" in prose) and (
            "tejido" in prose or "histolog" in prose
        ):
            raise ExplanationError(
                "Falta de tejido o histología no demuestra sitio anatómico no especificado."
            )
    if answer["selection"] == "proposed":
        if answer["assessment"] != "compatible" or answer["additional_detail_needed"]:
            raise ExplanationError(
                "Una incompatibilidad, duda o dato faltante impide proponer selección."
            )
        if not any(sources[ref]["type"] == "INPUT" for ref in refs):
            raise ExplanationError(
                "Una selección propuesta debe citar el diagnóstico recibido."
            )
    # Targeted regression guard for the previously observed calyx/calculus confusion.
    source_text = " ".join(item["text"] for item in evidence).casefold()
    generated = answer["justification"].casefold()
    if "cálices" in source_text and not re.search(r"c[áa]lculos?", source_text):
        if re.search(r"c[áa]lculos?", generated):
            raise ExplanationError(
                "La explicación sustituye cálices por cálculos sin respaldo."
            )
    return answer


def readable_justification(text, concept_id, sources, refs):
    """Remove redundant identity annotations; never rewrite clinical assertions."""
    if not isinstance(text, str):
        raise ExplanationError("La justificación debe ser texto.")
    if re.search(
        r"\bcie[- ]?10\s*(?:\(\s*(?:snomed\s*:?\s*)?|:\s*)" + re.escape(concept_id),
        normalize(text),
    ):
        raise ExplanationError("Un SCTID no es un código CIE-10.")
    text = re.sub(r"\s*\(" + re.escape(concept_id) + r"\)", "", text)
    text = re.sub(
        r"\b(SNOMED(?:\s+CT)?)\s*:?\s*" + re.escape(concept_id) + r"\b",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    # Some generations echo the numeric suffix of an evidence ID. These are
    # identity annotations only; leave unknown numbers and clinical prose untouched.
    known_annotations = {
        item["id"].removeprefix("snomed-")
        for item in sources.values()
        if item["type"] == "SNOMED"
        and re.fullmatch(r"snomed-[0-9]{6,18}-[0-9]{6,18}", item["id"])
    }
    for annotation in known_annotations:
        text = re.sub(r"\s*\(" + re.escape(annotation) + r"\)", "", text)
    labels = {
        "title": "título CIE-10",
        "exclusion": "exclusión CIE-10",
        "inclusions": "inclusión CIE-10",
        "notes": "nota CIE-10",
        "hierarchy": "contexto jerárquico CIE-10",
        "candidate_term": "concepto SNOMED",
        "finding_site": "sitio definido en SNOMED",
        "index_entry": "ruta del índice",
        "index_table": "fila y columnas del índice",
        "index_remission": "remisión del índice",
        "index_note": "nota del índice",
        "manual_instruction": "instrucción del tomo 2",
        "manual_guidance": "orientación del tomo 2",
        "manual_convention": "convención del tomo 2",
    }

    def replace(match):
        ref = match[0]
        if ref not in sources or ref not in refs:
            raise ExplanationError(
                "La justificación menciona una evidencia sin citarla."
            )
        source = sources[ref]
        return labels.get(
            source.get("role"),
            "evidencia " + ("CIE-10" if source["type"] == "CIE10" else "SNOMED"),
        )

    return re.sub(r"\b(?:cie|snomed|manual|index)-[a-zA-Z0-9_-]+", replace, text)

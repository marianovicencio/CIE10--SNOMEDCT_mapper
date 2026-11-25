"""Readable comparison of source-bound dimensions, independent of LLM prose.

A literal difference is not a clinical contradiction. Only an existing verified
constraint can mark a conflict. Published parents support directional membership,
never synonymy or a positive mapping decision. No disease-specific code lists.
"""
import re
from .explanation_constraints import normalize
from .reasoning.assertions import extract_assertions
from .explanation_attribution import source_label

POLICY = "source_bound_comparison_dimensions_v1"


DIMENSION_PATTERNS = {
    "stage": r"\b(?:etapa|estadio)\s+([1-9][0-9]?(?:[ab])?|iv|iii|ii|vi|vii|viii|ix|x|i|v)\b",
    "onset": r"\b(?:inicio|comienzo|aparición|aparicion)\s+(?:en\s+la\s+(?:edad|etapa)\s+)?(tempran[oa]|tardí[oa]|tardi[oa]|presenil|senil|juvenil|neonatal)\b",
}
SPECIFICATION = r"\b(?:sin menci[oó]n de [^,;—]+|no especificad[oa]s?|sin especificar|SAI|NCOP)\b"


def heading_text(text):
    # Remove coding references and semantic tags only from the comparison view.
    # The original text stays intact in every citation.
    text = re.sub(r"\([^()]*[A-Z][0-9]{2}[^()]*\)", "", text)
    text = re.sub(r"\((?:trastorno|hallazgo)\)\s*$", "", text, flags=re.I)
    return text.strip().rstrip("†*").strip()


def key(text):
    text = heading_text(text)
    # Normalize de-phrase articles, retaining polarity, specificity and order.
    text = re.sub(r"\bdel(?=\s+[a-záéíóúüñ])", "de", text)
    text = re.sub(r"\bde\s+(?:el|la|los|las)(?=\s+[a-záéíóúüñ])", "de", text)
    return tuple(re.findall(r"[a-z0-9]+", normalize(text)))


def split_heading(text):
    text = heading_text(text)
    # A grammatical association is shown literally, not interpreted as a new
    # causal or clinical assertion. Unknown constructions remain a whole heading.
    match = re.fullmatch(r"(.+?)\s+en\s+(?:la\s+|el\s+)?(enfermedad\s+de\s+.+)", text, re.I)
    if match:
        return match[1].strip(), match[2].strip()
    return text, None


def condition_text(text):
    """Separate only qualifiers that are displayed in their own dimensions."""
    text = heading_text(text)
    ends = [m.start() for pattern in DIMENSION_PATTERNS.values() for m in re.finditer(pattern, text, re.I)]
    ends.extend(m.start() for m in re.finditer(SPECIFICATION, text, re.I))
    for frame in extract_assertions(text, "condition"):
        if not frame.feature: continue
        operators = [start for word, start, _ in frame.lexemes
                     if word in ("con", "sin", "no") and start < frame.span[0]]
        if operators: ends.append(max(operators))
    if not ends: return text
    prefix = text[:min(ends)].strip(" ,;—")
    # The onset marker may have been introduced by 'de inicio/comienzo'.
    prefix = re.sub(r"\s+de$", "", prefix, flags=re.I)
    return prefix.strip(" ,;—") or text


def feature_values(item):
    text = heading_text(item["text"])
    return [{"text": text[frame.span[0]:frame.span[1]], "value": frame.value,
             "key": frame.feature, "source": item["id"], "construction": frame.construction}
            for frame in extract_assertions(text, item["id"])
            if frame.feature]


def marker_values(item, dimension):
    text = heading_text(item["text"])
    return [{"text": m[0], "key": normalize(m[1]), "source": item["id"]}
            for m in re.finditer(DIMENSION_PATTERNS[dimension], text, re.I)]


def source_projection(item):
    return {"id": item["id"], "type": item["type"], "label": source_label(item),
            **{name: item[name] for name in ("role", "text", "provenance", "volume") if name in item}}


def build_comparison(evidence, review, anchor=None):
    title = next((x for x in evidence if x.get("role") == "title" and x["type"] == "CIE10"), None)
    term = next((x for x in evidence if x.get("role") == "candidate_term" and x["type"] == "SNOMED"), None)
    if not title or not term:
        return None
    anchor = anchor or {}
    cid = term.get("concept_id")
    targets = [term] + [x for x in evidence if x.get("role") == "candidate_alias" and x.get("concept_id") == cid]
    parents = [x for x in evidence if x.get("role") == "parent" and x.get("concept_id") == cid]
    rows = []
    base_refs = [title["id"], term["id"]]

    def row(identifier, label, cie_text, candidate_text, status, reading, refs=(), candidate_detail=None):
        item = {"id": identifier, "label": label, "status": status,
                "cie": {"text": cie_text}, "candidate": {"text": candidate_text},
                "reading": reading, "evidence_refs": list(dict.fromkeys(base_refs + list(refs)))}
        if candidate_detail: item["candidate"]["detail"] = candidate_detail
        rows.append(item)
        return item

    main, associated = split_heading(title["text"])
    main = condition_text(main)
    candidate_main, candidate_associated = split_heading(term["text"])
    direct = next((x for x in targets if key(main) == key(condition_text(split_heading(x["text"])[0]))), None)
    parent = next((x for x in parents if key(main) == key(x["text"])), None)
    condition_row = row("condition", "Afección", main, condition_text(candidate_main),
        "same_wording" if direct else "supported_by_hierarchy" if parent else "different_wording",
        "Las denominaciones conservan la misma formulación de la afección principal. Los calificadores se comparan por separado cuando están expresados." if direct else
        "La afección del título figura como concepto superior publicado del candidato. La relación jerárquica aporta respaldo aunque no aparezca en su nombre." if parent else
        "Las denominaciones no coinciden literalmente. Esta diferencia por sí sola no establece una contradicción; queda pendiente comprobar su alcance.",
        [x["id"] for x in (direct, parent) if x],
        "Concepto superior publicado: " + parent["text"] if parent else None)

    # A direct parent of a verified, whole-heading anchor is a directional subtype
    # witness. An anatomy-only or qualifier-stripped anchor cannot establish this.
    if (not associated and anchor.get("status") == "verified_published_condition"
            and key(anchor.get("matched_description", "")) == key(title["text"])):
        anchor_parent = next((p for p in parents if p["id"] == "snomed-parent-" + anchor.get("concept_id", "")), None)
        if anchor_parent and not direct:
            condition_row.update(status="candidate_narrower", reading="La afección verificada para el título es un concepto superior directo del candidato. El candidato representa un subtipo; hay que revisar qué detalle añade.")
            condition_row["evidence_refs"].append(anchor_parent["id"])
            condition_row["candidate"]["detail"] = "Concepto superior publicado: " + anchor_parent["text"]

    if associated:
        exact = next((x for x in targets if key(associated) == key(x["text"]) or (split_heading(x["text"])[1] and key(associated) == key(split_heading(x["text"])[1]))), None)
        parent = next((x for x in parents if key(associated) == key(x["text"])), None)
        row("association", "Enfermedad asociada", associated,
            candidate_associated or heading_text(term["text"]),
            "same_wording" if exact else "candidate_narrower" if parent else "different_wording",
            "La enfermedad nombrada en la asociación CIE-10 también está expresada en la denominación oficial del candidato." if exact else
            "La enfermedad asociada figura como concepto superior del candidato: este representa un subtipo y puede añadir detalle." if parent else
            "No se ha establecido una coincidencia literal para la enfermedad asociada. La relación queda pendiente de comprobar.",
            [x["id"] for x in (exact, parent) if x],
            "Concepto superior publicado: " + parent["text"] if parent else None)

    for dimension, label in [("stage", "Estadio"), ("onset", "Inicio")]:
        left = marker_values(title, dimension)
        right = [value for x in targets for value in marker_values(x, dimension)]
        # Aliases are alternative descriptions of this very concept, not extra
        # diagnoses. Prefer the literal value shared with the CIE heading.
        if not left and not right: continue
        same = next(((a, b) for a in left for b in right if a["key"] == b["key"]), None)
        chosen = [same[1]] if same else list({x["key"]: x for x in right}.values())
        row(dimension, label, " · ".join(x["text"] for x in left) or "No explicitado en el título",
            " · ".join(x["text"] for x in chosen) or "No explicitado en las descripciones",
            "same_wording" if same else "candidate_detail" if not left else "not_explicit" if not right else "different_wording",
            "Las fuentes expresan el mismo valor literal para esta dimensión." if same else
            "El candidato explicita un detalle que el título CIE-10 no aporta. El diagnóstico escrito puede aportar el contexto necesario." if not left else
            "Las descripciones consultadas no expresan este detalle del código; hay que revisar si su alcance lo conserva." if not right else
            "Las fuentes expresan valores distintos. Se muestran para revisar su alcance, sin deducir incompatibilidad solo por las palabras.",
            [x["source"] for x in chosen])

    left_spec = [m[0] for m in re.finditer(SPECIFICATION, heading_text(title["text"]), re.I)]
    right_spec = [m[0] for m in re.finditer(SPECIFICATION, heading_text(term["text"]), re.I)]
    if left_spec or right_spec:
        row("specification", "Grado de especificación", " · ".join(left_spec) or "Sin expresión de este tipo en el título",
            " · ".join(right_spec) or "Sin expresión de este tipo en la denominación", "context",
            "Se conserva la expresión de la fuente sobre su nivel de detalle. Una falta de mención no equivale a negar una afección o complicación.")

    left_features = feature_values(title)
    right_features = feature_values(term)
    if left_features or right_features:
        left_set = {(x["key"], x["value"]) for x in left_features}
        right_set = {(x["key"], x["value"]) for x in right_features}
        same = bool(left_set and left_set == right_set)
        def shown(values):
            return " · ".join(("No " if x["construction"] == "no_qualifier" else "Sin " if x["value"] == "absent" else "Con " if x["value"] == "present" else "Alternativa: ") + x["text"] for x in values)
        row("qualifiers", "Calificadores explícitos", shown(left_features) or "No explicitados en el título",
            shown(right_features) or "No explicitados en la denominación",
            "same_wording" if same else "candidate_detail" if not left_features else "not_explicit" if not right_features else "different_wording",
            "La construcción literal conserva los calificadores y su afirmación o negación." if same else
            "El candidato añade calificadores respecto al título. Deben contrastarse con el diagnóstico aportado." if not left_features else
            "Los calificadores del título no aparecen explícitos en la denominación del candidato; su conservación requiere revisión." if not right_features else
            "Los calificadores se expresan de forma diferente. Las restricciones verificadas, si existen, se muestran por separado.")

    morphology = [x for x in evidence if x.get("role") == "116676008" and x.get("concept_id") == cid]
    if morphology:
        # The official attribute is displayed verbatim. Literal overlap with its
        # label is informative, never an inferred histological identity/conflict.
        texts = [re.sub(r"^morfología asociada\s+", "", x["text"], flags=re.I) for x in morphology]
        words = " ".join(key(title["text"]))
        same = bool(texts) and all((" " + " ".join(key(x)) + " ") in (" " + words + " ") for x in texts)
        row("morphology", "Morfología del candidato", heading_text(title["text"]), " · ".join(texts),
            "same_wording" if same else "context",
            "El nombre de la morfología publicada aparece también en el título CIE-10." if same else
            "Atributo publicado del candidato. Su relación con el título se revisa junto con la afección y los calificadores.",
            [x["id"] for x in morphology])

    # Missing anatomy is not a global verdict. Show this dimension only when an
    # independently verified CIE site makes it relevant to the code's scope.
    expected = anchor.get("sites", [])
    if expected:
        actual = review.get("finding_sites", {}).get("candidate", [])
        if not actual:
            actual = [{"descriptions": [re.sub(r"^sitio del hallazgo\s+", "", x["text"], flags=re.I)]}
                      for x in evidence if x.get("role") == "finding_site"]
        status = review.get("anatomy", {}).get("status", "not_comparable")
        readings = {
            "same_published_site": ("same_wording", "La localización verificada coincide."),
            "candidate_site_narrower_review": ("candidate_narrower", "La relación publicada indica una localización más precisa en el candidato."),
            "candidate_site_broader_review": ("candidate_broader", "La relación publicada indica una localización más amplia en el candidato; revisa si conserva el detalle del código."),
            "multiple_sites_review": ("not_explicit", "Hay varios sitios publicados; una coincidencia parcial no resuelve el alcance completo."),
            "no_hierarchy_link_review": ("different_wording", "Los sitios difieren y no se verificó una relación jerárquica entre ellos. Esto no demuestra por sí mismo que sean incompatibles."),
        }
        state, reading = readings.get(status, ("not_explicit", "No se pudo verificar la relación entre las localizaciones."))
        site_refs = [x["id"] for x in evidence if x.get("role") == "finding_site"]
        row("site", "Localización", " · ".join(t for x in expected for t in x.get("descriptions", [])),
            " · ".join(t for x in actual for t in x.get("descriptions", [])) or "Sin atributo verificado", state, reading, site_refs)

    symbol = title.get("code_symbol", "")
    pairs = re.findall(r"[A-Z][0-9]{2}(?:\.[0-9–.-]+)?[†*]?", title["text"])
    if symbol in ("*", "†") or (pairs and any(c in title["text"] for c in "†*")):
        conventions = [x for x in evidence if x.get("volume") == 2 and x.get("role") == "manual_convention"
                       and re.search(r"sistema.{0,40}(?:daga|asterisco)", normalize(x["text"]))]
        row("coding", "Convención de codificación", ("Código marcado con " + ("asterisco (*)" if symbol == "*" else "daga (†)") + ". " if symbol in ("*", "†") else "") + ("Referencia: " + ", ".join(pairs) if pairs else ""),
            "Representación mediante concepto SNOMED", "context",
            "CIE-10 distingue la enfermedad básica (daga) de su manifestación (asterisco). Esta convención debe considerarse al revisar el alcance del mapeo." if conventions else
            "El título contiene una referencia de codificación. Su interpretación requiere revisar la convención aplicable y la pareja de códigos.",
            [x["id"] for x in conventions])

    constraint = review.get("constraint")
    if constraint:
        refs = constraint.get("evidence_refs", [])
        matched = [x for x in evidence if x["id"] in refs]
        row("restriction", "Restricción verificada", " · ".join(dict.fromkeys(source_label(x) for x in matched if x["type"] == "CIE10")) or "Alcance del código consultado",
            heading_text(term["text"]),
            "conflict" if constraint.get("assessment") == "incompatible" else "not_explicit",
            "El resultado se basa en la restricción citada. Consulta su texto y condiciones en el respaldo documental.", refs)

    source_map = {x["id"]: x for x in evidence}
    refs = list(dict.fromkeys(r for item in rows for r in item["evidence_refs"] if r in source_map))
    if constraint:
        summary = {"status": "conflict" if constraint.get("assessment") == "incompatible" else "review",
                   "title": "Hay una contradicción respaldada" if constraint.get("assessment") == "incompatible" else "Hay una condición pendiente de aclarar",
                   "text": constraint.get("justification", "Revisa la restricción documentada.")}
    elif any(x["type"] == "INPUT" for x in evidence) and review.get("input_scope") in ("negated", "hypothetical", "uncertain", "historical", "other_subject"):
        summary = {"status": "review", "title": "El contexto aportado necesita aclaración",
                   "text": "Revisa si la mención corresponde a una afección afirmada y actual de la persona consultada. Las coincidencias documentales se muestran por separado."}
    elif any(x["status"] in ("candidate_narrower", "candidate_detail") for x in rows):
        summary = {"status": "review", "title": "El candidato añade detalle respecto al código",
                   "text": "Revisa las dimensiones señaladas y si el diagnóstico escrito aporta el detalle adicional."}
    elif any(x["status"] in ("candidate_broader", "not_explicit") for x in rows):
        summary = {"status": "review", "title": "Hay detalles cuyo alcance debe comprobarse",
                   "text": "Las fuentes permiten comparar parte del significado, pero quedan dimensiones sin correspondencia verificada."}
    elif all(x["status"] in ("same_wording", "supported_by_hierarchy", "context") for x in rows):
        summary = {"status": "supported", "title": "Hay respaldo en las denominaciones o la jerarquía",
                   "text": "Las dimensiones mostradas tienen respaldo documental. Puedes revisar las fuentes de cada una."}
    else:
        summary = {"status": "review", "title": "La relación entre los términos requiere revisión",
                   "text": "Se muestran las coincidencias verificables y las diferencias de formulación pendientes de comprobar."}
    entry = next((x for x in evidence if x["type"] == "INPUT"), None)
    if entry and entry["id"] not in refs: refs.append(entry["id"])
    return {"policy": POLICY, "summary": summary, "dimensions": rows,
            "sources": [source_projection(source_map[r]) for r in refs],
            "input": {"text": entry["text"], "scope": review.get("input_scope"), "evidence_ref": entry["id"]} if entry else None,
            "automatic_selection": False, "positive_mapping_approved": False,
            "source_coverage": "literal_headings_published_attributes_and_existing_constraints"}

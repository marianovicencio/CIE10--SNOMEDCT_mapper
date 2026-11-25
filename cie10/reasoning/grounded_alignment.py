"""Compare verified component identities and directional subtype relations.

A narrower present condition contradicts absence of its broader class. The reverse
is not assumed. These constraints can reject/defer, never approve a clinical map.
"""

from cie10.reasoning.assertions import extract_assertions
from cie10.explanations.explanation_constraints import source
from cie10.api.mapping_context import digest


def grounded_constraint(evidence):
    title = source(evidence, "CIE10", "title", "cie-title")
    term = source(evidence, "SNOMED", "candidate_term", "snomed-term")
    entry = next((x for x in evidence if x["type"] == "INPUT"), None)
    if not title or not term:
        return None
    bindings = {}
    relations = {}
    for item in evidence:
        if item.get("role") == "component_alignment" and item.get(
            "concept_id"
        ) == term.get("concept_id"):
            for binding in item.get("component_bindings", []):
                bindings[binding["phrase_sha256"]] = (
                    item["component_id"],
                    item["id"],
                    binding["match_method"],
                )
        if item.get("role") == "component_subsumption" and item.get(
            "concept_id"
        ) == term.get("concept_id"):
            relations[(item["broader_component_id"], item["narrower_component_id"])] = (
                item["id"]
            )

    def identity(a, b):
        if a == b:
            return {"method": "literal", "refs": []}
        left, right = bindings.get(digest(a)), bindings.get(digest(b))
        if left and right and left[0] == right[0]:
            return {
                "method": "same_verified_component",
                "concept_id": left[0],
                "refs": list(dict.fromkeys([left[1], right[1]])),
                "description_matching": [left[2], right[2]],
            }
        return None

    def feature_relation(a, b):
        same = identity(a, b)
        if same:
            return {"kind": "same", **same}
        left, right = bindings.get(digest(a)), bindings.get(digest(b))
        if left and right:
            for broader, narrower in [(left[0], right[0]), (right[0], left[0])]:
                ref = relations.get((broader, narrower))
                if ref:
                    return {
                        "kind": "subsumption",
                        "broader": broader,
                        "narrower": narrower,
                        "left_component": left[0],
                        "right_component": right[0],
                        "refs": list(dict.fromkeys([left[1], right[1], ref])),
                    }
        # A lexical extension is not silently reduced to its first word.
        if a and b and a[0] == b[0] and a != b:
            return {"kind": "unverified_nested", "refs": []}
        return None

    left = extract_assertions(title["text"], title["id"])
    right = extract_assertions(term["text"], term["id"])
    for item in evidence:
        if item.get("role") == "candidate_alias" and item.get("concept_id") == term.get(
            "concept_id"
        ):
            right.extend(extract_assertions(item["text"], item["id"]))
    inputs = extract_assertions(entry["text"], entry["id"], True) if entry else []
    anchors = [title["id"], term["id"]] + ([entry["id"]] if entry else [])

    def alignment(a, b):
        if not a.feature or not b.feature:
            return None
        condition = identity(a.condition, b.condition)
        if not condition:
            return None
        feature = feature_relation(a.feature, b.feature)
        return (condition, feature) if feature else None

    def opposed(a, b, feature):
        if {a.value, b.value} != {"present", "absent"}:
            return False
        if feature["kind"] == "same":
            return True
        if feature["kind"] == "subsumption":
            negative_id = (
                feature["left_component"]
                if a.value == "absent"
                else feature["right_component"]
            )
            positive_id = (
                feature["left_component"]
                if a.value == "present"
                else feature["right_component"]
            )
            return (
                negative_id == feature["broader"] and positive_id == feature["narrower"]
            )
        return False

    def decision(kind, assessment, a, b, witness):
        condition, feature = witness
        refs = list(
            dict.fromkeys(
                anchors
                + [a.source_id, b.source_id]
                + condition["refs"]
                + feature["refs"]
            )
        )
        message = {
            "polarity_conflict": "La terminología verificada alinea la afección y sus calificadores. Una característica afirmada contradice su ausencia explícita, también cuando lo afirmado es un subtipo de lo excluido. Esa contradicción impide proponer la correspondencia.",
            "scope_unconfirmed": "La terminología permite alinear los componentes, pero la entrada los menciona en una hipótesis, con incertidumbre o para otra persona. Esa mención no respalda una propuesta actual para el paciente.",
            "nested_scope_review": "Los calificadores tienen distinto alcance. No puede extenderse la ausencia de un subtipo a toda la categoría, ni reducirse un calificador compuesto a su primera palabra. La correspondencia requiere revisión.",
            "contradictory_input": "La entrada afirma y niega componentes que la terminología permite relacionar como la misma característica o un subtipo. Debe aclararse esa contradicción antes de proponer la correspondencia.",
        }[kind]
        return {
            "rule_id": "grounded_" + kind,
            "assessment": assessment,
            "justification": message,
            "additional_detail_needed": (
                []
                if assessment == "incompatible"
                else [
                    "Precisar el alcance y la afirmación actual de los calificadores."
                ]
            ),
            "evidence_refs": refs,
            "comparison_trace": {
                "policy": "grounded_component_assertions_v1",
                "left": a.trace(),
                "right": b.trace(),
                "condition_alignment": condition,
                "feature_alignment": feature,
                "positive_mapping_approved": False,
            },
        }

    definition_pending = []
    for a in left:
        for b in right:
            w = alignment(a, b)
            if w and opposed(a, b, w[1]):
                return decision("polarity_conflict", "incompatible", a, b, w)
            if (
                w
                and {a.value, b.value} == {"present", "absent"}
                and w[1]["kind"] in ("subsumption", "unverified_nested")
            ):
                definition_pending.append(("nested_scope_review", a, b, w))
    for a in inputs:
        for b in inputs:
            if (
                a.body_span == b.body_span
                or a.subject != b.subject
                or a.subject != "patient"
                or a.modality != b.modality
                or a.modality != "asserted"
            ):
                continue
            w = alignment(a, b)
            if w and opposed(a, b, w[1]):
                return decision("contradictory_input", "undetermined", a, b, w)
    pending = list(definition_pending)
    for a in left + right:
        for b in inputs:
            w = alignment(a, b)
            if not w:
                continue
            if (
                b.subject != "patient"
                or b.modality != "asserted"
                or b.value == "unknown"
            ):
                pending.append(("scope_unconfirmed", a, b, w))
                continue
            if opposed(a, b, w[1]):
                return decision("polarity_conflict", "incompatible", a, b, w)
            if {a.value, b.value} == {"present", "absent"} and w[1]["kind"] in (
                "subsumption",
                "unverified_nested",
            ):
                pending.append(("nested_scope_review", a, b, w))
    if pending:
        kind, a, b, w = pending[0]
        return decision(kind, "undetermined", a, b, w)
    return None

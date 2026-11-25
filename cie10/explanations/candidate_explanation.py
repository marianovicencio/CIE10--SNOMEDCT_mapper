"""Execute an on-demand candidate explanation without persisting input or prose.

This module coordinates documentary restrictions and model generation.
Contract, prompts, validation and documentary policy live in separate modules.
Generated explanations always come from the selected model.
"""

import json
from cie10.explanations.explanation_limits import (
    MAX_CLAIMS,
    MAX_CLAIM_WORDS,
    MAX_CLAIM_CHARACTERS,
    LOCAL_MAX_NEW_TOKENS,
    LOCAL_CONTEXT_TOKENS,
)
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from cie10.explanations.explanation_contract import ExplanationError, comparison_anchors, response_schema
from cie10.explanations.explanation_validation import validate_explanation, readable_justification
from cie10.explanations.explanation_prompt import (
    INSTRUCTIONS,
    model_evidence_view,
    reference_aliases,
    generation_setup,
    gemma_turn,
)
from cie10.reasoning.policy import normalized_anatomy, anatomical_exclusion, effective_constraint
from cie10.explanations.explanation_attribution import validate_claim_attribution, validate_mapping_comparison


def explain_candidate(
    concept_id,
    diagnostic,
    evidence,
    endpoint="http://127.0.0.1:11434",
    timeout=180,
    transport=None,
    prompt_renderer=gemma_turn,
    generation_method="local_model",
    response_profile="expanded",
):
    """Generate and validate in memory, allowing one explicit correction attempt."""
    if not isinstance(concept_id, str) or not re.fullmatch(r"[0-9]{6,18}", concept_id):
        raise ExplanationError("Identificador de candidato inválido.")
    if diagnostic is not None and (
        not isinstance(diagnostic, str) or not diagnostic.strip()
    ):
        raise ExplanationError("El diagnóstico debe ser texto no vacío o None.")
    if not isinstance(evidence, list) or not evidence:
        raise ExplanationError("Falta la evidencia.")
    for item in evidence:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) and item[k].strip()
            for k in ("id", "type", "text")
        ):
            raise ExplanationError("Evidencia inválida.")
        if item["type"] not in ("CIE10", "SNOMED", "INPUT"):
            raise ExplanationError("Tipo de evidencia inválido.")
        if item["type"] == "SNOMED" and item.get("concept_id") != concept_id:
            raise ExplanationError("La evidencia SNOMED corresponde a otro candidato.")
        if item["type"] == "INPUT" and item["text"] != diagnostic:
            raise ExplanationError(
                "La evidencia de entrada no corresponde al diagnóstico."
            )
    if len({item["id"] for item in evidence}) != len(evidence):
        raise ExplanationError("La evidencia tiene identificadores duplicados.")
    excluded_site = anatomical_exclusion(evidence)
    if excluded_site:
        source_map = {item["id"]: item for item in evidence}
        exclusion = source_map[excluded_site]
        anatomy = re.fullmatch(
            r"([a-z ]+) \([a-z][0-9]{2}(?:\.[0-9-]+)?\)",
            normalized_anatomy(exclusion["text"]),
        )[1]
        site = next(
            item
            for item in evidence
            if item["type"] == "SNOMED"
            and item.get("role") == "finding_site"
            and (
                normalized_anatomy(item["text"]) == anatomy
                or normalized_anatomy(item["text"]).endswith(" " + anatomy)
            )
        )
        refs = [excluded_site, site["id"]]
        answer = {
            "concept_id": concept_id,
            "assessment": "incompatible",
            "justification": "El sitio definido en SNOMED es «"
            + site["text"]
            + "». La CIE-10 excluye «"
            + exclusion["text"]
            + "» del código consultado. Esta localización impide proponer la correspondencia.",
            "evidence_refs": refs,
            "quotes": [
                {"evidence_id": ref, "text": source_map[ref]["text"]} for ref in refs
            ],
            "additional_detail_needed": [],
            "selection": "abstained" if diagnostic else "not_requested",
        }
        answer = validate_explanation(answer, concept_id, diagnostic, evidence)
        return {
            "status": "explanation_available",
            "analysis": answer,
            "attempts": 0,
            "generation_method": "explicit_local_anatomical_exclusion",
            "validation_scope": "structure_references_and_consistency",
            "clinical_validation": "not_performed",
        }
    constraint = effective_constraint(evidence)
    if constraint:
        source_map = {item["id"]: item for item in evidence}
        refs = constraint["evidence_refs"]
        answer = {
            key: constraint[key]
            for key in ("assessment", "justification", "additional_detail_needed")
        }
        answer.update(
            concept_id=concept_id,
            selection="abstained" if diagnostic else "not_requested",
            evidence_refs=refs,
            quotes=[
                {"evidence_id": ref, "text": source_map[ref]["text"]} for ref in refs
            ],
        )
        answer = validate_explanation(answer, concept_id, diagnostic, evidence)
        return {
            "status": "explanation_available",
            "analysis": answer,
            "attempts": 0,
            "generation_method": (
                "manual_documentary_constraint"
                if constraint["rule_id"].startswith("manual_")
                else (
                    "index_documentary_constraint"
                    if constraint["rule_id"].startswith("index_")
                    else "documentary_constraint"
                )
            ),
            "constraint_id": constraint["rule_id"],
            **(
                {"comparison_trace": constraint["comparison_trace"]}
                if "comparison_trace" in constraint
                else {}
            ),
            "validation_scope": "structure_references_and_explicit_documentary_constraints",
            "clinical_validation": "not_performed",
        }
    schema, base_prompt = generation_setup(concept_id, diagnostic, evidence, profile=response_profile)
    attempts = []
    previous = None
    max_attempts = 3 if response_profile == "local" else 2
    recovery_selection = None
    for attempt in range(max_attempts):
        normalizations = []
        prompt = base_prompt
        attempt_evidence = evidence
        if response_profile == "local" and attempt == 2:
            from cie10.explanations.explanation_recovery import recovery_evidence
            attempt_evidence, recovery_selection = recovery_evidence(evidence, diagnostic)
            schema, prompt = generation_setup(concept_id, diagnostic, attempt_evidence, profile="local")
        if attempts:
            prompt += (
                "\nCorrige esta validación de tu intento anterior: " + attempts[-1]
            )
            if attempt < 2:
                prompt += "\nINTENTO ANTERIOR (datos para corregir)\n" + previous
            else:
                prompt += "\nÚLTIMO INTENTO: genera desde cero una comparación breve de 40–70 palabras. Limítate a lo respaldado por el título, el término y, si es necesario, una fuente concreta de contexto. No repitas el intento anterior ni inventes una respuesta. Compara únicamente los términos y la jerarquía o atributos SNOMED visibles. No evalúes reglas de los libros ni convenciones de símbolos: no están en esta comparación acotada. Cita las fuentes utilizadas."
            prompt += "\nDevuelve el objeto completo corregido, respetando el esquema y las evidencias originales."
        body = {
            "prompt": prompt_renderer(prompt, bool(diagnostic)),
            "temperature": 0,
            "n_predict": LOCAL_MAX_NEW_TOKENS,
            "stream": False,
            "json_schema": schema,
            "cache_prompt": False,
            "stop": ["<end_of_turn>"],
        }
        if transport:
            result = transport(body)
        else:
            request = Request(
                endpoint.rstrip("/") + "/completion",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                token_request = Request(
                    endpoint.rstrip("/") + "/tokenize",
                    data=json.dumps(
                        {
                            "content": body["prompt"],
                            "add_special": False,
                            "parse_special": True,
                        }
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(token_request, timeout=15) as response:
                    tokens = json.load(response)["tokens"]
                if len(tokens) + body["n_predict"] > LOCAL_CONTEXT_TOKENS:
                    raise ExplanationError(
                        "La evidencia supera la ventana del modelo. Se requiere una selección documental respaldada."
                    )
                with urlopen(request, timeout=timeout) as response:
                    result = json.load(response)
            except ExplanationError:
                raise
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
                raise ExplanationError(
                    "El modelo local no pudo completar la explicación."
                ) from error
        previous = str(result.get("content", ""))
        try:
            if result.get("truncated") or result.get("stop_type") == "limit":
                raise ExplanationError("La generación quedó truncada.")
            raw = result.get("content", "").strip()
            previous = raw
            # Accept only an optional enclosing JSON fence, never trailing commentary.
            if raw.startswith(chr(96) * 3 + "json\n") and raw.endswith(chr(96) * 3):
                raw = raw[8:-3].strip()
            decoded = json.loads(raw)
            if not isinstance(decoded, dict) or set(decoded) != set(schema["required"]):
                raise ExplanationError(
                    "La salida no corresponde al esquema solicitado."
                )
            source_map = {item["id"]: item for item in evidence}
            reverse_aliases = {
                alias: ref for ref, alias in reference_aliases(attempt_evidence).items()
            }
            claims = decoded["claims"]
            if not isinstance(claims, list) or not 1 <= len(claims) <= schema["properties"]["claims"]["maxItems"]:
                raise ExplanationError(
                    f"Se requieren entre 1 y {MAX_CLAIMS} párrafos con sus propias fuentes."
                )
            attributed = []
            seen_claims = set()
            refs = []
            for claim in claims:
                if not isinstance(claim, dict) or set(claim) != {
                    "text",
                    "evidence_refs",
                }:
                    raise ExplanationError(
                        "Una afirmación tiene una estructura incorrecta."
                    )
                own_refs = claim["evidence_refs"]
                if isinstance(own_refs, list):
                    own_refs = [
                        reverse_aliases.get(ref, ref) if isinstance(ref, str) else ref
                        for ref in own_refs
                    ]
                # Duplicate known citations do not change the model's prose or
                # attribution. Unknown IDs remain invalid; never add guessed refs.
                if (response_profile == "local" and isinstance(own_refs, list)
                        and all(isinstance(ref, str) and ref in source_map for ref in own_refs)
                        and len(set(own_refs)) != len(own_refs)):
                    own_refs = list(dict.fromkeys(own_refs))
                    normalizations.append("duplicate_known_citations_removed")
                if (
                    not isinstance(own_refs, list)
                    or not 1 <= len(own_refs) <= 6
                    or any(
                        not isinstance(ref, str) or ref not in source_map
                        for ref in own_refs
                    )
                    or len(set(own_refs)) != len(own_refs)
                ):
                    raise ExplanationError(
                        "Una afirmación cita fuentes desconocidas o repetidas."
                    )
                if not set(comparison_anchors(evidence, diagnostic)) <= set(own_refs):
                    raise ExplanationError(
                        "Cada comparación debe citar sus fuentes de base: CIE-10, SNOMED y la entrada si existe."
                    )
                text = claim["text"]
                if not isinstance(text, str) or not text.strip():
                    raise ExplanationError("Cada párrafo debe contener texto.")
                character_limit = schema["properties"]["claims"]["items"]["properties"]["text"]["maxLength"]
                if len(text) > character_limit:
                    raise ExplanationError(f"Cada párrafo admite hasta {character_limit} caracteres; distribuye las razones sin repetir contenido.")
                if len(text.split()) > MAX_CLAIM_WORDS:
                    raise ExplanationError(f"Cada párrafo admite hasta {MAX_CLAIM_WORDS} palabras.")
                canonical_claim = " ".join(text.casefold().split())
                if canonical_claim in seen_claims:
                    raise ExplanationError("Los párrafos deben aportar información distinta, sin repetir el mismo texto.")
                seen_claims.add(canonical_claim)
                for alias, ref in reverse_aliases.items():
                    if re.search(r"\b" + re.escape(alias) + r"\b", text):
                        if ref not in own_refs:
                            if response_profile == "local" and len(own_refs) < 6:
                                # The model explicitly named this known source;
                                # resolve that citation, never guess from similarity.
                                own_refs.append(ref)
                                normalizations.append("explicit_source_mention_resolved")
                            else:
                                raise ExplanationError(
                                    "La afirmación menciona una fuente sin citarla."
                                )
                        text = re.sub(r"\b" + re.escape(alias) + r"\b", ref, text)
                if response_profile == "local":
                    field_labels = {"candidate_term": "término del candidato SNOMED",
                                    "candidate_alias": "descripción alternativa SNOMED",
                                    "finding_site": "sitio del hallazgo SNOMED",
                                    "associated_morphology": "morfología asociada SNOMED"}
                    for field, label in field_labels.items():
                        if re.search(r"\b" + field + r"\b", text):
                            # Quotes around a field name are formatting, not a
                            # verbatim medical quotation. Remove only that exact
                            # wrapper before translating the known field label.
                            text = re.sub(r"[«“‘'\"]\s*" + field + r"\s*[»”’'\"]", label, text)
                            text = re.sub(r"\b" + field + r"\b", label, text)
                            normalizations.append("technical_field_label_made_readable")
                text = readable_justification(text, concept_id, source_map, own_refs)
                validate_claim_attribution(text, own_refs, source_map)
                attributed.append({"text": text, "evidence_refs": own_refs})
                refs.extend(ref for ref in own_refs if ref not in refs)
            if not any(
                {"CIE10", "SNOMED"}
                <= {source_map[ref]["type"] for ref in claim["evidence_refs"]}
                for claim in attributed
            ):
                raise ExplanationError(
                    "Al menos una afirmación debe comparar fuentes CIE-10 y SNOMED juntas."
                )
            decoded = {
                key: decoded[key]
                for key in ("concept_id", "assessment", "additional_detail_needed")
            }
            decoded["selection"] = (
                "not_requested"
                if not diagnostic
                else (
                    "proposed"
                    if decoded["assessment"] == "compatible"
                    and not decoded["additional_detail_needed"]
                    and recovery_selection is None
                    else "abstained"
                )
            )
            decoded["justification"] = " ".join(claim["text"] for claim in attributed)
            decoded["evidence_refs"] = refs
            decoded["quotes"] = [
                {"evidence_id": ref, "text": source_map[ref]["text"]} for ref in refs
            ]
            validate_mapping_comparison(decoded["justification"])
            answer = validate_explanation(decoded, concept_id, diagnostic, evidence)
            return {
                "status": "explanation_available",
                "analysis": answer,
                "attempts": attempt + 1,
                "generation_method": generation_method,
                "attributed_claims": attributed,
                "citation_policy": "required_comparison_anchors_plus_optional_context",
                "recovered_after_validation": attempt > 0,
                "recovery_context_selection": recovery_selection,
                "normalizations": list(dict.fromkeys(normalizations)),
                "validation_scope": "structure_references_and_claim_attribution",
                "clinical_validation": "not_performed",
            }
        except (ValueError, TypeError, KeyError) as error:
            attempts.append(str(error))
    return {
        "status": "explanation_rejected",
        "analysis": None,
        "attempts": max_attempts,
        "errors": attempts,
        "recovery_context_selection": recovery_selection,
        "clinical_validation": "not_performed",
    }

"""Prepare a version-bound, tabular candidate explanation without persisting content."""

import json
import os
from pathlib import Path
import subprocess
import socket
import time
from contextlib import contextmanager
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

from .candidate_explanation import (
    ExplanationError,
    anatomical_exclusion,
    explain_candidate,
    effective_constraint,
)
from .reasoning.comparisons import literal_label_analysis
from .snowstorm_verification import SnowstormFHIR
from .manual_reasoning import build_manual_context
from .index_reasoning import build_index_context
from .mapping_context import ContextError
from .explanation_attribution import source_label
from .explanation_budget import fit_model_evidence
from .explanation_focus import focus_evidence
from .openai_explanation import load_config, OpenAITransport, OpenAIError

ROOT = Path(__file__).resolve().parents[1]
VERSION = "http://snomed.info/sct/449081005/version/20261110"
MODEL_ENDPOINT = "http://127.0.0.1:11435"


def get_json(url, timeout=15):
    # Retry only transient read failures; every caller still checks its snapshot.
    for attempt in range(2):
        try:
            with urlopen(url, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            if attempt or error.code not in (502, 503, 504):
                raise
        except (URLError, TimeoutError, ConnectionResetError):
            if attempt:
                raise
        time.sleep(0.1)


def prepare_evidence(request):
    code = request["code"]
    doc = get_json(
        "http://127.0.0.1:8000/v1/codes/" + code + "?scope=morbidity&limit=1"
    )
    if doc.get("source_snapshot_sha256") != request["source_snapshot_sha256"]:
        raise ExplanationError("La versión documental cambió. Repite la búsqueda.")
    if request["target_version"] != VERSION:
        raise ExplanationError("La edición SNOMED solicitada no está configurada.")
    concept_id = request["concept_id"]
    verifier = SnowstormFHIR("http://127.0.0.1:8081/fhir", VERSION)
    verifier.require_version()
    verifier.lookup_active(concept_id)
    lookup = verifier.get(
        "/CodeSystem/$lookup?"
        + urlencode(
            {
                "system": "http://snomed.info/sct",
                "version": VERSION,
                "code": concept_id,
                "displayLanguage": "es",
                "property": "*",
            }
        )
    )
    params = lookup["parameter"]
    if [item.get("valueString") for item in params if item["name"] == "version"] != [
        VERSION
    ]:
        raise ExplanationError("Snowstorm devolvió otra edición.")
    title = " — ".join(
        [
            doc["title"],
            *[item["text"] for item in doc["classification"].get("subdivisions", [])],
        ]
    )
    evidence = [
        {
            "id": "cie-title",
            "type": "CIE10",
            "text": title,
            "role": "title",
            "code": code,
            "code_symbol": doc["classification"].get("symbol", ""),
            "provenance": doc["classification"].get("reference", {}).get("source", ""),
        }
    ]
    for index, parent in enumerate(doc["classification"].get("hierarchy", [])):
        evidence.append(
            {
                "id": "cie-hierarchy-" + str(index),
                "type": "CIE10",
                "text": parent["title"],
                "role": "hierarchy",
                "origin": parent.get("code"),
                "provenance": "Jerarquía de "
                + code
                + " · "
                + evidence[0]["provenance"],
            }
        )
    for kind, items in doc["tabular"].items():
        for index, item in enumerate(items):
            parts = item.get("numbered_notes") or [None]
            for note in parts:
                text = "\n".join(
                    value
                    for value in [
                        item.get("title", ""),
                        item.get("text", "") if note else "",
                        note["text"] if note else item.get("text", ""),
                    ]
                    if value
                )
                if not text:
                    continue
                refs = item.get("references", []) or [item.get("reference", {})]
                suffix = (
                    "-note-" + str(note.get("number", parts.index(note)))
                    if note
                    else ""
                )
                evidence.append(
                    {
                        "id": "cie-" + kind + "-" + str(index) + suffix,
                        "type": "CIE10",
                        "text": text,
                        "role": "exclusion" if kind == "exclusions" else kind,
                        "kind": item.get("kind"),
                        "inherited": item.get("inherited"),
                        "origin": item.get("origin"),
                        "provenance": " · ".join(
                            dict.fromkeys(
                                ref.get("source", "")
                                for ref in refs
                                if ref.get("source")
                            )
                        ),
                    }
                )
    for item in params:
        if item["name"] == "display":
            evidence.append(
                {
                    "id": "snomed-term",
                    "type": "SNOMED",
                    "concept_id": concept_id,
                    "text": item["valueString"],
                    "role": "candidate_term",
                    "provenance": VERSION,
                }
            )
        if item["name"] != "property":
            continue
        parts = item.get("part", [])
        key = next(
            (part.get("valueCode") for part in parts if part["name"] == "code"), None
        )
        if key in ("363698007", "116676008", "parent"):
            text = " ".join(
                part.get("valueString", "")
                for part in parts
                if part["name"] in ("code-display", "description")
            )
            value = next(
                (part.get("valueCode") for part in parts if part["name"] == "value"), ""
            )
            if text:
                item = {
                    "id": "snomed-" + key + "-" + value,
                    "type": "SNOMED",
                    "concept_id": concept_id,
                    "text": text,
                    "role": "finding_site" if key == "363698007" else key,
                    "provenance": VERSION,
                }
                previous = next((x for x in evidence if x["id"] == item["id"]), None)
                if previous is None:
                    evidence.append(item)
                elif {
                    k: v for k, v in previous.items() if k != "source_occurrences"
                } == item:
                    # Repeated identical properties share a citation, retaining
                    # multiplicity. This does not infer role-group equivalence.
                    previous["source_occurrences"] = (
                        previous.get("source_occurrences", 1) + 1
                    )
                else:
                    raise ExplanationError(
                        "Un atributo SNOMED repetido tiene contenido conflictivo."
                    )
    diagnostic = request.get("diagnostic_text") or None
    # All Spanish descriptions belong to the version-verified concept. Structural
    # comparison can use an explicit alias without inventing a medical synonym.
    seen_aliases = {
        item["text"] for item in evidence if item.get("role") == "candidate_term"
    }
    for item in params:
        if item.get("name") != "designation":
            continue
        parts = item.get("part", [])
        language = next(
            (p.get("valueCode") for p in parts if p["name"] == "language"), None
        )
        alias = next(
            (p.get("valueString") for p in parts if p["name"] == "value"), None
        )
        if language == "es" and alias and alias not in seen_aliases:
            seen_aliases.add(alias)
            evidence.append(
                {
                    "id": "snomed-alias-" + str(len(evidence)),
                    "type": "SNOMED",
                    "concept_id": concept_id,
                    "role": "candidate_alias",
                    "text": alias,
                    "provenance": VERSION,
                }
            )
    if diagnostic:
        evidence.append(
            {
                "id": "input-diagnostic",
                "type": "INPUT",
                "text": diagnostic,
                "provenance": "Diagnóstico aportado en la consulta",
            }
        )
    return evidence


def check_model_port(port=11435):
    """Permit reuse after shutdown while rejecting a live listener."""
    try:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    except OSError as error:
        raise ExplanationError(
            "El puerto del modelo está ocupado. Intenta nuevamente."
        ) from error


@contextmanager
def model_server():
    binary = ROOT / "infra/llm/runtime/llama-b11430-cuda/llama-b11430/llama-server"
    if not binary.is_file():
        raise ExplanationError("El ejecutor local GPU no está instalado.")
    libraries = list(
        (ROOT / "infra/retrieval/.venv/lib").glob("python*/site-packages/nvidia/*/lib")
    )
    env = dict(
        os.environ,
        LD_LIBRARY_PATH=":".join(str(path) for path in [binary.parent, *libraries]),
    )
    command = [
        str(binary),
        "--model",
        str(ROOT / "infra/llm/model-data/gemma3-4b.gguf"),
        "--alias",
        "gemma3-4b",
        "--host",
        "127.0.0.1",
        "--port",
        "11435",
        "--ctx-size",
        "8192",
        "--parallel",
        "1",
        "--gpu-layers",
        "all",
        "--fit",
        "off",
        "--no-context-shift",
        "--jinja",
        "--cache-ram",
        "0",
        "--log-disable",
        "--batch-size",
        "256",
        "--ubatch-size",
        "128",
    ]
    check_model_port()
    process = subprocess.Popen(
        command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise ExplanationError(
                    "No se pudo cargar Gemma en la GPU. Intenta de nuevo cuando haya memoria disponible."
                )
            try:
                health = get_json(MODEL_ENDPOINT + "/health", timeout=1)
                if health.get("status") == "ok":
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise ExplanationError("El modelo no terminó de cargar a tiempo.")
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def run_explanation(request):
    started = time.monotonic()
    provider = request.get("provider", "local")
    if provider not in ("local", "openai"):
        raise ExplanationError("Proveedor de explicación no válido.")
    if provider == "openai" and request.get("external_consent") is not True:
        raise ExplanationError(
            "Confirma el envío del contexto y diagnóstico opcional a OpenAI."
        )
    try:
        evidence = prepare_evidence(request)
    except (ContextError, OSError, ValueError) as error:
        raise ExplanationError(
            "No se pudo preparar evidencia tabular/SNOMED (fase tabular_snomed)."
        ) from error
    diagnostic = request.get("diagnostic_text") or None
    try:
        manual, coverage = build_manual_context(
            request,
            evidence,
            transport=lambda path: get_json("http://127.0.0.1:8000" + path),
        )
    except (ContextError, OSError, ValueError) as error:
        raise ExplanationError(
            "No se pudo preparar el contexto del tomo 2 (fase manual)."
        ) from error
    try:
        index, index_coverage = build_index_context(
            request,
            evidence,
            transport=lambda path: get_json("http://127.0.0.1:8000" + path),
        )
    except (ContextError, OSError, ValueError) as error:
        raise ExplanationError(
            "No se pudo preparar el contexto del tomo 3 (fase index)."
        ) from error
    if not manual:
        raise ExplanationError(
            "No se recuperó un pasaje completo utilizable del tomo 2 para esta consulta."
        )
    evidence.extend(manual)
    evidence.extend(index)
    from .terminology_alignment import configured_components

    prior_constraint = effective_constraint(evidence)
    if prior_constraint and not prior_constraint["rule_id"].startswith(
        ("safety_", "grounded_")
    ):
        component_alignment = {"status": "not_needed_existing_constraint"}
    else:
        evidence, component_alignment = configured_components(ROOT, request, evidence)
    # A label match is a summary, not a substitute for requested model prose.
    automatic = literal_label_analysis(request["concept_id"], None, evidence)
    summary = (
        {
            "assessment": "compatible",
            "text": automatic["justification"],
            "evidence_refs": automatic["evidence_refs"],
        }
        if automatic
        else None
    )
    model_attempted = not (
        anatomical_exclusion(evidence) or effective_constraint(evidence)
    )
    if not model_attempted:
        summary = None  # An explicit restriction outranks a positive label match.
    if not model_attempted:
        # Preserve restrictions, but never present a rule template as LLM prose.
        check = explain_candidate(
            request["concept_id"], diagnostic, evidence
        )
        result = {
            "status": "explanation_unavailable",
            "analysis": None,
            "message": "La comparación automática detectó una restricción. Consulta la pestaña Comparación.",
            "documentary_constraint": check["analysis"],
            "generation_method": "blocked_by_documentary_constraint",
            "attempts": 0,
        }
    elif provider == "openai":
        evidence, selection = focus_evidence(evidence)
        try:
            key, model = load_config()
            remote = OpenAITransport(key, model)
            result = explain_candidate(
                request["concept_id"],
                diagnostic,
                evidence,
                transport=remote,
                prompt_renderer=lambda prompt, _: prompt,
                generation_method="openai_model",
            )
        except OpenAIError as error:
            raise ExplanationError(str(error)) from None
        result["model"] = model
        result["provider"] = "openai"
        result["token_usage"] = remote.usage
        result["model_context_selection"] = selection | {
            "coverage": "selected_whole_items_not_all_retrieved_context",
            "truncated_text": False,
        }
    else:
        with model_server():
            evidence, packing = fit_model_evidence(
                request["concept_id"], diagnostic, evidence, MODEL_ENDPOINT
            )
            result = explain_candidate(
                request["concept_id"],
                diagnostic,
                evidence,
                endpoint=MODEL_ENDPOINT,
                timeout=60,
                response_profile="local",
            )
        result["provider"] = "local"
        result["model"] = "gemma3-4b"
        result["model_context_selection"] = packing
    if result.get("status") == "explanation_rejected":
        result["message"] = (
            "El modelo generó una respuesta que no superó la validación. Puedes reintentar o cambiar de modelo."
        )
        result["generation_method"] = (
            "openai_model" if provider == "openai" else "local_model"
        )
    refs = (
        result.get("analysis", {}).get("evidence_refs", [])
        if result.get("analysis")
        else []
    )
    result["evidence"] = [
        {
            "id": item["id"],
            "type": item["type"],
            "source": item.get("provenance", ""),
            "label": source_label(item),
            "role": item.get("role"),
            "volume": item.get("volume"),
        }
        | ({"reading_text": item["reading_text"]} if item.get("volume") == 3 else {})
        for item in evidence
        if item["id"] in refs
    ]
    if model_attempted and not result.get("analysis"):
        recovery = result.get("recovery_context_selection")
        provided_ids = set(recovery["included_evidence_ids"]) if recovery else {item["id"] for item in evidence}
        result["available_evidence"] = [
            {"id": item["id"], "label": source_label(item),
             "text": item.get("reading_text", item["text"]),
             "source": item.get("provenance", "")}
            for item in evidence if item["id"] in provided_ids
        ]
    result["automatic_comparison"] = summary
    result["component_alignment"] = component_alignment
    result["scope"] = "tabular_manual_index_and_snomed"
    result["scope_note"] = (
        "Este análisis consulta los tres tomos y utiliza contexto seleccionado para morbilidad junto con SNOMED CT. Las reglas conservan sus condiciones; las rutas, tablas y remisiones del índice no implican sinonimia ni recodifican automáticamente el caso."
    )
    result["manual_context"] = {
        **coverage,
        "passed_to_model": model_attempted,
        "items": [
            {
                key: item[key]
                for key in (
                    "id",
                    "role",
                    "section",
                    "title",
                    "scope",
                    "requires_case_context",
                    "contains_worked_examples",
                    "text",
                    "provenance",
                    "record_ids",
                )
            }
            | {
                "cited": item["id"] in refs,
                "passed_to_model": model_attempted
                and any(x["id"] == item["id"] for x in evidence),
            }
            for item in manual
        ],
    }
    result["index_context"] = {
        **index_coverage,
        "passed_to_model": model_attempted,
        "items": [
            {
                key: item[key]
                for key in (
                    "id",
                    "role",
                    "kind",
                    "route",
                    "text",
                    "provenance",
                    "record_ids",
                    "matched_columns",
                    "usable_as_synonym",
                    "navigation",
                    "requires_documentary_review",
                )
            }
            | {
                "text": item["reading_text"],
                "cited": item["id"] in refs,
                "passed_to_model": model_attempted
                and any(x["id"] == item["id"] for x in evidence),
            }
            for item in index
        ],
    }
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    result["source_snapshot_sha256"] = request["source_snapshot_sha256"]
    result["target_version"] = VERSION
    return result

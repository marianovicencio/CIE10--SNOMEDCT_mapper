"""Source-bound CIE-10 contrast of retrieved SNOMED CT candidates.

Only independently verified published descriptions may anchor CIE anatomy.
No embedding result becomes an anchor or an equivalence. No-hierarchy-link is
review evidence, never a proof of anatomical disjointness.
"""

from copy import deepcopy
import json
import re
from pathlib import Path

from .mapping_context import CODE, ContextError, MappingContextClient
from .explanation_service import get_json, prepare_evidence
from .manual_reasoning import build_manual_context
from .index_reasoning import build_index_context
from .reasoning.policy import effective_constraint, anatomical_exclusion
from .reasoning.assertions import extract_assertions
from .terminology_alignment import enrich_components, ComponentResolver
from .retrieval_core import normalize
from .snowstorm_verification import published_attributes
from .candidate_comparison import build_comparison

POLICY = "verified_cie_anchor_anatomy_and_documentary_constraints_v1"
SITE = "363698007"


def sites(attributes):
    values = {}
    for prop in attributes:
        parts = prop.get("part", [])
        codes = [p.get("valueCode") for p in parts if p.get("name") == "code"]
        if codes != [SITE]:
            continue
        ids = [p.get("valueCode") for p in parts if p.get("name") == "value"]
        labels = [p.get("valueString") for p in parts if p.get("name") == "description"]
        if len(ids) != 1 or not isinstance(ids[0], str) or not ids[0].isdigit():
            raise ContextError("Atributo anatómico no verificable.")
        values[ids[0]] = {"concept_id": ids[0], "descriptions": labels}
    return list(values.values())


class BodySiteRelations:
    """Dated, directional relations within Body structure, with bounded requests.

    Clinical-component relations deliberately reject anatomy. Keep this separate
    so widening anatomy support cannot alter existing clinical-component rules.
    """

    def __init__(self, resolver, budget=32):
        self.resolver = resolver
        self.budget = budget
        self.calls = 0
        self.bodies = {}
        self.relations = {}

    def body_concept(self, cid):
        if cid in self.bodies:
            return self.bodies[cid]
        if self.calls >= self.budget:
            return None
        self.calls += 1
        value = self.resolver._concept(cid)
        scope = self.resolver._subsumes_request("123037004", cid)
        value = (
            {**value, "body_structure_verification": scope}
            if scope["outcome"] in ("subsumes", "equivalent")
            else None
        )
        self.bodies[cid] = value
        return value

    def relation(self, a, b):
        key = (a, b)  # Direction is meaningful; never cache sorted identifiers.
        if key in self.relations:
            return self.relations[key]
        if not self.body_concept(a) or not self.body_concept(b):
            return None
        if self.calls >= self.budget:
            return None
        self.calls += 1
        value = self.resolver._subsumes_request(a, b)
        self.relations[key] = value
        return value


def compare_sites(expected, actual, resolver):
    if not expected or not actual:
        return {
            "status": "not_comparable",
            "comparisons": [],
            "proves_disjointness": False,
        }
    comparisons = []
    for left in expected:
        for right in actual:
            a, b = left["concept_id"], right["concept_id"]
            relation = (
                {"outcome": "same_concept"} if a == b else resolver.relation(a, b)
            )
            outcome = relation.get("outcome") if relation else "budget_unresolved"
            comparisons.append(
                {
                    "cie_site": left,
                    "candidate_site": right,
                    "relation": relation,
                    "outcome": outcome,
                }
            )
    outcomes = {x["outcome"] for x in comparisons}
    # Multiple sites and partial overlaps do not establish a whole-concept match.
    if len(expected) > 1 or len(actual) > 1:
        status = "multiple_sites_review"
    elif outcomes <= {"same_concept", "equivalent"}:
        status = "same_published_site"
    elif outcomes == {"subsumes"}:
        status = "candidate_site_narrower_review"
    elif outcomes == {"subsumed-by"}:
        status = "candidate_site_broader_review"
    elif outcomes == {"not-subsumed"}:
        status = "no_hierarchy_link_review"
    else:
        status = "relation_unresolved"
    return {"status": status, "comparisons": comparisons, "proves_disjointness": False}


class CIEContextReviewer:
    def __init__(self, root, code, diagnostic, resolver):
        if not isinstance(code, str) or not CODE.fullmatch(code):
            raise ContextError("Se requiere un código CIE-10 individual canónico.")
        self.root, self.code, self.diagnostic, self.resolver = (
            Path(root),
            code,
            diagnostic,
            resolver,
        )
        self.cache = {}
        self.anatomical_resolver = BodySiteRelations(resolver)
        self.doc = self.fetch("/v1/codes/" + code + "?scope=morbidity&limit=1")
        config = json.loads(
            (self.root / "infra/retrieval/active-component-alignment.json").read_text()
        )
        self.snapshot = self.doc.get("source_snapshot_sha256")
        if not self.snapshot or self.snapshot != config.get("source_snapshot_sha256"):
            raise ContextError("El contexto CIE-10 no coincide con el catálogo fijado.")
        if config.get("version") != resolver.version:
            raise ContextError("Otra edición SNOMED en el contraste contextual.")
        self.title = " — ".join(
            [
                self.doc["title"],
                *[
                    x["text"]
                    for x in self.doc["classification"].get("subdivisions", [])
                ],
            ]
        )
        self.anchor = self.resolve_anchor()
        self.client = MappingContextClient(transport=self.fetch)
        self.audit = self.client.fetch_evidence(code, "morbidity")
        if self.audit["source_snapshot_sha256"] != self.snapshot:
            raise ContextError("El catálogo cambió al recuperar el contexto.")

    def fetch(self, path):
        if path not in self.cache:
            self.cache[path] = get_json("http://127.0.0.1:8000" + path)
        return deepcopy(self.cache[path])

    def fetch_evidence(self, code, scope):
        # Shared complete immutable audit; builders can safely augment a copy.
        if code != self.code or scope != "morbidity":
            raise ContextError("Otro alcance contextual.")
        return deepcopy(self.audit)

    @property
    def transport(self):
        return self.fetch

    def resolve_anchor(self):
        frames = extract_assertions(self.title, "cie-title")
        conditions = list(dict.fromkeys(f.condition for f in frames if f.condition))
        if len(conditions) != 1:
            return {
                "status": "unresolved",
                "reason": "not_one_explicit_condition",
                "sites": [],
            }
        # A broad FTS pool must not hide an exact short published description.
        # Bound the larger pool locally, without changing the clinical resolver.
        bounded = ComponentResolver(
            self.resolver.index,
            version=self.resolver.version,
            verifier=self.resolver.verifier,
            row_budget=1024,
            term_budget=1,
        )
        try:
            value = bounded.resolve(conditions[0])
        finally:
            bounded.close()
        if value:
            return {
                "status": "verified_published_condition",
                "concept_id": value["concept_id"],
                "matched_description": value["matched_label"],
                "match_method": value["match_method"],
                "lookup_path": value["request_path"],
                "lookup_sha256": value["response_sha256"],
                "sites": sites(published_attributes(value, self.resolver)),
                "mapping_equivalence_asserted": False,
            }
        # An explicitly named anatomical complement can be verified independently
        # even when the full disease heading has no published SNOMED synonym.
        frame = frames[0]
        lexemes = list(frame.lexemes)
        end = next(
            (start for word, start, _ in lexemes if word in ("con", "sin")),
            len(self.title),
        )
        body = self.title[:end]
        match = re.search(
            r"\b(?:del|de la|de los|de las)\s+([^,;—]+)$", body, re.IGNORECASE
        )
        if match:
            phrase = match[1].strip()
            rows = self.resolver.db.execute(
                "SELECT concept_id,term FROM aliases WHERE normalized=?",
                (normalize(phrase),),
            ).fetchmany(17)
            if len(rows) <= 16:
                verified = {}
                for cid, label in rows:
                    concept = self.anatomical_resolver.body_concept(cid)
                    if concept and label in concept["labels"]:
                        verified[cid] = (concept, label)
                if len(verified) == 1:
                    cid, (concept, label) = next(iter(verified.items()))
                    return {
                        "status": "verified_published_anatomy",
                        "concept_id": cid,
                        "matched_description": label,
                        "match_method": "explicit_anatomical_complement_and_published_description",
                        "title_span": list(match.span(1)),
                        "lookup_path": concept["request_path"],
                        "lookup_sha256": concept["response_sha256"],
                        "body_structure_verification": concept[
                            "body_structure_verification"
                        ],
                        "sites": [{"concept_id": cid, "descriptions": [label]}],
                        "mapping_equivalence_asserted": False,
                    }
        return {
            "status": "unresolved",
            "reason": "no_unique_verified_published_description",
            "sites": [],
        }

    def review(self, candidate, phrase):
        request = {
            "code": self.code,
            "concept_id": candidate["concept_id"],
            "diagnostic_text": self.diagnostic,
            "source_snapshot_sha256": self.snapshot,
            "target_version": self.resolver.version,
        }
        evidence = prepare_evidence(request)
        manual, manual_coverage = build_manual_context(
            request, evidence, transport=self.fetch, client=self
        )
        index, index_coverage = build_index_context(
            request, evidence, transport=self.fetch, client=self
        )
        evidence.extend(manual)
        evidence.extend(index)
        evidence, alignment = enrich_components(
            evidence, candidate["concept_id"], self.resolver
        )
        exclusion = anatomical_exclusion(evidence)
        constraint = effective_constraint(evidence)
        if exclusion:
            constraint = {
                "rule_id": "explicit_local_anatomical_exclusion",
                "assessment": "incompatible",
                "justification": "Una exclusión local explícita del código coincide con el sitio publicado del candidato.",
                "evidence_refs": [exclusion, "snomed-term"],
            }
        if not candidate["clinical_finding_scope"]:
            constraint = {
                "rule_id": "outside_clinical_finding_scope",
                "assessment": "incompatible",
                "justification": "El concepto pertenece a otra clase semántica y no representa aquí un hallazgo clínico.",
                "evidence_refs": ["snomed-term"],
            }
        anatomy = compare_sites(
            self.anchor["sites"],
            sites(candidate["published_fhir_attributes"]),
            self.anatomical_resolver,
        )
        if constraint and constraint["assessment"] == "incompatible":
            status = "excluded_by_explicit_constraint"
        elif (
            constraint
            or phrase["scope"] != "asserted"
            or anatomy["status"] != "same_published_site"
        ):
            status = "requires_review"
        else:
            status = "no_detected_conflict"
        refs = set(constraint.get("evidence_refs", [])) if constraint else set()
        citations = [
            {
                k: item[k]
                for k in [
                    "id",
                    "type",
                    "role",
                    "text",
                    "provenance",
                    "volume",
                    "record_ids",
                ]
                if k in item
            }
            for item in evidence
            if item["id"] in refs
        ]
        result = {
            "status": status,
            "anatomy": anatomy,
            "input_scope": phrase["scope"],
            "constraint": constraint,
            "citations": citations,
            "component_alignment": alignment,
            "documentary_coverage": {
                "manual": manual_coverage,
                "index": index_coverage,
            },
            "positive_mapping_approved": False,
        }
        result["comparison"] = build_comparison(evidence, result, self.anchor)
        if result["comparison"]:
            known = {item["id"] for item in citations}
            citations.extend(item for item in result["comparison"]["sources"] if item["id"] not in known)
        return result

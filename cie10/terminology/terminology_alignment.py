"""Bounded component resolution using active published descriptions and FHIR.

No embedding score or lexical similarity is treated as clinical equivalence.
The alias index proposes candidates; dated FHIR lookups verify each description.
Ambiguous matches and exhausted budgets remain unresolved.
"""

import json, re, sqlite3
from pathlib import Path
from urllib.parse import urlencode
from cie10.api.mapping_context import ContextError, digest
from cie10.retrieval.retrieval_configuration import load_active_index, EDITION
from cie10.retrieval.retrieval_core import sha256
from cie10.retrieval.full_retrieval_runtime import streamed_sha256
from cie10.terminology.snowstorm_verification import SnowstormFHIR
from cie10.reasoning.assertions import extract_assertions, ARTICLES
from cie10.reasoning.assertion_comparison import assertion_constraint

POLICY = "published_component_identity_and_directional_subsumption_v1"


def canonical(text):
    # Reuse the literal grammar, including its treatment of semantic tags and NOS.
    text = re.sub(r"\s*\((?:trastorno|hallazgo)\)\s*$", "", text, flags=re.IGNORECASE)
    frames = extract_assertions(text, "descriptor")
    if len(frames) != 1 or frames[0].feature:
        return ()
    return frames[0].condition


def variants(word):
    out = {word}
    if len(word) > 4 and word.endswith("s"):
        out.add(word[:-1])
    if len(word) > 5 and word.endswith("es"):
        out.add(word[:-2])
    return out


def match_kind(phrase, label):
    if phrase == label:
        return "exact_published_description"
    if len(phrase) == len(label) and all(
        b in variants(a) for a, b in zip(phrase, label)
    ):
        return "published_description_with_regular_plural_variant"
    return None


class ComponentResolver:
    def __init__(
        self,
        index,
        version=EDITION,
        verifier=None,
        term_budget=24,
        relation_budget=8,
        row_budget=256,
    ):
        self.index = Path(index)
        self.version = version
        self.verifier = verifier or SnowstormFHIR("http://127.0.0.1:8081/fhir", version)
        self.term_budget = term_budget
        self.relation_budget = relation_budget
        self.row_budget = row_budget
        self.terms = {}
        self.concepts = {}
        self.relations = {}
        self.checked_version = False
        self.stats = {
            "term_attempts": 0,
            "relationship_attempts": 0,
            "unresolved": 0,
            "nonclinical_rejected": 0,
            "ambiguous_rejected": 0,
            "budget_exhausted": False,
        }
        self.db = sqlite3.connect(
            (self.index / "aliases.sqlite").resolve().as_uri() + "?mode=ro", uri=True
        )

    def close(self):
        self.db.close()

    def _concept(self, cid):
        if cid in self.concepts:
            return self.concepts[cid]
        if not self.checked_version:
            self.verifier.require_version()
            self.checked_version = True
        active = self.verifier.lookup_active(cid)
        path = "/CodeSystem/$lookup?" + urlencode(
            dict(
                system="http://snomed.info/sct",
                version=self.version,
                code=cid,
                displayLanguage="es",
            )
        )
        data = self.verifier.get(path)
        params = data.get("parameter", [])
        if [
            p.get("valueString", p.get("valueUri"))
            for p in params
            if p.get("name") == "version"
        ] != [self.version]:
            raise ContextError("Otra edición al resolver un componente.")
        codes = [
            p.get("valueCode", p.get("valueString"))
            for p in params
            if p.get("name") == "code"
        ]
        systems = [
            p.get("valueUri", p.get("valueString"))
            for p in params
            if p.get("name") == "system"
        ]
        if codes != [cid] or systems != ["http://snomed.info/sct"]:
            raise ContextError("Otro concepto o sistema al verificar el componente.")
        labels = []
        for p in params:
            if p.get("name") == "designation":
                parts = p.get("part", [])
                if any(
                    x.get("name") == "language" and x.get("valueCode") == "es"
                    for x in parts
                ):
                    labels.extend(
                        x["valueString"]
                        for x in parts
                        if x.get("name") == "value"
                        and isinstance(x.get("valueString"), str)
                    )
        if not labels:
            raise ContextError(
                "Faltan descripciones españolas verificables para el componente."
            )
        value = {
            "concept_id": cid,
            "labels": list(dict.fromkeys(labels)),
            "request_path": path,
            "response_sha256": digest(data),
            "active_check": active,
        }
        scope = (
            self._subsumes_request("404684003", cid)
            if cid != "404684003"
            else {"outcome": "equivalent"}
        )
        value["clinical_finding_scope"] = scope["outcome"] in ("subsumes", "equivalent")
        value["scope_verification"] = scope
        self.concepts[cid] = value
        return value

    def resolve(self, phrase):
        phrase = tuple(phrase)
        if phrase in self.terms:
            return self.terms[phrase]
        self.terms[phrase] = None
        if (
            not phrase
            or len(phrase) > 16
            or any(not re.fullmatch(r"[a-z0-9]+", w) for w in phrase)
        ):
            return None
        if self.stats["term_attempts"] >= self.term_budget:
            self.stats["budget_exhausted"] = True
            return None
        self.stats["term_attempts"] += 1
        expression = " AND ".join(
            "(" + " OR ".join('"' + v + '"' for v in sorted(variants(w))) + ")"
            for w in phrase
        )
        rows = self.db.execute(
            "SELECT a.concept_id,a.term FROM lexical JOIN aliases a ON a.alias_no=lexical.rowid WHERE lexical MATCH ?",
            (expression,),
        ).fetchmany(self.row_budget + 1)
        if len(rows) > self.row_budget:
            self.stats["unresolved"] += 1
            return None
        exact = {}
        inflected = {}
        for cid, label in rows:
            kind = match_kind(phrase, canonical(label))
            if kind:
                (
                    exact if kind == "exact_published_description" else inflected
                ).setdefault(cid, []).append(label)
        matches = exact or inflected
        if len(matches) != 1:
            if len(matches) > 1:
                self.stats["ambiguous_rejected"] += 1
            self.stats["unresolved"] += 1
            return None
        cid = next(iter(matches))
        concept = self._concept(cid)
        if not concept["clinical_finding_scope"]:
            self.stats["nonclinical_rejected"] += 1
            self.stats["unresolved"] += 1
            return None
        valid = [
            (label, match_kind(phrase, canonical(label))) for label in concept["labels"]
        ]
        valid = [x for x in valid if x[1]]
        if exact:
            valid = [x for x in valid if x[1] == "exact_published_description"]
        if not valid:
            self.stats["unresolved"] += 1
            return None
        label, kind = sorted(
            valid, key=lambda x: (x[1] != "exact_published_description", x[0])
        )[0]
        result = {
            **concept,
            "matched_label": label,
            "match_method": kind,
            "phrase_sha256": digest(phrase),
        }
        self.terms[phrase] = result
        return result

    def _subsumes_request(self, a, b):
        path = "/CodeSystem/$subsumes?" + urlencode(
            dict(
                system="http://snomed.info/sct", version=self.version, codeA=a, codeB=b
            )
        )
        data = self.verifier.get(path)
        params = data.get("parameter", [])
        values = lambda name: [
            p.get("valueCode", p.get("valueString", p.get("valueUri")))
            for p in params
            if p.get("name") == name
        ]
        if values("system") != ["http://snomed.info/sct"] or values("version") != [
            self.version
        ]:
            raise ContextError("La relación no está vinculada a la edición solicitada.")
        outcome = values("outcome")
        if len(outcome) != 1 or outcome[0] not in {
            "subsumes",
            "subsumed-by",
            "equivalent",
            "not-subsumed",
        }:
            raise ContextError("Resultado de subsunción no reconocido.")
        value = {
            "outcome": outcome[0],
            "request_path": path,
            "response_sha256": digest(data),
        }
        if outcome[0] in {"subsumes", "subsumed-by"}:
            value.update(
                broader=a if outcome[0] == "subsumes" else b,
                narrower=b if outcome[0] == "subsumes" else a,
            )
        return value

    def relation(self, a, b):
        if a == b:
            return {"outcome": "same_concept", "broader": a, "narrower": b}
        key = tuple(sorted((a, b)))
        if key in self.relations:
            return self.relations[key]
        self.relations[key] = None
        if self.stats["relationship_attempts"] >= self.relation_budget:
            self.stats["budget_exhausted"] = True
            return None
        self.stats["relationship_attempts"] += 1
        if (
            not self._concept(a)["clinical_finding_scope"]
            or not self._concept(b)["clinical_finding_scope"]
        ):
            return None
        value = self._subsumes_request(a, b)
        self.relations[key] = value
        return value


def enrich_components(evidence, candidate_id, resolver):
    frames = []
    for item in evidence:
        if (
            item.get("role") in ("title", "candidate_term", "candidate_alias")
            or item["type"] == "INPUT"
        ):
            frames.extend(
                extract_assertions(item["text"], item["id"], item["type"] == "INPUT")
            )
    pairs = [
        (a, b)
        for i, a in enumerate(frames)
        for b in frames[i + 1 :]
        if (a.source_id != b.source_id or a.body_span != b.body_span)
        and a.feature
        and b.feature
        and (
            a.value != b.value
            or a.modality not in ("definition", "asserted")
            or b.modality not in ("definition", "asserted")
            or a.subject == "other"
            or b.subject == "other"
        )
    ]
    if not pairs:
        return list(evidence), {"status": "not_needed", "policy": POLICY}
    bindings = {}
    relations = {}

    def bind(phrase):
        value = resolver.resolve(phrase)
        if value:
            bindings[digest(tuple(phrase))] = value
        return value

    for a, b in pairs:
        if a.condition == b.condition:
            condition_match = True
        else:
            x, y = bind(a.condition), bind(b.condition)
            condition_match = bool(x and y and x["concept_id"] == y["concept_id"])
        if not condition_match or a.feature == b.feature:
            continue
        x, y = bind(a.feature), bind(b.feature)
        if x and y and x["concept_id"] != y["concept_id"]:
            relation = resolver.relation(x["concept_id"], y["concept_id"])
            if relation and relation.get("broader"):
                relations[(relation["broader"], relation["narrower"])] = relation
    grouped = {}
    for key, match in bindings.items():
        cid = match["concept_id"]
        entry = grouped.setdefault(cid, {"matches": [], "bindings": []})
        entry["matches"].append(match)
        entry["bindings"].append(
            {
                "phrase_sha256": key,
                "match_method": match["match_method"],
                "description": match["matched_label"],
            }
        )
    added = []
    for cid, entry in sorted(grouped.items()):
        descriptions = sorted({x["matched_label"] for x in entry["matches"]})
        record = entry["matches"][0]
        added.append(
            {
                "id": "alignment-component-" + cid,
                "type": "SNOMED",
                "concept_id": candidate_id,
                "role": "component_alignment",
                "component_id": cid,
                "component_bindings": entry["bindings"],
                "text": "Componente SNOMED verificado "
                + cid
                + ": "
                + " | ".join(descriptions)
                + ". Estas descripciones identifican un componente; no declaran equivalencia del mapeo completo.",
                "provenance": resolver.version,
                "verification": {
                    "request_path": record["request_path"],
                    "response_sha256": record["response_sha256"],
                    "scope_verification": record["scope_verification"],
                },
            }
        )
    for (broader, narrower), relation in sorted(relations.items()):
        added.append(
            {
                "id": "alignment-subsumption-" + broader + "-" + narrower,
                "type": "SNOMED",
                "concept_id": candidate_id,
                "role": "component_subsumption",
                "broader_component_id": broader,
                "narrower_component_id": narrower,
                "text": "Relación SNOMED verificada: "
                + narrower
                + " es subtipo de "
                + broader
                + ". La relación se aplica en esa dirección y no implica equivalencia entre ambos conceptos.",
                "provenance": resolver.version,
                "verification": relation,
            }
        )
    return list(evidence) + added, {
        "status": "prepared",
        "policy": POLICY,
        "components_verified": len(grouped),
        "subsumptions_verified": len(relations),
        **resolver.stats,
    }


def configured_components(root, request, evidence):
    root = Path(root)
    path = root / "infra/retrieval/active-component-alignment.json"
    if not path.is_file():
        return list(evidence), {"status": "disabled", "policy": POLICY}
    resolver = None
    try:
        cfg = json.loads(path.read_text())
        if (
            cfg.get("status") != "enabled_local_experimental"
            or cfg.get("version") != request.get("target_version")
            or cfg.get("source_snapshot_sha256")
            != request.get("source_snapshot_sha256")
        ):
            return list(evidence), {
                "status": "not_configured_for_request",
                "policy": POLICY,
            }
        if cfg.get("policy") != POLICY or not all(
            sha256(root / p) == h for p, h in cfg["implementation_sha256"].items()
        ):
            raise ContextError("Cambió la implementación de alineación.")
        index, info = load_active_index(root)
        if (
            info["schema_version"] != "0.2.0"
            or sha256(index / "index.json") != cfg["index_manifest_sha256"]
        ):
            raise ContextError("Índice de otra versión para alinear componentes.")
        if streamed_sha256(index / "aliases.sqlite") != info["files"]["aliases.sqlite"]:
            raise ContextError("Cambió el catálogo de descripciones.")
        resolver = ComponentResolver(index, request["target_version"])
        return enrich_components(evidence, request["concept_id"], resolver)
    except Exception:
        return list(evidence), {
            "status": "unavailable_prior_policy_retained",
            "policy": POLICY,
        }
    finally:
        if resolver:
            resolver.close()

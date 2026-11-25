"""Source-backed alignment tests with a synthetic terminology, no network."""

import json, sqlite3, tempfile, unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from cie10.terminology_alignment import ComponentResolver, canonical, enrich_components
from cie10.reasoning.grounded_alignment import grounded_constraint
from cie10.mapping_context import ContextError
from cie10.retrieval_evaluation import normalize

VERSION = "http://snomed.info/sct/449081005/version/20261110"
CID = "999999999"
LABELS = {
    "111111": ["cálculo de órgano", "litiasis de órgano"],
    "222222": ["cálculo renal"],
    "333333": ["inflamación"],
    "444444": ["inflamación aguda"],
    "555555": ["inflamación crónica"],
}


def evidence(
    title="Cálculo de órgano sin inflamación",
    term="Cálculo de órgano sin inflamación",
    text="Litiasis de órgano con inflamación aguda.",
):
    rows = [
        dict(id="title", type="CIE10", role="title", text=title),
        dict(
            id="term", type="SNOMED", role="candidate_term", text=term, concept_id=CID
        ),
    ]
    if text:
        rows.append(dict(id="input", type="INPUT", text=text))
    return rows


class FakeFHIR:
    def __init__(self, labels=None):
        self.labels = labels or LABELS
        self.bad_version = False
        self.bad_relation_version = False
        self.calls = []
        self.nonclinical = set()

    def require_version(self):
        return {"version": VERSION}

    def lookup_active(self, cid):
        return {"active": True, "version": VERSION}

    def get(self, path):
        self.calls.append(path)
        q = parse_qs(urlsplit(path).query)
        if "$lookup" in path:
            cid = q["code"][0]
            params = [
                dict(name="system", valueUri="http://snomed.info/sct"),
                dict(name="code", valueCode=cid),
                dict(
                    name="version", valueString="wrong" if self.bad_version else VERSION
                ),
            ]
            params += [
                dict(
                    name="designation",
                    part=[
                        dict(name="language", valueCode="es"),
                        dict(name="value", valueString=label),
                    ],
                )
                for label in self.labels[cid]
            ]
        else:
            a, b = q["codeA"][0], q["codeB"][0]
            outcome = (
                "subsumes"
                if (a, b) == ("333333", "444444")
                else "subsumed-by" if (a, b) == ("444444", "333333") else "not-subsumed"
            )
            if a == "404684003":
                outcome = "not-subsumed" if b in self.nonclinical else "subsumes"
            params = [
                dict(name="outcome", valueString=outcome),
                dict(name="system", valueUri="http://snomed.info/sct"),
                dict(
                    name="version",
                    valueString="wrong" if self.bad_relation_version else VERSION,
                ),
            ]
        return dict(resourceType="Parameters", parameter=params)


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fhir = FakeFHIR()
        db = sqlite3.connect(self.root / "aliases.sqlite")
        db.executescript(
            "CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id,term,normalized); CREATE VIRTUAL TABLE lexical USING fts5(normalized,content='aliases',content_rowid='alias_no');"
        )
        for cid, labels in LABELS.items():
            for text in labels:
                db.execute(
                    "INSERT INTO aliases(concept_id,term,normalized) VALUES(?,?,?)",
                    (cid, text, normalize(text)),
                )
        db.execute("INSERT INTO lexical(lexical) VALUES('rebuild')")
        db.commit()
        db.close()
        self.resolver = ComponentResolver(self.root, verifier=self.fhir)

    def tearDown(self):
        self.resolver.close()
        self.tmp.cleanup()

    def test_aliases_of_same_verified_component_resolve_together(self):
        a = self.resolver.resolve(("calculo", "organo"))
        b = self.resolver.resolve(("litiasis", "organo"))
        self.assertEqual(a["concept_id"], b["concept_id"])
        self.assertEqual(a["match_method"], "exact_published_description")

    def test_plural_requires_a_published_singular_counterpart(self):
        r = self.resolver.resolve(("calculos", "organo"))
        self.assertEqual(r["concept_id"], "111111")
        self.assertIn("plural", r["match_method"])

    def test_similar_word_without_published_counterpart_is_not_matched(self):
        self.assertIsNone(self.resolver.resolve(("calculo", "organico")))

    def test_ambiguous_alias_is_not_resolved_by_first_result(self):
        db = sqlite3.connect(self.root / "aliases.sqlite")
        db.execute(
            "INSERT INTO aliases(concept_id,term,normalized) VALUES(?,?,?)",
            ("777777", "litiasis de órgano", normalize("litiasis de órgano")),
        )
        db.execute("INSERT INTO lexical(lexical) VALUES('rebuild')")
        db.commit()
        db.close()
        self.assertIsNone(self.resolver.resolve(("litiasis", "organo")))

    def test_live_descriptions_recheck_index_proposal(self):
        self.fhir.labels = {**LABELS, "111111": ["Otro nombre"]}
        self.assertIsNone(self.resolver.resolve(("litiasis", "organo")))

    def test_lookup_version_mismatch_is_rejected(self):
        self.fhir.bad_version = True
        with self.assertRaises(ContextError):
            self.resolver.resolve(("litiasis", "organo"))

    def test_budget_does_not_silently_choose_an_unverified_result(self):
        self.resolver.term_budget = 0
        self.assertIsNone(self.resolver.resolve(("litiasis", "organo")))
        self.assertTrue(self.resolver.stats["budget_exhausted"])

    def test_result_row_limit_does_not_hide_ambiguity(self):
        self.resolver.row_budget = 0
        self.assertIsNone(self.resolver.resolve(("litiasis", "organo")))

    def test_subsumption_direction_is_retained_when_query_reversed(self):
        r = self.resolver.relation("444444", "333333")
        self.assertEqual((r["broader"], r["narrower"]), ("333333", "444444"))
        self.assertEqual(self.resolver.relation("333333", "444444"), r)

    def test_subsumption_version_mismatch_is_rejected(self):
        self.fhir.bad_relation_version = True
        with self.assertRaises(ContextError):
            self.resolver.relation("333333", "444444")

    def test_non_subsumption_is_not_relabelled_as_equivalence(self):
        self.assertNotIn("broader", self.resolver.relation("444444", "555555"))

    def test_same_component_and_nested_feature_support_a_conflict(self):
        enriched, meta = enrich_components(evidence(), CID, self.resolver)
        r = grounded_constraint(enriched)
        self.assertEqual(r["assessment"], "incompatible")
        self.assertEqual(r["rule_id"], "grounded_polarity_conflict")
        self.assertEqual(
            r["comparison_trace"]["condition_alignment"]["concept_id"], "111111"
        )
        self.assertIn("alignment-subsumption-333333-444444", r["evidence_refs"])

    def test_absent_subtype_does_not_disprove_generic_presence(self):
        e = evidence(
            "Cálculo de órgano sin inflamación aguda",
            "Cálculo de órgano sin inflamación aguda",
            "Litiasis de órgano con inflamación.",
        )
        enriched, _ = enrich_components(e, CID, self.resolver)
        r = grounded_constraint(enriched)
        self.assertEqual(r["assessment"], "undetermined")
        self.assertEqual(r["rule_id"], "grounded_nested_scope_review")

    def test_siblings_are_not_assumed_to_be_opposites(self):
        e = evidence(
            "Cálculo de órgano sin inflamación crónica",
            "Cálculo de órgano sin inflamación crónica",
            "Litiasis de órgano con inflamación aguda.",
        )
        enriched, _ = enrich_components(e, CID, self.resolver)
        self.assertEqual(grounded_constraint(enriched)["assessment"], "undetermined")

    def test_different_condition_identity_never_becomes_same_condition(self):
        e = evidence(text="Cálculo renal con inflamación aguda.")
        enriched, _ = enrich_components(e, CID, self.resolver)
        self.assertIsNone(grounded_constraint(enriched))

    def test_relative_and_hypothetical_paraphrases_are_not_patient_facts(self):
        for text in [
            "Su madre tiene litiasis de órgano con inflamación aguda.",
            "Si el paciente tuviera litiasis de órgano con inflamación aguda, se evaluaría.",
        ]:
            enriched, _ = enrich_components(evidence(text=text), CID, self.resolver)
            self.assertEqual(
                grounded_constraint(enriched)["assessment"], "undetermined"
            )

    def test_trace_uses_verified_sources_without_copying_input(self):
        enriched, _ = enrich_components(evidence(), CID, self.resolver)
        r = grounded_constraint(enriched)
        self.assertNotIn("text", r["comparison_trace"]["right"])
        self.assertTrue(
            all(
                "component_alignment" != x.get("role") or x["concept_id"] == CID
                for x in enriched
            )
        )

    def test_equal_positive_components_never_auto_approve(self):
        e = evidence(
            "Cálculo de órgano con inflamación",
            "Cálculo de órgano con inflamación",
            "Litiasis de órgano con inflamación.",
        )
        enriched, _ = enrich_components(e, CID, self.resolver)
        self.assertIsNone(grounded_constraint(enriched))

    def test_unique_label_from_nonclinical_hierarchy_is_not_a_condition(self):
        self.fhir.nonclinical.add("111111")
        self.assertIsNone(self.resolver.resolve(("litiasis", "organo")))

    def test_unverified_nested_qualifier_is_not_reduced_to_first_word(self):
        e = evidence(
            "Cálculo de órgano sin inflamación aguda",
            "Cálculo de órgano sin inflamación aguda",
            "Cálculo de órgano con inflamación.",
        )
        r = grounded_constraint(e)
        self.assertEqual(r["assessment"], "undetermined")
        self.assertEqual(
            r["comparison_trace"]["feature_alignment"]["kind"], "unverified_nested"
        )

    def test_nonclinical_component_cannot_participate_in_subsumption(self):
        self.fhir.nonclinical.add("444444")
        self.assertIsNone(self.resolver.relation("333333", "444444"))

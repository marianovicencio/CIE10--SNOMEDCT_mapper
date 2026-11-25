"""Contract tests: retrieval is never a verified clinical mapping."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cie10.mapping_context import ContextError, digest
from cie10.semantic_proposals import (
    prepare_phrases,
    review_candidate,
    PhraseProposalEngine,
    published_attributes,
)


class ProposalTests(unittest.TestCase):
    def test_preserve_original_accents_and_offsets(self):
        text = "No presenta cálculos vesiculares."
        p = prepare_phrases(text)[0]
        self.assertEqual(p["text"], "cálculos vesiculares")
        self.assertEqual(text[slice(*p["span"])], p["text"])
        self.assertEqual(p["scope"], "negated")

    def test_scope_controls(self):
        cases = [
            ("Si el paciente tuviera asma, se evaluaría.", "hypothetical"),
            ("Posible asma.", "uncertain"),
            ("Su madre presenta asma.", "other_subject"),
            ("Antecedente de asma.", "historical"),
            ("Asma.", "asserted"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(prepare_phrases(text)[0]["scope"], expected)

    def test_absent_feature_not_absent_condition(self):
        p = prepare_phrases("Úlcera sin hemorragia.")[0]
        self.assertEqual(p["text"], "Úlcera sin hemorragia")
        self.assertEqual(p["scope"], "asserted")
        self.assertEqual(p["assertions"][0]["value"], "absent")

    def test_coordinated_features_keep_single_query_and_qualifiers(self):
        p = prepare_phrases("Úlcera sin hemorragia ni perforación.")
        self.assertEqual(len(p), 1)
        self.assertEqual(len(p[0]["assertions"]), 2)
        self.assertIn("ni perforación", p[0]["text"])

    def test_unknown_scope_not_claimed_exhaustive(self):
        p = prepare_phrases("Asma.")[0]
        self.assertFalse(p["scope_is_exhaustive"])

    def test_invalid_inputs(self):
        for text in [None, [], 1, "", " ", "x" * 1001, "A. B. C. D. E."]:
            with self.subTest(text=text):
                with self.assertRaises(ContextError):
                    prepare_phrases(text)

    def candidate(self, clinical=True, term="asma"):
        concept = {
            "concept_id": "195967001",
            "labels": [term],
            "clinical_finding_scope": clinical,
            "request_path": "/lookup",
            "response_sha256": digest({"parameter": []}),
            "active_check": {"active": True},
            "scope_verification": {"outcome": "subsumes"},
        }
        return SimpleNamespace(
            _concept=lambda cid: concept,
            verifier=SimpleNamespace(get=lambda path: {"parameter": []}),
        )

    def test_exact_description_still_requires_review(self):
        row = dict(
            concept_id="195967001", term="asma", description_id="123", score=0.999
        )
        r = review_candidate(row, prepare_phrases("Asma.")[0], self.candidate())
        self.assertEqual(r["match_basis"], "exact_published_description")
        self.assertEqual(r["status"], "review_required")
        for key in [
            "patient_assertion",
            "implies_clinical_equivalence",
            "usable_as_verified_component_binding",
            "score_is_probability",
        ]:
            self.assertFalse(r[key])

    def test_similarity_not_promoted_to_published_match(self):
        row = dict(
            concept_id="195967001", term="asma", description_id="123", score=0.99
        )
        r = review_candidate(
            row, prepare_phrases("Bronquios con síntomas.")[0], self.candidate()
        )
        self.assertEqual(r["match_basis"], "semantic_similarity_only")
        self.assertFalse(r["usable_as_verified_component_binding"])

    def test_nonclinical_candidates_retained_and_marked(self):
        row = dict(
            concept_id="195967001", term="asma", description_id="123", score=0.99
        )
        r = review_candidate(row, prepare_phrases("Asma.")[0], self.candidate(False))
        self.assertEqual(r["status"], "outside_clinical_finding_scope")

    def test_unpublished_ranked_description_blocks(self):
        row = dict(
            concept_id="195967001", term="inventado", description_id="123", score=0.99
        )
        with self.assertRaises(ContextError):
            review_candidate(row, prepare_phrases("Asma.")[0], self.candidate())

    def test_negated_phrase_cannot_be_patient_assertion(self):
        row = dict(
            concept_id="195967001", term="asma", description_id="123", score=0.99
        )
        r = review_candidate(
            row, prepare_phrases("No presenta asma.")[0], self.candidate()
        )
        self.assertTrue(r["input_scope_restricted"])
        self.assertFalse(r["patient_assertion"])

    def test_batch_and_top_k_budgets(self):
        e = object.__new__(PhraseProposalEngine)
        for texts, k in [
            ([], 5),
            (["asma"] * 17, 5),
            (["asma"], True),
            (["asma"], 6),
            ("asma", 5),
        ]:
            with self.assertRaises(ContextError):
                e.propose_batch(texts, k)

    def test_no_silent_truncation(self):
        e = object.__new__(PhraseProposalEngine)
        e.engine = SimpleNamespace(tokenizer=lambda *a, **kw: {"input_ids": [[1] * 65]})
        with self.assertRaisesRegex(ContextError, "64 tokens"):
            e.propose_batch(["asma"])

    def test_attributes_require_unchanged_source(self):
        resolver = SimpleNamespace(
            verifier=SimpleNamespace(get=lambda _: {"parameter": []})
        )
        with self.assertRaises(ContextError):
            published_attributes(
                {"request_path": "/lookup", "response_sha256": "changed"}, resolver
            )

    def test_attribute_projection_preserves_parts_and_excludes_children(self):
        site = {
            "name": "property",
            "part": [
                {"name": "code", "valueCode": "363698007"},
                {"name": "description", "valueString": "sitio publicado"},
                {"name": "value", "valueCode": "123"},
            ],
        }
        child = {
            "name": "property",
            "part": [
                {"name": "code", "valueCode": "child"},
                {"name": "value", "valueCode": "456"},
            ],
        }
        data = {"parameter": [site, child]}
        resolver = SimpleNamespace(verifier=SimpleNamespace(get=lambda _: data))
        verified = {"request_path": "/lookup", "response_sha256": digest(data)}
        self.assertEqual(published_attributes(verified, resolver), [site])


if __name__ == "__main__":
    unittest.main()

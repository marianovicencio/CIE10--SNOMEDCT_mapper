"""Cross-family structural tests for source-bound proposal contrast."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from cie10.api.mapping_context import ContextError
from cie10.comparison.candidate_context import sites, compare_sites, CIEContextReviewer, BodySiteRelations


class AnatomyTests(TestCase):
    def site(self, cid):
        return {"concept_id": cid, "descriptions": ["published"]}

    def compare(self, outcome):
        resolver = SimpleNamespace(relation=lambda a, b: {"outcome": outcome})
        return compare_sites([self.site("100")], [self.site("200")], resolver)

    def test_same_site_requires_no_relation_guess(self):
        r = compare_sites([self.site("100")], [self.site("100")], None)
        self.assertEqual(r["status"], "same_published_site")
        self.assertFalse(r["proves_disjointness"])

    def test_missing_site_does_not_create_conflict(self):
        self.assertEqual(
            compare_sites([], [self.site("100")], None)["status"], "not_comparable"
        )
        self.assertEqual(
            compare_sites([self.site("100")], [], None)["status"], "not_comparable"
        )

    def test_no_subsumption_is_not_proof_of_disjointness(self):
        r = self.compare("not-subsumed")
        self.assertEqual(r["status"], "no_hierarchy_link_review")
        self.assertFalse(r["proves_disjointness"])

    def test_narrower_requires_review(self):
        self.assertEqual(
            self.compare("subsumes")["status"], "candidate_site_narrower_review"
        )

    def test_broader_requires_review(self):
        self.assertEqual(
            self.compare("subsumed-by")["status"], "candidate_site_broader_review"
        )

    def test_exhausted_relation_budget_not_incompatible(self):
        r = compare_sites(
            [self.site("100")],
            [self.site("200")],
            SimpleNamespace(relation=lambda a, b: None),
        )
        self.assertEqual(r["status"], "relation_unresolved")

    def test_multiple_sites_not_reduced_to_matching_site(self):
        r = compare_sites(
            [self.site("100")],
            [self.site("100"), self.site("200")],
            SimpleNamespace(relation=lambda a, b: {"outcome": "not-subsumed"}),
        )
        self.assertEqual(r["status"], "multiple_sites_review")

    def test_only_published_finding_sites_extracted(self):
        prop = {
            "part": [
                {"name": "code", "valueCode": "363698007"},
                {"name": "value", "valueCode": "100"},
                {"name": "description", "valueString": "site"},
            ]
        }
        other = {
            "part": [
                {"name": "code", "valueCode": "116676008"},
                {"name": "value", "valueCode": "200"},
            ]
        }
        self.assertEqual(
            sites([prop, prop, other]),
            [{"concept_id": "100", "descriptions": ["site"]}],
        )

    def test_malformed_site_blocks(self):
        with self.assertRaises(ContextError):
            sites([{"part": [{"name": "code", "valueCode": "363698007"}]}])


class BodyRelationTests(TestCase):
    def resolver(self, valid=True):
        def relation(a, b):
            if a == "123037004":
                return {
                    "outcome": "subsumes" if valid else "not-subsumed",
                    "request_path": "body-check",
                }
            return {
                "outcome": "subsumes" if (a, b) == ("100", "200") else "subsumed-by",
                "request_path": a + "-" + b,
            }

        return SimpleNamespace(
            _concept=lambda cid: {"concept_id": cid, "clinical_finding_scope": False},
            _subsumes_request=relation,
        )

    def test_body_structures_not_rejected_as_nonclinical_findings(self):
        r = BodySiteRelations(self.resolver())
        self.assertEqual(r.relation("100", "200")["outcome"], "subsumes")

    def test_directional_cache_keeps_inverse_outcomes(self):
        r = BodySiteRelations(self.resolver())
        self.assertEqual(r.relation("100", "200")["outcome"], "subsumes")
        self.assertEqual(r.relation("200", "100")["outcome"], "subsumed-by")
        self.assertEqual(r.relation("100", "200")["request_path"], "100-200")

    def test_body_scope_is_verified(self):
        self.assertIsNone(
            BodySiteRelations(self.resolver(False)).relation("100", "200")
        )

    def test_body_request_budget_is_bounded(self):
        r = BodySiteRelations(self.resolver(), budget=2)
        self.assertIsNone(r.relation("100", "200"))
        self.assertEqual(r.calls, 2)


class ContextTests(TestCase):
    def reviewer(self):
        r = object.__new__(CIEContextReviewer)
        r.code = "A00.0"
        r.diagnostic = "condition"
        r.snapshot = "hash"
        r.title = "Unrecognized clinical phrase"
        r.resolver = SimpleNamespace(version="edition", resolve=lambda _: None)
        r.anatomical_resolver = None
        r.anchor = {"sites": []}
        r.doc = {"classification": {}}
        r.fetch = lambda _: None
        return r

    def test_unknown_title_does_not_use_semantic_guess(self):
        r = self.reviewer()
        r.resolver.index = Path("/tmp/unopened-test-index")
        r.resolver.verifier = None
        with patch("cie10.comparison.candidate_context.ComponentResolver") as factory:
            factory.return_value.resolve.return_value = None
            self.assertEqual(r.resolve_anchor()["status"], "unresolved")

    def test_invalid_code_blocks_before_io(self):
        for code in [None, "K80.-", "K80.2 extra", "k80.2"]:
            with self.assertRaises(ContextError):
                CIEContextReviewer(".", code, "text", None)


    def run_review(self, scope="asserted", constraint=None, clinical=True):
        r = self.reviewer()
        r.anchor = {"sites": [{"concept_id": "100"}]}
        candidate = {
            "concept_id": "123456",
            "clinical_finding_scope": clinical,
            "published_fhir_attributes": [],
        }
        ev = [
            {"id": "cie-title", "type": "CIE10", "role": "title", "text": "title"},
            {
                "id": "manual-source",
                "type": "CIE10",
                "volume": 2,
                "role": "manual_instruction",
                "text": "conditioned source",
            },
        ]
        with patch("cie10.comparison.candidate_context.prepare_evidence", return_value=ev), patch(
            "cie10.comparison.candidate_context.build_manual_context",
            return_value=([], {"scope": "morbidity"}),
        ), patch(
            "cie10.comparison.candidate_context.build_index_context",
            return_value=([], {"scope": "morbidity"}),
        ), patch(
            "cie10.comparison.candidate_context.enrich_components",
            side_effect=lambda e, *_: (e, {"status": "not_needed"}),
        ), patch(
            "cie10.comparison.candidate_context.anatomical_exclusion", return_value=None
        ), patch(
            "cie10.comparison.candidate_context.effective_constraint", return_value=constraint
        ), patch(
            "cie10.comparison.candidate_context.compare_sites",
            return_value={"status": "same_published_site"},
        ):
            return r.review(candidate, {"scope": scope})

    def test_same_site_never_approves_mapping(self):
        result = self.run_review()
        self.assertEqual(result["status"], "no_detected_conflict")
        self.assertFalse(result["positive_mapping_approved"])

    def test_nonpatient_or_nonasserted_scope_still_requires_review(self):
        for scope in [
            "negated",
            "uncertain",
            "hypothetical",
            "other_subject",
            "historical",
        ]:
            self.assertEqual(self.run_review(scope)["status"], "requires_review")

    def test_explicit_conflict_excludes_with_citation(self):
        constraint = {
            "rule_id": "generic",
            "assessment": "incompatible",
            "evidence_refs": ["manual-source"],
        }
        r = self.run_review(constraint=constraint)
        self.assertEqual(r["status"], "excluded_by_explicit_constraint")
        self.assertEqual(r["citations"][0]["volume"], 2)

    def test_manual_pending_keeps_condition_and_citation(self):
        constraint = {
            "rule_id": "source_condition",
            "assessment": "undetermined",
            "evidence_refs": ["manual-source"],
        }
        r = self.run_review(constraint=constraint)
        self.assertEqual(r["status"], "requires_review")
        self.assertEqual(r["constraint"], constraint)

    def test_nonclinical_scope_excludes_regardless_of_site(self):
        r = self.run_review(clinical=False)
        self.assertEqual(r["status"], "excluded_by_explicit_constraint")
        self.assertEqual(r["constraint"]["rule_id"], "outside_clinical_finding_scope")


if __name__ == "__main__":
    main()

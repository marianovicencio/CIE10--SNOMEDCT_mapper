"""Integration adapter contracts; no models and no medical rule tuning."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from cie10.candidate_review_service import (
    validate_request,
    input_scope,
    review_candidates,
)
from cie10.mapping_context import ContextError
from cie10.retrieval_configuration import EDITION


def request():
    return {
        "code": "K80.2",
        "diagnostic_text": "condition",
        "concept_ids": ["235919008", "70650003"],
        "source_snapshot_sha256": "a" * 64,
        "target_version": EDITION,
    }


class AdapterTests(TestCase):
    def test_valid_request_preserves_input(self):
        r = request()
        r["diagnostic_text"] = "  Texto con acentos: riñón.  "
        self.assertEqual(validate_request(r), r)

    def test_invalid_pools(self):
        for ids in [
            [],
            ["123456"] * 2,
            ["123456"] * 6,
            [123456],
            ["../123456"],
            "123456",
        ]:
            r = request()
            r["concept_ids"] = ids
            with self.assertRaises(ContextError):
                validate_request(r)

    def test_version_and_snapshot_required(self):
        for field, value in [
            ("target_version", "other"),
            ("source_snapshot_sha256", "wrong"),
            ("code", "K80.-"),
            ("diagnostic_text", "x" * 4001),
        ]:
            r = request()
            r[field] = value
            with self.assertRaises(ContextError):
                validate_request(r)

    def test_unknown_fields_rejected(self):
        with self.assertRaises(ContextError):
            validate_request({**request(), "provider": "openai"})

    def test_code_only_not_treated_as_patient_assertion(self):
        self.assertEqual(input_scope(""), "not_provided")
        self.assertEqual(input_scope("  "), "not_provided")

    def test_existing_scopes_preserved(self):
        for text, expected in [
            ("No presenta asma.", "negated"),
            ("Posible asma.", "uncertain"),
            ("Su madre presenta asma.", "other_subject"),
            ("Antecedente de asma.", "historical"),
            ("Asma sin crisis.", "asserted"),
        ]:
            self.assertEqual(input_scope(text), expected)

    def run_adapter(self, snapshot="a" * 64):
        resolver = SimpleNamespace(
            version=EDITION,
            _concept=lambda cid: {"clinical_finding_scope": True, "labels": ["cálculo de vesícula biliar"] if cid == "235919008" else ["otro término"]},
            close=lambda: None,
        )
        reviewer = SimpleNamespace(
            snapshot=snapshot,
            title="Cálculo de la vesícula biliar",
            anchor={"sites": []},
            review=lambda c, p: {
                "status": (
                    "requires_review"
                    if c["concept_id"] == "70650003"
                    else "no_detected_conflict"
                ),
                "anatomy": {"status": "same_published_site"},
                "positive_mapping_approved": False,
            },
        )
        with patch(
            "cie10.candidate_review_service.load_active_index",
            return_value=(Path("/tmp/index"), {"files": {"aliases.sqlite": "hash"}}),
        ), patch(
            "cie10.candidate_review_service.streamed_sha256", return_value="hash"
        ), patch(
            "cie10.candidate_review_service.ComponentResolver", return_value=resolver
        ), patch(
            "cie10.candidate_review_service.CIEContextReviewer", return_value=reviewer
        ), patch(
            "cie10.candidate_review_service.published_attributes", return_value=[]
        ):
            return review_candidates(request(), ".")

    def test_existing_pool_preserved_without_automatic_selection(self):
        r = self.run_adapter()
        self.assertEqual(
            {c["id"] for c in r["candidates"]}, set(request()["concept_ids"])
        )
        self.assertFalse(r["automatic_selection"])
        self.assertTrue(r["candidate_set_preserved"])
        self.assertEqual([c["retrieval_rank"] for c in r["candidates"]], [1, 2])

    def test_context_does_not_promote_anatomical_match_over_search_order(self):
        original_request = request()
        original_request["concept_ids"] = ["70650003", "235919008"]
        with patch(__name__ + ".request", return_value=original_request):
            r = self.run_adapter()
        self.assertEqual(
            [c["id"] for c in r["candidates"]], original_request["concept_ids"]
        )
        self.assertEqual([c["rank"] for c in r["candidates"]], [1, 2])

    def test_automatic_heading_available_without_llm_generation(self):
        r = self.run_adapter()
        self.assertEqual(r['candidates'][0]['review']['automatic_comparison']['kind'],'grammatical')
        self.assertIsNone(r['candidates'][1]['review']['automatic_comparison'])

    def test_changed_documentary_snapshot_blocks(self):
        with self.assertRaises(ContextError):
            self.run_adapter("b" * 64)


if __name__ == "__main__":
    main()

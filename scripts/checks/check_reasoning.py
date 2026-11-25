"""Run the focused reasoning suite without loading models or calling paid APIs."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PATTERNS = (
    "test_candidate_review_service.py",
    "test_candidate_comparison.py",
    "test_candidate_context.py",
    "test_published_attributes.py",
    "test_grounded_alignment.py",
    "test_assertion_comparison.py",
    "test_comparison_safety.py",
    "test_literal_assertions.py",
    "test_candidate_explanation.py",
    "test_explanation_constraints.py",
    "test_explanation_service.py",
    "test_explanation_attribution.py",
    "test_explanation_refinement.py",
    "test_explanation_budget.py",
    "test_expanded_explanations.py",
    "test_local_explanation_recovery.py",
    "test_manual_reasoning.py",
    "test_index_reasoning.py",
    "test_openai_explanation.py",
    "test_retrieval_configuration.py",
    "test_index_compatibility.py",
    "test_reranker_service.py",
    "test_retrieval_title_fragments.py",
    "test_shortlist_reranker.py",
)


def main():
    suite = unittest.TestSuite()
    for pattern in PATTERNS:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

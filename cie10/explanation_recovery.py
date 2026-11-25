"""Bounded final comparison when a small model cannot use the full context.

Only whole sources are selected. The caller still validates against the complete
original evidence and never turns this limited comparison into a selection.
"""
from .explanation_contract import comparison_anchors


def recovery_evidence(evidence, diagnostic):
    anchors = set(comparison_anchors(evidence, diagnostic))
    core = [item for item in evidence if item["id"] in anchors]
    optional = [item for item in evidence if item.get("role") in ("parent", "finding_site", "116676008")]
    priorities = {"parent": 0, "finding_site": 1, "116676008": 2}
    optional.sort(key=lambda item: priorities[item["role"]])
    # Three optional sources also fit the paragraph's bounded citation contract.
    selected = core + optional[:3]
    return selected, {"policy": "limited_terms_and_published_snomed_context_v1",
                      "included_evidence_ids": [item["id"] for item in selected],
                      "omitted_evidence_ids": [item["id"] for item in evidence if item not in selected],
                      "full_documentary_checks_retained": True,
                      "automatic_selection": False}

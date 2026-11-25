"""Precedence of restrictions from tabular sources, the manual and index.

This is the single place to inspect which restriction takes precedence."""

import re
from ..explanation_constraints import normalize, documentary_constraint
from ..literal_assertions import literal_constraint
from ..manual_reasoning import manual_constraint
from ..index_reasoning import index_constraint
from .safety import safety_constraint
from .assertion_comparison import assertion_constraint
from .grounded_alignment import grounded_constraint


def normalized_anatomy(text):
    return normalize(text)


def anatomical_exclusion(evidence):
    """Recognize only simple local anatomy exclusions with an explicit code target."""
    sites = [
        normalized_anatomy(item["text"])
        for item in evidence
        if item["type"] == "SNOMED" and item.get("role") == "finding_site"
    ]
    for item in evidence:
        if (
            item["type"] != "CIE10"
            or item.get("role") != "exclusion"
            or item.get("inherited") is not False
        ):
            continue
        # Lists, clinical qualifiers and conditions remain outside this narrow guard.
        match = re.fullmatch(
            r"([a-z ]+) \([a-z][0-9]{2}(?:\.[0-9-]+)?\)",
            normalized_anatomy(item["text"]),
        )
        if match and any(
            site == match[1] or site.endswith(" " + match[1]) for site in sites
        ):
            return item["id"]
    return None


def effective_constraint(evidence):
    # A confirmed local exclusion outranks a missing qualifier on that target.
    if anatomical_exclusion(evidence):
        return None
    structured = assertion_constraint(evidence)
    if structured:
        return structured
    grounded = grounded_constraint(evidence)
    if grounded:
        return grounded
    safety = safety_constraint(evidence)
    if safety:
        return safety
    literal = literal_constraint(evidence)
    if literal and literal["assessment"] == "incompatible":
        return literal
    base = documentary_constraint(evidence)
    if base and base["assessment"] == "incompatible":
        return base
    return manual_constraint(evidence) or index_constraint(evidence) or literal or base

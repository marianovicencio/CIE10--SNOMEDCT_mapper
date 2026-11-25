"""Compatibility imports for comparison safety; implementation lives in reasoning/.

Keep existing consumers working while exposing responsibilities in separate files.
See docs/code-organization.md for the reading order and limits of each component.
"""

from .reasoning.text import STOP, clean, absence, core
from .reasoning.safety import (
    HYPOTHETICAL,
    qualifier_conflict,
    scope_marker,
    safety_constraint,
)
from .reasoning.comparisons import literal_label_analysis, conservative_analysis

__all__ = [
    "STOP",
    "HYPOTHETICAL",
    "clean",
    "absence",
    "core",
    "qualifier_conflict",
    "scope_marker",
    "safety_constraint",
    "literal_label_analysis",
    "conservative_analysis",
]

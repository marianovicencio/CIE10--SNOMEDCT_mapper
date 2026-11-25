import unittest
from cie10.reasoning.assertions import extract_assertions, align
from cie10.reasoning.assertion_comparison import heading_conflict, assertion_constraint


def evidence(title, term, text=None):
    rows = [
        dict(id="t", type="CIE10", role="title", text=title),
        dict(
            id="s",
            type="SNOMED",
            role="candidate_term",
            concept_id="123456789",
            text=term,
        ),
    ]
    if text is not None:
        rows.append(dict(id="i", type="INPUT", text=text))
    return rows


class AssertionRepresentationTests(unittest.TestCase):
    def test_arbitrary_minimal_no_pairs_not_a_senility_dictionary(self):
        for term in [
            "senil",
            "bacteriana",
            "controlada",
            "inflamatoria",
            "hereditaria",
        ]:
            self.assertTrue(heading_conflict("Afección " + term, "Afección no " + term))
            self.assertTrue(heading_conflict("Afección no " + term, "Afección " + term))

    def test_preposition_features_are_independent_of_code(self):
        for feature in ["aura", "obstrucción", "hemorragia", "complicación"]:
            self.assertTrue(
                heading_conflict("Afección con " + feature, "Afección sin " + feature)
            )

    def test_unrelated_conditions_do_not_align(self):
        self.assertFalse(heading_conflict("Catarata senil", "Demencia no senil"))
        self.assertFalse(
            heading_conflict("Hernia con obstrucción", "Úlcera sin obstrucción")
        )

    def test_unknown_or_unspecified_is_not_absence(self):
        self.assertFalse(
            heading_conflict("Migraña, no especificada", "Migraña con aura")
        )
        self.assertFalse(
            heading_conflict("Migraña sin especificar", "Migraña con aura")
        )
        self.assertFalse(
            heading_conflict("Migraña sin mención de aura", "Migraña con aura")
        )

    def test_negation_qualifies_a_feature_not_the_whole_condition(self):
        frame = extract_assertions("Catarata no senil", "s")[0]
        self.assertEqual(frame.condition, ("catarata",))
        self.assertEqual(frame.feature, ("senil",))
        self.assertEqual(frame.value, "absent")

    def test_headings_are_definitions_not_patient_facts(self):
        self.assertEqual(
            extract_assertions("Migraña con aura", "s")[0].subject, "definition"
        )

    def test_positive_alternatives_are_not_both_asserted(self):
        self.assertFalse(
            heading_conflict(
                "Hernia con obstrucción o gangrena", "Hernia sin obstrucción"
            )
        )

    def test_coordinated_absences_preserve_each_feature(self):
        frames = extract_assertions("Úlcera sin hemorragia ni perforación", "t")
        self.assertEqual(
            {f.feature for f in frames}, {("hemorragia",), ("perforacion",)}
        )
        self.assertTrue(
            heading_conflict(
                "Úlcera sin hemorragia ni perforación", "Úlcera con hemorragia"
            )
        )

    def test_distinct_features_are_not_compared_as_one_axis(self):
        self.assertFalse(heading_conflict("Migraña con aura", "Migraña sin cefalea"))

    def test_unicode_feature_spans_refer_to_original_sources(self):
        text = "Úlcera gástrica sin hemorragia ni perforación"
        for f in extract_assertions(text, "t"):
            self.assertIn(text[f.span[0] : f.span[1]], ["hemorragia", "perforación"])
        pair = align(
            extract_assertions("Catarata senil", "t")[0],
            extract_assertions("Catarata no senil", "s")[0],
        )
        self.assertEqual("Catarata senil"[slice(*pair[0].span)], "senil")

    def test_uncertain_prefix_is_not_asserted_absence(self):
        f = extract_assertions("No se descarta migraña con aura", "i", True)[0]
        self.assertEqual(f.modality, "uncertain")

    def test_family_subject_is_preserved(self):
        f = extract_assertions("Su madre tiene migraña con aura", "i", True)[0]
        self.assertEqual(f.subject, "other")
        self.assertEqual(f.condition, ("migrana",))

    def test_hypothetical_scope_stops_before_consequence(self):
        f = extract_assertions(
            "Si el paciente tuviera migraña con aura, se evaluaría", "i", True
        )[0]
        self.assertEqual(f.modality, "hypothetical")
        self.assertEqual(f.feature, ("aura",))

    def test_unclear_confirmation_does_not_become_current_absence(self):
        f = extract_assertions("No hay psoriasis confirmada", "i", True)[0]
        self.assertEqual(f.modality, "uncertain")
        self.assertEqual(f.value, "unknown")


class AssertionDecisionTests(unittest.TestCase):
    def test_definitions_with_opposed_values_are_incompatible(self):
        r = assertion_constraint(evidence("Migraña con aura", "Migraña sin aura"))
        self.assertEqual(r["assessment"], "incompatible")
        self.assertEqual(r["rule_id"], "assertion_polarity_conflict")

    def test_real_input_conflict_is_not_lost(self):
        r = assertion_constraint(
            evidence(
                "Migraña sin aura", "Migraña sin aura", "Se confirma migraña con aura."
            )
        )
        self.assertEqual(r["assessment"], "incompatible")

    def test_hypothesis_and_relative_do_not_become_positive_facts(self):
        for text in [
            "Si el paciente tuviera migraña con aura, se evaluaría.",
            "Su madre tiene migraña con aura.",
            "No se descarta migraña con aura.",
        ]:
            r = assertion_constraint(
                evidence("Migraña sin aura", "Migraña sin aura", text)
            )
            self.assertEqual(r["assessment"], "undetermined")

    def test_conflicting_actual_input_statements_require_clarification(self):
        r = assertion_constraint(
            evidence(
                "Migraña con aura",
                "Migraña con aura",
                "Migraña con aura. Migraña sin aura.",
            )
        )
        self.assertEqual(r["assessment"], "undetermined")
        self.assertEqual(r["rule_id"], "assertion_contradictory_input")

    def test_negated_other_condition_does_not_change_target(self):
        self.assertIsNone(
            assertion_constraint(
                evidence("Psoriasis", "Psoriasis", "Se descarta fiebre. Psoriasis.")
            )
        )

    def test_compatible_values_never_auto_approve_a_mapping(self):
        self.assertIsNone(
            assertion_constraint(
                evidence("Migraña con aura", "Migraña con aura", "Migraña con aura.")
            )
        )

    def test_unspecified_source_does_not_disprove_specific_candidate(self):
        self.assertIsNone(
            assertion_constraint(
                evidence("Migraña no especificada", "Migraña con aura")
            )
        )

    def test_opposed_values_are_not_inferred_from_general_similarity(self):
        self.assertIsNone(
            assertion_constraint(evidence("Neumonía", "Neumonía bacteriana"))
        )

    def test_trace_contains_offsets_and_scope_not_copied_input(self):
        r = assertion_constraint(evidence("Migraña sin aura", "Migraña con aura"))
        self.assertIn("feature_span", r["comparison_trace"]["left"])
        self.assertNotIn("text", r["comparison_trace"]["left"])

    def test_generation_schema_cannot_approve_structural_contradiction(self):
        from cie10.explanation_contract import response_schema

        schema = response_schema(
            "123456789", None, evidence("Afección con rasgo", "Afección sin rasgo")
        )
        self.assertEqual(schema["properties"]["assessment"]["enum"], ["incompatible"])

    def test_model_is_not_called_for_new_qualifier_conflict(self):
        from cie10.candidate_explanation import explain_candidate

        e = evidence("Afección con rasgo", "Afección sin rasgo")
        r = explain_candidate(
            "123456789", None, e, transport=lambda _: self.fail("Model called")
        )
        self.assertEqual(r["analysis"]["assessment"], "incompatible")
        self.assertIn("comparison_trace", r)

    def test_official_same_concept_alias_aligns_alternative_wording(self):
        e = evidence(
            "Hernia diafragmática sin obstrucción", "Hernia diafragmática obstruida"
        )
        e.append(
            dict(
                id="alias",
                type="SNOMED",
                role="candidate_alias",
                concept_id="123456789",
                text="hernia diafragmática con obstrucción",
            )
        )
        r = assertion_constraint(e)
        self.assertEqual(r["assessment"], "incompatible")
        self.assertIn("alias", r["evidence_refs"])
        self.assertEqual(r["comparison_trace"]["right"]["source_id"], "alias")

    def test_description_of_another_concept_is_not_an_alias(self):
        e = evidence("Hernia sin obstrucción", "Hernia obstruida")
        e.append(
            dict(
                id="alias",
                type="SNOMED",
                role="candidate_alias",
                concept_id="999999999",
                text="hernia con obstrucción",
            )
        )
        self.assertIsNone(assertion_constraint(e))

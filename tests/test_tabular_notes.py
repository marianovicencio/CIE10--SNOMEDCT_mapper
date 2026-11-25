import unittest

from cie10.tabular_notes import logical_notes, reference_details, normalize_record_notes


def f(text, x=96, y=100, n=1, page=1):
    return {"text": text, "block_id": "example", "source": {
        "volume": 1, "source_file": "fixture.pdf", "source_sha256": "fixture",
        "pdf_page": page, "printed_page": None, "line_id": n,
        "bbox": [x, y, x + 40, y + 10], "column": None}}


CTX = {"code": "C75", "description": "Tumor maligno de otras glándulas endocrinas"}


class TabularNotesTests(unittest.TestCase):
    def test_long_same_margin_continuation_is_one_exclusion(self):
        first=f('síntomas, signos y hallazgos anormales clínicos y de laboratorio, no',96,100,1)
        first['source']['bbox'][2]=380
        leaves,issues=logical_notes([first,f('clasificados en otra parte (R00–R99)',96,111,2)],'exclusion',CTX,'explicit_label')
        self.assertEqual(len(leaves),1)
        self.assertIn('no clasificados en otra parte',leaves[0]['text'])
        self.assertEqual(len(leaves[0]['sources']),2)
        self.assertEqual(issues,[])

    def test_wrapped_colon_label_does_not_leave_a_partial_leaf(self):
        first=f('ciertas enfermedades o lesiones que complican el embarazo, el parto',48,100,1)
        first['source']['bbox'][2]=380
        leaves,issues=logical_notes([first,f('o el puerperio clasificadas en otra parte:',106,111,2),
            f('• tétanos obstétrico (A34)',96,123,3)],'exclusion',CTX,'explicit_label')
        self.assertEqual(len(leaves),1)
        self.assertIn('el parto o el puerperio clasificadas en otra parte tétanos',leaves[0]['text'])
        self.assertEqual(len(leaves[0]['sources']),3)
        self.assertEqual(issues,[])

    def test_outer_bullets_end_an_unbulleted_nested_label(self):
        leaves,issues=logical_notes([f('supervisión del embarazo:',96,100,1),
            f('• de alto riesgo (Z35.–)',106,112,2),f('• normal (Z34.–)',106,124,3),
            f('• tétanos obstétrico (A34)',96,136,4),
            f('• trastornos mentales (F53.–)',96,148,5)],'exclusion',CTX,'explicit_label')
        self.assertEqual([x['text'] for x in leaves],['supervisión del embarazo de alto riesgo (Z35.–)',
            'supervisión del embarazo normal (Z34.–)','tétanos obstétrico (A34)','trastornos mentales (F53.–)'])
        self.assertEqual(issues,[])

    def test_brace_members_do_not_inherit_the_preceding_unrelated_term(self):
        first=f('• Apoplejía† (I68.8*) ',96,112,2)
        first['starts_independent_brace_group']=True
        leaves,issues=logical_notes([f('Uremia crónica',96,100,1),
            first,f('urémica',160,118,3),
            f('• Demencia† (F02.8*)',96,124,4),f('',145,129,5)],'inclusion',CTX,'implicit_under_code_heading')
        self.assertEqual([x['text'] for x in leaves],['Uremia crónica','Apoplejía† (I68.8*) urémica','Demencia† (F02.8*) urémica'])
        self.assertEqual(issues,[])

    def test_brace_children_can_have_a_legitimate_preceding_root(self):
        leaves,issues=logical_notes([f('Quiste',96,100,1),
            f('• dermoide ',96,112,2),f('de la boca',160,118,3),
            f('• epidermoide',96,124,4),f('',145,129,5)],'inclusion',CTX,'implicit_under_code_heading')
        self.assertEqual([x['text'] for x in leaves],['Quiste','Quiste dermoide de la boca','Quiste epidermoide de la boca'])
        self.assertEqual(issues,[])

    def test_return_to_outer_margin_ends_wrap_not_new_term(self):
        first=f('síndromes adrenogenitales, virilizantes o feminizantes, ya sean',138,100,1)
        first['source']['bbox'][2]=380
        second=f('adquiridos o como consecuencia de hiperplasia suprarrenal',148,111,2)
        second['source']['bbox'][2]=380
        leaves,_=logical_notes([first,second,f('virilización (femenina)',138,122,3)],'inclusion',CTX,'implicit_under_code_heading')
        self.assertEqual(len(leaves),2)
        self.assertEqual(leaves[-1]['text'],'virilización (femenina)')

    def test_colon_prefix_stops_at_unbulleted_sibling(self):
        leaves, issues = logical_notes([
            f("glándula:", 96, 100, 1), f("• suprarrenal (C74.–)", 138, 112, 2),
            f("• tiroides (C73)", 138, 124, 3), f("ovario (C56)", 138, 136, 4),
        ], "exclusion", CTX, "explicit_label")
        self.assertEqual([e["text"] for e in leaves], ["glándula suprarrenal (C74.–)", "glándula tiroides (C73)", "ovario (C56)"])
        self.assertEqual(issues, [])
        self.assertEqual(len(leaves[0]["sources"]), 2)

    def test_nested_prefix_and_return_to_parent_level(self):
        leaves, issues = logical_notes([
            f("tumor maligno de:", 96, 100, 1),
            f("• vías genitourinarias SAI:", 138, 112, 2),
            f("• femeninas (C57.9)", 148, 124, 3),
            f("• masculinas (C63.9)", 148, 136, 4),
            f("• sitio no especificado (C80.-)", 138, 148, 5),
        ], "exclusion", CTX, "explicit_label")
        self.assertEqual(leaves[0]["text"], "tumor maligno de vías genitourinarias SAI femeninas (C57.9)")
        self.assertEqual(leaves[2]["text"], "tumor maligno de sitio no especificado (C80.-)")
        self.assertEqual(issues, [])

    def test_reference_on_wrapped_line_belongs_to_previous_leaf(self):
        leaves, issues = logical_notes([
            f("tumor maligno de:", 96, 100, 1),
            f("• tejido linfático, hematopoyético y de tejidos afines", 138, 112, 2),
            f("(C81–C96)", 148, 124, 3), f("• sitio no especificado (C80.-)", 138, 136, 4),
        ], "exclusion", CTX, "explicit_label")
        self.assertEqual(len(leaves), 2)
        self.assertTrue(leaves[0]["text"].endswith("(C81–C96)"))
        self.assertEqual(issues, [])

    def test_complete_brace_shares_qualifier_and_reference(self):
        leaves, issues = logical_notes([
            f("", 96, 265, 13), f("Cálices ", 96, 276, 14),
            f("renal(es) (C65)", 155, 281, 15), f("", 139, 284, 16),
            f("Pelvis", 96, 288, 17), f("", 139, 291, 18),
        ], "exclusion", CTX, "explicit_label")
        self.assertEqual([e["text"] for e in leaves], ["Cálices renal(es) (C65)", "Pelvis renal(es) (C65)"])
        self.assertEqual(issues, [])
        self.assertTrue(all(e["references"][0]["raw"] == "C65" for e in leaves))
        self.assertEqual(leaves[0]["composition"], "brace_shared_qualifier")

    def test_incomplete_brace_is_one_unresolved_group_not_independent_terms(self):
        leaves, issues = logical_notes([f("Cálices "), f("renal(es) (C65)",155,112,2)], "exclusion", CTX, "explicit_label")
        self.assertEqual(leaves, [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(len(issues[0]["fragments"]), 2)

    def test_hyphen_reference_has_different_review_semantics_by_polarity(self):
        for dash in ["-", "–", "—"]:
            exclusion = reference_details(f"C74.{dash}", "exclusion")[0]
            inclusion = reference_details(f"C74.{dash}", "inclusion")[0]
            self.assertEqual(exclusion["category"], "C74")
            self.assertEqual(exclusion["scope"], "all_subcategories")
            self.assertFalse(exclusion["usable_as_final_code"])
            self.assertFalse(exclusion["requires_specificity_review"])
            self.assertTrue(inclusion["requires_specificity_review"])

    def test_unlabelled_terms_become_contextual_inclusions(self):
        original = [f("Mejilla SAI", n=1), f("Nariz SAI", y=112, n=2)]
        record = {"kind": "code", "code": "C76.0", "description": "Tumor maligno de la cabeza, cara y cuello",
                  "inclusions": [], "exclusions": [], "instructions": [], "notes": [], "unclassified": original, "warnings": []}
        record = normalize_record_notes(record)
        self.assertEqual([e["text"] for e in record["inclusions"]], ["Mejilla SAI", "Nariz SAI"])
        self.assertEqual(record["unclassified"], [])
        self.assertEqual(record["raw_note_fragments"]["unclassified"], original)
        self.assertEqual(record["inclusions"][0]["classification_context"]["code"], "C76.0")
        self.assertEqual(record["inclusions"][0]["qualifiers"][0]["meaning"], "sin otra indicación")

    def test_glossary_and_editorial_note_are_not_promoted(self):
        for text in ["Se caracteriza por episodios recurrentes", "[Ver nota 5 al inicio de este capítulo]"]:
            record = {"kind": "code", "code": "F00", "description": "Ejemplo",
                      "inclusions": [], "exclusions": [], "instructions": [], "notes": [], "unclassified": [f(text)], "warnings": []}
            result = normalize_record_notes(record)
            self.assertEqual(result["inclusions"], [])
            self.assertEqual(len(result["unclassified"]), 1)

    def test_dangling_prefix_is_not_a_complete_exclusion(self):
        leaves, issues = logical_notes([f("glándula:")], "exclusion", CTX, "explicit_label")
        self.assertEqual(leaves, [])
        self.assertEqual(issues[0]["reason"], "prefix_without_resolved_children")

    def test_new_explicit_block_cannot_inherit_previous_prefix(self):
        other = f("ovario (C56)",138,124,3)
        other["block_id"] = "second"
        leaves, _ = logical_notes([f("glándula:"), f("• tiroides (C73)",138,112,2), other], "exclusion", CTX, "explicit_label")
        self.assertEqual(leaves[-1]["text"], "ovario (C56)")

    def test_indent_after_explicit_label_does_not_merge_complete_exclusions(self):
        leaves, _ = logical_notes([f("glándula tiroides (C73)",96,100,1), f("ovario (C56)",138,112,2)], "exclusion", CTX, "explicit_label")
        self.assertEqual([e["text"] for e in leaves], ["glándula tiroides (C73)", "ovario (C56)"])


if __name__ == "__main__":
    unittest.main()

import unittest

from cie10.common import code_references, page_numbers
from cie10.extract import is_visible, is_watermark, normalize_page_record
from cie10.parse import parse_index, parse_tabular


def page(number, entries, volume=1):
    return {"volume": volume, "source_file": "fixture.pdf", "source_sha256": "test",
            "pdf_page": number, "printed_page": str(number), "lines": [
                {"id": i, "text": text, "start_bold": bold,
                 "start_font": "Helvetica-Bold" if bold else "Times-Roman",
                 "start_size": 10, "max_size": 10, "column": None,
                 "bbox": [48, 70 + 12 * i, 380, 80 + 12 * i]}
                for i, (text, bold) in enumerate(entries, 1)]}


class StructureTests(unittest.TestCase):
    def test_exclusion_not_promoted_to_synonym_or_child(self):
        records = parse_tabular([page(495, [
            ("J18 Neumonía, organismo no especificado", True),
            ("Excluye: absceso del pulmón con neumonía (J85.1)", False),
            ("neumonía por aspiración (J69.0)", False),
            ("J18.9 Neumonía, no especificada", True),
        ])])
        self.assertEqual(len(records), 2)
        self.assertEqual(len(records[0]["exclusions"]), 2)
        self.assertEqual(records[0]["inclusions"], [])
        self.assertEqual(records[1]["exclusions"], [])
        self.assertEqual(records[1]["parent_code"], "J18")

    def test_code_mention_in_prose_is_not_a_new_heading(self):
        records = parse_tabular([page(1, [("A00 Cólera", True), ("A01 se utiliza en otra situación", False)])])
        self.assertEqual([r.get("code") for r in records], ["A00"])

    def test_dagger_and_multiline_title(self):
        records = parse_tabular([page(1, [("A17.0† Meningitis", True), ("tuberculosa", True)])])
        self.assertEqual(records[0]["code"], "A17.0")
        self.assertEqual(records[0]["symbol"], "†")
        self.assertEqual(records[0]["description"], "Meningitis tuberculosa")

    def test_notes_continue_on_next_page(self):
        records = parse_tabular([page(1, [("A00 Cólera", True), ("Excluye: condición", False)]),
                                 page(2, [("con modificador adicional", False), ("A01 Otra", True)])])
        self.assertEqual(len(records[0]["exclusions"]), 2)

    def test_noncontiguous_pages_reset_context(self):
        records = parse_tabular([page(1, [("A00 Cólera", True), ("Excluye: otra", False)]),
                                 page(5, [("Fragmento de otra página", False)])])
        self.assertEqual(records[1]["kind"], "unassigned_tabular_block")
        self.assertEqual(records[1]["exclusions"], [])

    def test_ranges_unspecified_and_dual_codes_preserved(self):
        self.assertEqual(code_references("A00–A09, O98.–; A17.0† G01*"), ["A00–A09", "O98.–", "A17.0†", "G01*"])

    def test_index_modifier_keeps_ancestry_and_cross_reference(self):
        records = parse_index([page(13, [("Abdomen – ver también estado patológico", True),
                                        ("– agudo R10.0", False), ("– en péndulo", False),
                                        ("– – afecta al feto P03.8", False)], 3)], "diseases")
        self.assertEqual(records[1]["code_references"], ["R10.0"])
        self.assertEqual(len(records[3]["ancestors"]), 2)
        self.assertTrue(records[0]["has_cross_reference"])
        self.assertFalse(records[1]["usable_as_synonym"])

    def test_wrapped_index_code_attaches_to_term(self):
        records = parse_index([page(13, [("Aarskog, enfermedad o síndrome de", True), ("Q87.1", False)], 3)], "diseases")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["code_references"], ["Q87.1"])

    def test_off_page_text_excluded_but_visible_text_kept(self):
        self.assertFalse(is_visible({"x0": -100, "x1": -50, "top": 30, "bottom": 40}, (0, 0, 400, 630)))
        self.assertTrue(is_visible({"x0": 30, "x1": 60, "top": 30, "bottom": 40}, (0, 0, 400, 630)))

    def test_watermark_filter_does_not_remove_normal_italic(self):
        self.assertTrue(is_watermark({"fontname": "BookAntiqua,Italic", "size": 35}))
        self.assertFalse(is_watermark({"fontname": "Times-Italic", "size": 10.5}))

    def test_page_ranges_validate_and_deduplicate(self):
        self.assertEqual(page_numbers("2-4,3,7", 10), [2, 3, 4, 7])
        for invalid in ["0", "4-2", "11", "2x"]:
            with self.assertRaises(ValueError):
                page_numbers(invalid, 10)

    def test_offset_code_and_title_are_joined_before_parsing(self):
        raw = page(493, [("J15.3 Neumonía anterior", True),
                         ("Neumonía debida a otros estreptococos", True), ("J15.4", True)])
        raw["crop_bbox"] = [15, 26, 416, 657]
        raw["lines"][1]["bbox"] = [96, 322.67, 286, 332.67]
        raw["lines"][2]["bbox"] = [48, 326.06, 73, 336.06]
        fixed = normalize_page_record(raw)
        result = parse_tabular([fixed])
        self.assertEqual(result[1]["description"], "Neumonía debida a otros estreptococos")
        self.assertEqual(len(fixed["layout_lines"]), 3)
        self.assertEqual(len(fixed["lines"]), 2)
        self.assertEqual(normalize_page_record(fixed), fixed)

    def test_volume2_certificate_part_number_is_not_removed_as_footer(self):
        raw = page(121, [("2", False), ("110", False)], volume=2)
        raw["printed_page"] = None
        raw["crop_bbox"] = [0, 0, 400, 629]
        raw["lines"][0]["bbox"] = [91, 592, 97, 603]
        raw["lines"][1]["bbox"] = [28, 605, 46, 618]
        fixed = normalize_page_record(raw)
        self.assertEqual(fixed["printed_page"], "110")
        self.assertEqual([line["text"] for line in fixed["lines"]], ["2"])

    def test_footer_is_pagination_not_clinical_content(self):
        raw = page(495, [("J18.9 Neumonía, no especificada", True), ("490", False)])
        raw["printed_page"] = None
        raw["crop_bbox"] = [15, 26, 416, 657]
        raw["lines"][1]["bbox"] = [48, 630, 66, 641]
        fixed = normalize_page_record(raw)
        self.assertEqual(fixed["printed_page"], "490")
        self.assertEqual(len(fixed["lines"]), 1)


if __name__ == "__main__":
    unittest.main()

"""Regression samples from the 2018 volume 3 tables and remission rules."""

import unittest

from cie10.common import ROOT, read_json
from cie10.processing.extract import normalize_page_record
from cie10.processing.parse import without_special_layout
from cie10.processing.volume3.volume3_special import (
    parse_abortion_table,
    parse_neoplasm_table,
    parse_transport_matrix,
    parse_drug_table,
    resolve_remissions,
)


def fixture(term, path, ident):
    return {"id": ident, "kind": "index_entry", "term_path": path,
            "term_fragment": path[-1], "text": term, "warnings": [], "sources": [],
            "has_cross_reference": "ver" in term}


class RemissionTests(unittest.TestCase):
    def test_exact_target_is_documentary_only(self):
        target = fixture("Ajenjo T62.2", ["Ajenjo"], "target")
        source = fixture("Absintio – ver Ajenjo", ["Absintio"], "source")
        edge = resolve_remissions([source, target])[0]
        self.assertEqual(edge["target_id"], "target")
        self.assertEqual(edge["resolution"], "resolved_exact")
        self.assertFalse(edge["implies_clinical_equivalence"])
        self.assertNotIn("code_references", source)

    def test_ambiguous_target_is_not_forced(self):
        source = fixture("Raíz – ver Ajenjo", ["Raíz"], "source")
        targets = [fixture("Ajenjo", ["Ajenjo"], f"target-{n}") for n in (1, 2)]
        edge = resolve_remissions([source] + targets)[0]
        self.assertIsNone(edge["target_id"])
        self.assertEqual(edge["resolution"], "ambiguous")

    def test_category_reference_preserves_its_expression(self):
        source = fixture("Aborto actual – ver Categorías O03–O06", ["Aborto", "actual"], "source")
        edge = resolve_remissions([source])[0]
        self.assertEqual(edge["target_kind"], "code_expression")
        self.assertEqual(edge["target_code_expressions"], ["O03–O06"])
        self.assertIsNone(edge["target_id"])


@unittest.skipUnless((ROOT / "data/interim/full/vol3/page_0014.json").is_file()
                     and (ROOT / "data/raw/CIE-10_2018_VOL3.pdf").is_file(),
                     "Full volume 3 cache and source PDF are unavailable")
class Volume3SpecialPDFTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = ROOT / "data/interim/full/vol3"
        cls.source = ROOT / "data/raw/CIE-10_2018_VOL3.pdf"

    @classmethod
    def page(cls, number):
        return normalize_page_record(read_json(cls.folder / f"page_{number:04d}.json"))

    def test_abortion_suffixes_keep_the_column_context(self):
        rows = parse_abortion_table([self.page(14), self.page(15)], self.source)
        abscess = next(r for r in rows if r["term_fragment"].startswith("absceso genital"))
        self.assertEqual(abscess["cells"]["o03_o06_complete_or_unspecified"]["text"], ".5")
        self.assertEqual(abscess["cells"]["o03_o06_incomplete"]["text"], ".0")
        self.assertEqual(abscess["cells"]["o08_subsequent_complication"]["code_family"], "O08")
        self.assertEqual(abscess["cells"]["o03_o06_complete_or_unspecified"]["category_scope"],
                         ["O03", "O04", "O05", "O06"])
        self.assertEqual(abscess["term_path"], ["Aborto", "complicado (por)",
                                               "absceso genital, peritoneo, peritoneal"])

    def test_neoplasm_cells_and_blank_in_situ(self):
        rows = parse_neoplasm_table([self.page(544), self.page(555)], self.source)
        site = next(r for r in rows if r["id"] == "v3-p555-table-y1030")
        self.assertEqual(site["cells"]["malignant_primary"]["text"], "C63.7")
        self.assertEqual(site["cells"]["uncertain_or_unknown_behavior"]["text"], "D40.7")
        acromion = next(r for r in rows if r["term_fragment"] == "acromion (apófisis)")
        self.assertIsNone(acromion["cells"]["in_situ"])

    def test_rotated_transport_matrix_keeps_missing_cell(self):
        rows = parse_transport_matrix([self.page(605)], self.source)
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0]["columns"]["pedal_cycle"], "V01.–")
        self.assertIsNone(rows[0]["columns"]["noncollision_accident"])
        self.assertEqual(rows[1]["columns"]["noncollision_accident"], "V18.–")
        self.assertFalse(rows[0]["warnings"])

    def test_drug_header_is_not_a_substance_and_see_is_not_a_code(self):
        rows = parse_drug_table([self.page(654), self.page(655)])
        self.assertFalse(any(r["term_fragment"] == "Sustancia" for r in rows))
        absintio = next(r for r in rows if r["term_fragment"].startswith("Absintio"))
        self.assertFalse(any(absintio["codes_by_context"].values()))
        self.assertEqual(absintio["code_references"], [])

    def test_special_layout_is_not_read_as_two_column_index(self):
        self.assertFalse(without_special_layout(self.page(544))["lines"])
        self.assertFalse(without_special_layout(self.page(605))["lines"])
        self.assertTrue(without_special_layout(self.page(581))["lines"])


if __name__ == "__main__":
    unittest.main()

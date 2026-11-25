"""Volume 3 line wraps and explicit page-continuation regression checks."""

import unittest

from cie10.common import ROOT, read_json
from cie10.processing.extract import normalize_page_record
from cie10.processing.parse import parse_index


def fixture_page(number, entries, section="diseases"):
    lines = []
    for index, (text, bold, x) in enumerate(entries, 1):
        top = 70 + (index - 1) * 9.2
        lines.append({
            "id": index, "text": text, "start_bold": bold,
            "start_font": "Times-Bold" if bold else "Times-Roman",
            "start_size": 8, "max_size": 8, "column": "left",
            "bbox": [x, top, x + 120, top + 8],
        })
    return {
        "volume": 3, "source_file": "fixture.pdf", "source_sha256": "test",
        "pdf_page": number, "printed_page": str(number - 4), "lines": lines,
    }


class Volume3ContinuationTests(unittest.TestCase):
    def test_bold_wrapped_main_term_keeps_its_code_and_sibling(self):
        page = fixture_page(13, [
            ("Abeja, picadura de (con choque alérgico o", True, 28),
            ("anafiláctico) T63.4", True, 35),
            ("Aberración, aberrante", True, 28),
            ("– mental F79.–", False, 28),
        ])
        rows = parse_index([page], "diseases")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["code_references"], ["T63.4"])
        self.assertEqual(len(rows[0]["sources"]), 2)
        self.assertIn("anafiláctico", rows[0]["term_fragment"])
        self.assertEqual(rows[2]["ancestors"], ["Aberración, aberrante"])

    def test_indented_ver_line_does_not_replace_the_parent(self):
        page = fixture_page(17, [
            ("Absceso", True, 28),
            ("– genital (órgano o tracto)", False, 28),
            ("– – femenino", False, 28),
            ("– – – en aborto o embarazo ectópico o molar", False, 28),
            ("– ver Aborto, complicado", False, 50),
            ("– – masculino N49.9", False, 28),
        ])
        rows = parse_index([page], "diseases")
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[3]["depth"], 3)
        self.assertTrue(rows[3]["has_cross_reference"])
        self.assertEqual(len(rows[3]["sources"]), 2)
        self.assertEqual(rows[4]["ancestors"], ["Absceso", "genital (órgano o tracto)"])
        self.assertNotIn("missing_ancestor", rows[4]["warnings"])

    def test_page_heading_links_to_original_entry(self):
        first = fixture_page(171, [
            ("Diabetes, diabético(a) (mellitus) E14.–", True, 28),
            ("– insulinodependiente E10.–", False, 28),
        ])
        second = fixture_page(172, [
            ("Diabetes", True, 28),
            ("— continuación", False, 35),
            ("– insulinodependiente — continuación", False, 28),
            ("– – en el embarazo O24.0", False, 28),
        ])
        rows = parse_index([first, second], "diseases")
        self.assertEqual(rows[2]["term_fragment"], "Diabetes")
        self.assertEqual(rows[2]["continuation_of"], rows[0]["id"])
        self.assertEqual(rows[3]["continuation_of"], rows[1]["id"])
        self.assertEqual(rows[4]["ancestors"], ["Diabetes", "insulinodependiente"])

    def test_separate_continuation_marker_joins_even_after_a_code(self):
        first = fixture_page(20, [("Síndrome X A00", True, 28)])
        second = fixture_page(21, [
            ("Síndrome X A00", True, 28),
            ("— continuación", False, 35),
        ])
        rows = parse_index([first, second], "diseases")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["continuation_of"], rows[0]["id"])


@unittest.skipUnless((ROOT / "data/interim/full/vol3/page_0013.json").is_file(),
                     "Full Volume 3 page cache is unavailable")
class Volume3PDFContinuationTests(unittest.TestCase):
    def source_page(self, number):
        path = ROOT / "data/interim/full/vol3" / f"page_{number:04d}.json"
        return normalize_page_record(read_json(path))

    def test_actual_bee_and_external_cause_wraps(self):
        disease = parse_index([self.source_page(13)], "diseases")
        bee = next(r for r in disease if r["id"] == "v3-p13-l15")
        self.assertEqual(bee["code_references"], ["T63.4"])
        self.assertEqual([s["line_id"] for s in bee["sources"]], [15, 16])
        self.assertFalse(any(r["id"] == "v3-p13-l16" for r in disease))
        external = parse_index([self.source_page(599)], "external_causes")
        abandonment = next(r for r in external if r["id"] == "v3-p599-l1")
        self.assertEqual(abandonment["code_references"], ["Y06.9"])
        self.assertEqual([s["line_id"] for s in abandonment["sources"]], [1, 2, 3])

    def test_actual_abscess_continuation_and_parentage(self):
        rows = parse_index([self.source_page(n) for n in (15, 16, 17)], "diseases")
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["v3-p17-l1"]["continuation_of"], "v3-p15-l31")
        self.assertEqual(by_id["v3-p17-l4"]["depth"], 3)
        self.assertEqual([s["line_id"] for s in by_id["v3-p17-l4"]["sources"][:2]], [4, 5])
        self.assertEqual(by_id["v3-p17-l8"]["ancestors"][-1], "genital (órgano o tracto)")

    def test_actual_diabetes_page_continuation(self):
        rows = parse_index([self.source_page(n) for n in (171, 172)], "diseases")
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["v3-p172-l1"]["continuation_of"], "v3-p171-l64")
        self.assertEqual(by_id["v3-p171-l45"]["code_references"], ["H53.5"])
        self.assertEqual([s["line_id"] for s in by_id["v3-p171-l45"]["sources"]], [45, 46])

    def test_table_margin_and_complete_reference_do_not_force_a_join(self):
        abortion = parse_index([self.source_page(15)], "diseases")
        by_id = {r["id"]: r for r in abortion}
        self.assertEqual([s["line_id"] for s in by_id["v3-p15-l6"]["sources"]], [6])
        self.assertEqual(by_id["v3-p15-l7"]["depth"], 1)
        self.assertEqual(by_id["v3-p15-l8"]["depth"], 2)
        forearm = parse_index([self.source_page(75)], "diseases")
        by_id = {r["id"]: r for r in forearm}
        self.assertEqual([s["line_id"] for s in by_id["v3-p75-l110"]["sources"]], [110])

    def test_prose_word_continuacion_is_not_a_page_marker(self):
        rows = parse_index([self.source_page(24)], "diseases")
        note = next(r for r in rows if r["kind"] == "index_note")
        self.assertIn("a continuación", note["term_fragment"])
        self.assertFalse(note["is_continuation"])
        self.assertEqual(note['scope_anchor_id'], 'v3-p24-l3')


if __name__ == "__main__":
    unittest.main()

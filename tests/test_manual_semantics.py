import unittest

from cie10.manual_semantics import annex_code_candidates, enrich_manual_passages, manual_scope, underlying_cause_candidates, association_blocks
from cie10.manual_layout import attach_bold_outcomes, attach_rule_clauses, diabetes_sequence_candidates
from cie10.common import ROOT, read_json
from cie10.extract import normalize_page_record
from cie10.parse import parse_manual


def page(number, lines):
    return {
        "volume": 2, "source_file": "volume2.pdf", "source_sha256": "fixture",
        "pdf_page": number, "printed_page": str(number - 11),
        "lines": [
            {"id": i, "text": text, "start_font": "ArialMT" if text[:1].isdigit() else "TimesNewRomanPSMT",
             "start_size": 11, "column": None, "bbox": [x, 50 + 12 * i, 380, 60 + 12 * i]}
            for i, (x, text) in enumerate(lines, 1)
        ],
    }


class ManualSemanticsTests(unittest.TestCase):
    def test_scope_separates_mortality_perinatal_and_morbidity(self):
        self.assertEqual(manual_scope({"number": "4.2.5"}), "mortality")
        self.assertEqual(manual_scope({"number": "4.4.5"}), "perinatal_mortality")
        self.assertEqual(manual_scope({"number": "4.5.4"}), "morbidity")

    def test_mention_is_not_a_verified_rule(self):
        records = parse_manual([page(84, [
            (28, "4.2.5 Instrucciones especiales"),
            (28, "A15-A19 Tuberculosis"),
            (85, "Con mención de: B20-B24, codifique en B20.0"),
        ])])
        enriched = enrich_manual_passages(records)
        self.assertEqual(enriched[0]["scope"], "mortality")
        self.assertFalse(enriched[0]["executable_rule"])
        self.assertIn("bold_outcome_requires_visual_review", enriched[0]["warnings"])
        self.assertTrue(all(not m["applicability_verified"] for m in enriched[0]["code_mentions"]))

    def test_annex_lists_preserve_their_distinct_meanings(self):
        pages = [
            page(244, [(28, "7.3 Lista de afecciones mal definidas"),
                       (32, "I46.9 Paro cardíaco, no especificado")]),
            page(245, [(28, "7.4 Lista de afecciones poco probables de provocar la muerte"),
                       (32, "A31.1 Infección cutánea por micobacterias")]),
            page(260, [(28, "7.7 Clasificación de prioridad"),
                       (32, "S00.0–S00.9 6 S07.0 5")]),
            page(266, [(28, "7.8.1 Lista de categorías en mujeres"),
                       (54, "A34 D07.3 M80.1 N76.8")]),
            page(272, [(28, "7.8.2 Lista de categorías en hombres"),
                       (54, "B26.0 I86.1")]),
        ]
        facts = annex_code_candidates(pages)
        by_code = {f["code_expression"]: f for f in facts}
        self.assertEqual(by_code["I46.9"]["relation"], "ill_defined_for_mortality_selection")
        self.assertEqual(by_code["A31.1"]["relation"], "unlikely_to_cause_death")
        self.assertEqual(by_code["S00.0–S00.9"]["priority"], 6)
        self.assertEqual(by_code["S07.0"]["priority"], 5)
        self.assertEqual(by_code["A34"]["sex"], "female")
        self.assertFalse(by_code["A34"]["hard_exclusion"])
        self.assertEqual(by_code["B26.0"]["sex"], "male")
        self.assertTrue(all(f["review_status"] == "pending" for f in facts))

    def test_underlying_cause_restrictions_keep_conditions_and_alternatives(self):
        pages = [
            page(119, [(28, "4.2.5 Instrucciones especiales"),
                       (57, "Códigos que no se deben utilizar para la codificación de la causa básica de"),
                       (28, "B95.0-B95.5 (codifique en A49.1)"),
                       (28, "E89.-"),
                       (28, "I15.1 (codifique en N28.9 si no se conoce)")]),
            page(120, [(57, "Códigos que no se deben utilizar para la codificación de la causa básica de"),
                       (57, "defunción (código para la enfermedad infecciosa de origen"),
                       (28, "U84.1 (codifique en B49)")]),
            page(121, [(62, "Códigos que no se deben utilizar si se conoce la causa básica que los origina"),
                       (28, "F03-F09"),
                       (28, "F17.- No debe usarse si se conoce la causa resultante"),
                       (28, "P07.-"),
                       (28, "P08.-"),
                       (28, "4.2.6 Otra sección")]),
        ]
        facts = underlying_cause_candidates(pages)
        by_code = {f["code_expression"]: f for f in facts}
        self.assertEqual(by_code["B95.0-B95.5"]["recode_candidates"], ["A49.1"])
        self.assertEqual(by_code["E89.-"]["fallback_if_no_indicated_code"], "R99")
        self.assertEqual(by_code["U84.1"]["condition"], "infectious_origin_preferred")
        self.assertEqual(by_code["F03-F09"]["condition"], "if_origin_known")
        self.assertEqual(by_code["F03-F09"]["relation"], "not_for_underlying_cause_when_origin_known")
        self.assertEqual(by_code["I15.1"]["recode_condition"], "if_origin_unknown")
        self.assertEqual(by_code["F17.-"]["condition"], "if_resultant_condition_known")
        self.assertEqual(by_code["P07.-"]["condition"], "if_other_perinatal_cause_reported")
        self.assertEqual(by_code["P08.-"]["exceptions"],
                         ["only_reported_cause", "other_cause_is_P28.5"])

    def test_association_blocks_keep_subjects_without_claiming_outcomes(self):
        pages = [
            page(83, [(28, "4.2.5 Instrucciones especiales sobre asociaciones")]),
            page(84, [(28, "A15-A19 Tuberculosis"),
                      (85, "Con mención de:"),
                      (85, "B20-B24 (VIH), codifique en B20.0 o B20.7"),
                      (28, "A15.- Tuberculosis respiratoria, o"),
                      (85, "histológicamente, o"),
                      (28, "A16.- Tuberculosis respiratoria"),
                      (85, "Con mención de:"),
                      (85, "J60-J64, codifique en J65")]),
        ]
        blocks = association_blocks(pages)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["subject_code_expressions"], ["A15-A19"])
        self.assertEqual(blocks[1]["subject_code_expressions"], ["A15.-", "A16.-"])
        self.assertIn("B20.0", blocks[0]["code_mentions"])
        self.assertFalse(blocks[0]["executable_rule"])
        self.assertIn("bold_outcome_requires_visual_review", blocks[0]["warnings"])

    def test_difficult_two_column_table_is_not_flattened_into_facts(self):
        pages = [page(259, [(28, "7.6 Lista de afecciones que pueden provocar diabetes"),
                            (158, "E12 E40–E46 Y41.5")])]
        self.assertEqual(annex_code_candidates(pages), [])


@unittest.skipUnless((ROOT / "data/interim/full/vol2/page_0083.json").is_file() and (ROOT / "data/interim/full/vol2/page_0258.json").is_file(), "Requiere la extracción local del volumen 2")
class ActualManualLayoutTests(unittest.TestCase):
    @staticmethod
    def cached_pages(numbers):
        base = ROOT / "data" / "interim" / "full" / "vol2"
        return [normalize_page_record(read_json(base / f"page_{n:04d}.json")) for n in numbers]

    def test_visual_review_cases_keep_subjects_and_bold_outcomes(self):
        pages = self.cached_pages(range(83, 122))
        blocks = association_blocks(pages)
        pdf = ROOT / "data" / "raw" / "CIE-10_2018_VOL2.pdf"
        attach_rule_clauses(attach_bold_outcomes(blocks, pages, pdf))
        def get(subject):
            return next(b for b in blocks if subject in b["subject_code_expressions"])
        self.assertEqual(get("B25.0†")["subject_code_expressions"],
                         ["B25.0†", "B25.2†", "B25.8", "B25.9"])
        self.assertEqual({x["code_expression"] for x in get("B58.-")["outcome_mentions"]},
                         {"B20.7", "B20.8", "B22.7"})
        self.assertIn("D50-D89", get("D50-D89")["subject_code_expressions"])
        for subject, expected in (("E10-E14", "E10–E14"),
                                  ("I70.-", "I42.0–I42.2"),
                                  ("K72.-", "K70.0–K70.4"),
                                  ("Q44.6", "Q61.1–Q61.3")):
            joined = [o for o in get(subject)["outcome_mentions"]
                      if o["code_expression"] == expected]
            self.assertTrue(joined)
            self.assertTrue(all(len(o["source_fragments"]) == 2 for o in joined))
        self.assertIn("O35.4", {x["code_expression"] for x in get("F10.-")["outcome_mentions"]})
        self.assertEqual(get("G40.6")["subject_code_expressions"], ["G40.6", "G40.7"])
        self.assertEqual(get("I05.8")["subject_code_expressions"], ["I05.8", "I05.9"])
        self.assertEqual(len(get("I44.-")["subject_code_expressions"]), 8)
        self.assertIn("antecedent_cause_of", get("L89.-")["trigger_types"])
        self.assertIn("reported_as_cause_of", get("I60-I69")["trigger_types"])
        self.assertEqual(next(r for r in get("I60-I69")["condition_rows"]
                              if "F01-F03" in r["condition_code_expressions"])["trigger_type"],
                         "reported_as_cause_of")
        self.assertEqual(next(r for r in get("I67.2")["condition_rows"]
                              if "F03" in r["condition_code_expressions"])["trigger_type"],
                         "reported_as_cause_of")
        a15_rows = get("A15-A19")["condition_rows"]
        self.assertEqual([r["condition_code_expressions"] for r in a15_rows],
                         [["B20-B24"], ["R75"]])
        self.assertEqual({o["code_expression"] for o in a15_rows[0]["outcome_mentions"]},
                         {"B20.0", "B20.7", "B22.7"})
        f10_o35 = [r for r in get("F10.-")["condition_rows"]
                   if "O35.4" in r["condition_code_expressions"]]
        self.assertEqual(len(f10_o35), 1)
        self.assertEqual({o["code_expression"] for o in f10_o35[0]["outcome_mentions"]},
                         {"O35.4"})
        a00_exception = [r for r in get("A00-B99")["condition_rows"]
                         if r["row_type"] == "exception"]
        self.assertEqual(len(a00_exception), 1)
        self.assertEqual(a00_exception[0]["exception_for_condition_code_expressions"],
                         ["C00-C97"])
        self.assertEqual({o["code_expression"] for o in a00_exception[0]["outcome_mentions"]},
                         {"B21.-", "B22.7"})
        i70_rows = get("I70.-")["condition_rows"]
        i42_codes = ["I42.0", "I42.1", "I42.2", "I42.8", "I42.9"]
        grouped = [r for r in i70_rows if r["condition_code_expressions"] == i42_codes]
        self.assertEqual(len(grouped), 1)
        self.assertEqual([o["code_expression"] for o in grouped[0]["outcome_mentions"]],
                         ["I25.5"])
        exception = [r for r in i70_rows if r["row_type"] == "exception"]
        self.assertEqual(len(exception), 1)
        self.assertEqual(exception[0]["exception_for_condition_code_expressions"], i42_codes)
        self.assertEqual({o["code_expression"] for o in exception[0]["outcome_mentions"]},
                         {"I42.0–I42.2", "I42.8-I42.9"})
        for subject, condition, destination in (
            ("E40-E46", "E14.-", "E12.-"),
            ("I10-I15", "I71.-", "I71.-"),
            ("E10-E14", "L97", "E10-E14"),
            ("E10-E14", "I70.0", "E10-E14"),
        ):
            row = next(r for r in get(subject)["condition_rows"]
                       if condition in r["condition_code_expressions"])
            self.assertEqual([(o["code_expression"], o["role"])
                              for o in row["outcome_mentions"]],
                             [(destination, "printed_explicit_destination_candidate")])
            self.assertIn("destination_not_bold_in_source", row["warnings"])
        self.assertEqual(next(r for r in get("E10-E14")["condition_rows"]
                              if "L97" in r["condition_code_expressions"])["fourth_character_literal"],
                         ".5")
        self.assertEqual(next(r for r in get("E10-E14")["condition_rows"]
                              if "I70.0" in r["condition_code_expressions"])["fourth_character_literal"],
                         ".6")
        self.assertTrue(all(r["outcome_mentions"] for b in blocks for r in b["condition_rows"]
                            if r['row_type'] in ('condition', 'exception', 'combination')))
        self.assertTrue(all(not b["executable_rule"] for b in blocks))

    def test_diabetes_cells_preserve_columns_and_continuations(self):
        pages = self.cached_pages((258, 259, 260))
        pdf = ROOT / "data" / "raw" / "CIE-10_2018_VOL2.pdf"
        facts = diabetes_sequence_candidates(pages, pdf)
        from collections import Counter
        self.assertEqual(Counter(f["diabetes_code"] for f in facts),
                         {"E10": 7, "E11": 8, "E12": 4, "E13": 44, "E14": 48})
        self.assertEqual(len({f["id"] for f in facts}), len(facts))
        for diabetes in ("E13", "E14"):
            c = [f for f in facts if f["diabetes_code"] == diabetes and f["cause_code_expression"] == "C78.8"]
            self.assertEqual(len(c), 1)
            self.assertEqual(c[0]["qualifier"], "Solamente páncreas")
        adjacent = [f for f in facts if f["diabetes_code"] == "E13" and
                    f["cause_code_expression"] in ("Y46.2", "Y52.5")]
        self.assertEqual(len(adjacent), 2)
        self.assertTrue(all("adjacent_source_codes_require_review" in f["warnings"] for f in adjacent))
        self.assertTrue(all(f["source"]["line_id"] is not None for f in facts))
        visual = read_json(ROOT / "tests" / "fixtures" / "vol2_7_6_visual_reference.json")
        from collections import defaultdict
        segments = defaultdict(list)
        for fact in facts:
            key = f"{fact['source']['pdf_page']}:{fact['source']['column']}:{fact['diabetes_code']}"
            segments[key].append(fact["cause_code_expression"])
        self.assertEqual(dict(segments), visual["segments"])
        for key, qualifier in visual["qualifiers"].items():
            diabetes, cause = key.split(":")
            match = next(f for f in facts if f["diabetes_code"] == diabetes and
                         f["cause_code_expression"] == cause)
            self.assertEqual(match["qualifier"], qualifier)


if __name__ == "__main__":
    unittest.main()

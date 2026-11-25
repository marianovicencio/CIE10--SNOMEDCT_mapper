"""Comparison dimensions remain source-bound across code families."""
from copy import deepcopy
import unittest
from cie10.candidate_comparison import build_comparison, key

CID = "26929004"

def evidence(title, term, parents=(), extras=()):
    return [dict(id="cie-title",type="CIE10",role="title",text=title,provenance="Volume 1"),
            dict(id="snomed-term",type="SNOMED",role="candidate_term",concept_id=CID,text=term,provenance="dated edition")]+[
            dict(id="snomed-parent-"+str(i),type="SNOMED",role="parent",concept_id=CID,text=text,provenance="dated edition") for i,text in enumerate(parents)]+list(extras)

def review(constraint=None):
    return dict(constraint=constraint,anatomy=dict(status="not_comparable"),input_scope="not_provided")

def dimension(result, identifier):
    return next(x for x in result["dimensions"] if x["id"]==identifier)

class ComparisonTests(unittest.TestCase):
    def test_manifestation_supported_by_published_parent_without_anatomical_distraction(self):
        items=evidence("Demencia en la enfermedad de Alzheimer (G30.–†)","enfermedad de Alzheimer",["degeneración cerebral que se manifiesta principalmente con demencia","demencia"],
                       [dict(id="site",type="SNOMED",role="finding_site",concept_id=CID,text="sitio del hallazgo cerebro")])
        result=build_comparison(items,review(),dict(sites=[]))
        self.assertEqual(dimension(result,"condition")["status"],"supported_by_hierarchy")
        self.assertEqual(dimension(result,"association")["status"],"same_wording")
        self.assertEqual(result["summary"]["status"],"supported")
        self.assertNotIn("site",[x["id"] for x in result["dimensions"]])
        self.assertIn("snomed-parent-1",dimension(result,"condition")["evidence_refs"])

    def test_association_grammar_is_not_an_alzheimer_exception(self):
        items=evidence("Manifestación en la enfermedad de beta","enfermedad de beta",["manifestación"])
        result=build_comparison(items,review())
        self.assertEqual(dimension(result,"condition")["status"],"supported_by_hierarchy")
        self.assertEqual(dimension(result,"association")["status"],"same_wording")

    def test_literal_differences_do_not_become_clinical_conflicts(self):
        result=build_comparison(evidence("Angiosarcoma del hígado","carcinosarcoma primario de hígado"),review())
        self.assertEqual(result["summary"]["status"],"review")
        self.assertFalse(any(x["status"]=="conflict" for x in result["dimensions"]))

    def test_negation_and_unspecified_metadata_are_not_erased_by_label_comparison(self):
        self.assertNotEqual(key("Tumor no especificado"),key("Tumor"))
        self.assertNotEqual(key("Asma sin crisis"),key("Asma con crisis"))
        self.assertEqual(key("Angiosarcoma del hígado"),key("angiosarcoma de hígado"))

    def test_added_qualifiers_are_displayed_in_multiple_families(self):
        for title,term in [("Asma","Asma con crisis"),("Enfermedad renal","Enfermedad renal con anemia")]:
            with self.subTest(title=title):
                result=build_comparison(evidence(title,term),review())
                self.assertEqual(dimension(result,"qualifiers")["status"],"candidate_detail")
                self.assertIn("añade detalle",result["summary"]["title"])
                self.assertFalse(result["positive_mapping_approved"])

    def test_narrower_associated_condition_requires_review(self):
        result=build_comparison(evidence("Demencia en la enfermedad de Alzheimer","enfermedad de Alzheimer focal",["enfermedad de Alzheimer"]),review())
        self.assertEqual(dimension(result,"association")["status"],"candidate_narrower")
        self.assertEqual(result["summary"]["status"],"review")

    def test_missing_stage_is_not_silently_discarded(self):
        result=build_comparison(evidence("Enfermedad renal crónica, etapa 5","Enfermedad renal crónica"),review())
        self.assertEqual(dimension(result,"stage")["status"],"not_explicit")
        self.assertEqual(dimension(result,"stage")["cie"]["text"],"etapa 5")

    def test_matching_stage_and_onset_aliases_retain_the_actual_source(self):
        alias=dict(id="alias",type="SNOMED",role="candidate_alias",concept_id=CID,text="Enfermedad de inicio temprano, etapa 5")
        result=build_comparison(evidence("Enfermedad de comienzo temprano, estadio 5","Enfermedad específica",extras=[alias]),review())
        for name in ("stage","onset"):
            row=dimension(result,name)
            self.assertEqual(row["status"],"same_wording")
            self.assertIn("alias",row["evidence_refs"])

    def test_morphology_substring_does_not_match_another_histology(self):
        morph=dict(id="morph",type="SNOMED",role="116676008",concept_id=CID,text="morfología asociada carcinoma")
        result=build_comparison(evidence("Adenocarcinoma del hígado","Carcinoma de hígado",extras=[morph]),review())
        self.assertNotEqual(dimension(result,"morphology")["status"],"same_wording")

    def test_explicit_constraint_takes_precedence_over_literal_name_match(self):
        constraint=dict(rule_id="verified",assessment="incompatible",justification="Restricción documentada.",evidence_refs=["cie-title","snomed-term"])
        result=build_comparison(evidence("Asma","Asma"),review(constraint))
        self.assertEqual(result["summary"]["status"],"conflict")
        self.assertEqual(dimension(result,"restriction")["status"],"conflict")
        self.assertFalse(result["automatic_selection"])

    def test_different_anatomy_without_subsumption_is_not_a_contradiction(self):
        r=review();r["anatomy"]["status"]="no_hierarchy_link_review"
        items=evidence("Tumor de órgano alfa","Tumor de órgano beta",extras=[dict(id="site",type="SNOMED",role="finding_site",concept_id=CID,text="sitio del hallazgo órgano beta")])
        result=build_comparison(items,r,dict(sites=[dict(concept_id="100",descriptions=["órgano alfa"])]))
        self.assertEqual(dimension(result,"site")["status"],"different_wording")
        self.assertNotEqual(result["summary"]["status"],"conflict")

    def test_other_candidate_parent_is_not_borrowed(self):
        items=evidence("Demencia","Enfermedad")+[dict(id="other",type="SNOMED",concept_id="123456",role="parent",text="demencia")]
        result=build_comparison(items,review())
        self.assertEqual(dimension(result,"condition")["status"],"different_wording")
        self.assertNotIn("other",[x["id"] for x in result["sources"]])

    def test_coding_reference_and_actual_symbol_are_preserved_in_sources(self):
        items=evidence("Demencia en la enfermedad de Alzheimer (G30.–†)","Enfermedad de Alzheimer")
        items[0]["code_symbol"]="*"
        result=build_comparison(items,review())
        self.assertIn("asterisco",dimension(result,"coding")["cie"]["text"])
        self.assertIn("G30.–†",result["sources"][0]["text"])

    def test_input_is_separate_and_does_not_change_source_categories(self):
        items=evidence("Asma","Asma")+[dict(id="input",type="INPUT",text="Su madre presenta asma.")]
        r=review();r["input_scope"]="other_subject"
        original=deepcopy(items)
        result=build_comparison(items,r)
        self.assertEqual(result["input"]["scope"],"other_subject")
        self.assertEqual(result["input"]["text"],items[-1]["text"])
        self.assertEqual(items,original)
        self.assertFalse(result["positive_mapping_approved"])

    def test_missing_anchor_prevents_claiming_a_published_whole_condition_subtype(self):
        items=evidence("Afección sin rasgo","Subtipo",["Afección"])
        anchor=dict(status="verified_published_condition",matched_description="Afección",concept_id="0",sites=[])
        result=build_comparison(items,review(),anchor)
        self.assertNotEqual(dimension(result,"condition")["status"],"candidate_narrower")

    def test_missing_base_source_does_not_fabricate_a_comparison(self):
        self.assertIsNone(build_comparison(evidence("Asma","Asma")[:1],review()))

    def test_background_morphology_does_not_create_a_missing_information_warning(self):
        morph=dict(id="morph",type="SNOMED",role="116676008",concept_id=CID,text="morfología asociada anormalidad degenerativa")
        result=build_comparison(evidence("Demencia en la enfermedad de Alzheimer","enfermedad de Alzheimer",["demencia"],[morph]),review())
        self.assertEqual(dimension(result,"morphology")["status"],"context")
        self.assertEqual(result["summary"]["status"],"supported")

    def test_symbol_explanation_cites_the_actual_manual_when_available(self):
        manual=dict(id="manual",type="CIE10",volume=2,role="manual_convention",text="El sistema de daga y asterisco distingue la enfermedad básica y su manifestación.")
        result=build_comparison(evidence("Manifestación (A00†)","Afección",extras=[manual]),review())
        self.assertIn("manual",dimension(result,"coding")["evidence_refs"])

    def test_no_qualifier_is_displayed_as_written_not_as_ungrammatical_sin(self):
        result=build_comparison(evidence("Afección","Afección no complicada"),review())
        self.assertEqual(dimension(result,"qualifiers")["candidate"]["text"],"No complicada")

    def test_stage_wording_does_not_obscure_a_matching_condition(self):
        result=build_comparison(evidence("Enfermedad renal crónica, etapa 5","Enfermedad renal crónica estadio 5"),review())
        self.assertEqual(dimension(result,"condition")["status"],"same_wording")
        self.assertEqual(dimension(result,"stage")["status"],"same_wording")
        self.assertEqual(result["summary"]["status"],"supported")

    def test_separating_qualifiers_does_not_hide_different_stages(self):
        result=build_comparison(evidence("Enfermedad, etapa 4","Enfermedad estadio 5"),review())
        self.assertEqual(dimension(result,"condition")["status"],"same_wording")
        self.assertEqual(dimension(result,"stage")["status"],"different_wording")
        self.assertEqual(result["summary"]["status"],"review")

    def test_without_mention_is_preserved_without_becoming_negative_complications(self):
        result=build_comparison(evidence("Diabetes mellitus tipo 2 — Sin mención de complicación","diabetes mellitus tipo 2 sin complicaciones"),review())
        self.assertEqual(dimension(result,"condition")["status"],"same_wording")
        self.assertIn("Sin mención",dimension(result,"specification")["cie"]["text"])
        self.assertEqual(dimension(result,"qualifiers")["status"],"candidate_detail")
        self.assertEqual(result["summary"]["status"],"review")

    def test_nonpatient_context_is_not_hidden_by_matching_names(self):
        items=evidence("Asma","Asma")+[dict(id="input",type="INPUT",text="Su madre presenta asma.")]
        r=review();r["input_scope"]="other_subject"
        result=build_comparison(items,r)
        self.assertEqual(result["summary"]["status"],"review")
        self.assertIn("contexto",result["summary"]["title"])

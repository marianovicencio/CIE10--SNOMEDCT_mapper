"""Recover generated comparisons without accepting invented sources or assertions."""
import json
import unittest
from cie10.explanations.candidate_explanation import explain_candidate
from cie10.explanations.explanation_prompt import generation_setup
from cie10.explanations.explanation_attribution import source_label

CID = "109844006"
EVIDENCE = [dict(id="title",type="CIE10",role="title",text="Angiosarcoma del hígado"),
            dict(id="term",type="SNOMED",role="candidate_term",concept_id=CID,text="angiosarcoma de hígado")]
TEXT = "El título CIE-10 y el candidato SNOMED coinciden en angiosarcoma y localización en el hígado."

def answer(text=TEXT, refs=None):
    return dict(concept_id=CID,assessment="compatible",additional_detail_needed=[],claims=[dict(text=text,evidence_refs=refs or ["cie_title","snomed_term"])])

class LocalRecoveryTests(unittest.TestCase):
    def test_third_local_attempt_regenerates_without_copying_failed_prose(self):
        calls=[]
        bad=answer(refs=["cie_title","invented"])
        def transport(body):
            calls.append(body)
            return dict(content=json.dumps(bad if len(calls)<3 else answer()))
        result=explain_candidate(CID,None,EVIDENCE,transport=transport,response_profile="local")
        self.assertEqual(result["status"],"explanation_available")
        self.assertEqual(result["attempts"],3)
        self.assertTrue(result["recovered_after_validation"])
        self.assertEqual(result["analysis"]["justification"],TEXT)
        self.assertIn("ÚLTIMO INTENTO",calls[2]["prompt"])
        self.assertNotIn("INTENTO ANTERIOR (datos para corregir)",calls[2]["prompt"])

    def test_external_profile_keeps_two_attempts(self):
        calls=[]
        def transport(body):
            calls.append(body)
            return dict(content=json.dumps(answer(refs=["cie_title","invented"])))
        result=explain_candidate(CID,None,EVIDENCE,transport=transport)
        self.assertEqual(result["status"],"explanation_rejected")
        self.assertEqual(result["attempts"],2)
        self.assertEqual(len(calls),2)
        self.assertIsNone(result["analysis"])

    def test_duplicate_known_citations_are_normalized_without_rewriting(self):
        value=answer(refs=["cie_title","snomed_term","cie_title"])
        result=explain_candidate(CID,None,EVIDENCE,transport=lambda _:dict(content=json.dumps(value)),response_profile="local")
        self.assertEqual(result["status"],"explanation_available")
        self.assertEqual(result["analysis"]["justification"],TEXT)
        self.assertEqual(result["analysis"]["evidence_refs"],["title","term"])
        self.assertEqual(result["normalizations"],["duplicate_known_citations_removed"])

    def test_unknown_citations_remain_rejected_after_all_local_attempts(self):
        result=explain_candidate(CID,None,EVIDENCE,transport=lambda _:dict(content=json.dumps(answer(refs=["cie_title","invented"]))),response_profile="local")
        self.assertEqual(result["status"],"explanation_rejected")
        self.assertEqual(result["attempts"],3)
        self.assertIsNone(result["analysis"])

    def test_local_retry_does_not_accept_unsourced_patient_claim(self):
        value=answer("El paciente presenta angiosarcoma. El título CIE-10 y el candidato SNOMED coinciden.")
        result=explain_candidate(CID,None,EVIDENCE,transport=lambda _:dict(content=json.dumps(value)),response_profile="local")
        self.assertEqual(result["status"],"explanation_rejected")
        self.assertIsNone(result["analysis"])

    def test_local_prompt_is_shorter_but_retains_source_boundaries(self):
        _,local=generation_setup(CID,None,EVIDENCE,profile="local")
        _,expanded=generation_setup(CID,None,EVIDENCE)
        self.assertLess(len(local),len(expanded))
        for text in ["NO son inclusiones", "no convierte dos conceptos en sinónimos", "No apliques mortalidad", "NO se recibió diagnóstico"]:
            self.assertIn(text,local)

    def test_parent_evidence_has_specific_display_label(self):
        self.assertEqual(source_label(dict(type="SNOMED",role="parent")),"Concepto superior SNOMED CT")

    def test_explicit_known_reference_in_prose_is_resolved_without_guessing(self):
        evidence=EVIDENCE+[dict(id="parent",type="SNOMED",role="parent",concept_id=CID,text="Angiosarcoma")]
        value=answer(TEXT+" sct_2 respalda la afección.")
        # Aliases are counted by type, including the candidate term.
        from cie10.explanations.explanation_prompt import reference_aliases
        alias=reference_aliases(evidence)["parent"]
        value["claims"][0]["text"]=TEXT+" "+alias+" respalda la afección."
        result=explain_candidate(CID,None,evidence,transport=lambda _:dict(content=json.dumps(value)),response_profile="local")
        self.assertEqual(result["status"],"explanation_available")
        self.assertIn("parent",result["analysis"]["evidence_refs"])
        self.assertIn("explicit_source_mention_resolved",result["normalizations"])

    def test_technical_field_name_can_be_made_readable_without_changing_assertion(self):
        value=answer("El título CIE-10 y candidate_term de SNOMED coinciden en angiosarcoma del hígado.")
        result=explain_candidate(CID,None,EVIDENCE,transport=lambda _:dict(content=json.dumps(value)),response_profile="local")
        self.assertEqual(result["status"],"explanation_available")
        self.assertNotIn("candidate_term",result["analysis"]["justification"])
        self.assertIn("technical_field_label_made_readable",result["normalizations"])

    def test_limited_retry_never_proposes_automatic_selection(self):
        diagnostic="Angiosarcoma del hígado"
        evidence=EVIDENCE+[dict(id="input",type="INPUT",text=diagnostic)]
        calls=[]
        def transport(body):
            calls.append(body)
            value=answer(refs=["cie_title","snomed_term","user_text"])
            if len(calls)<3:value["claims"][0]["evidence_refs"]=["invented"]
            return dict(content=json.dumps(value))
        result=explain_candidate(CID,diagnostic,evidence,transport=transport,response_profile="local")
        self.assertEqual(result["status"],"explanation_available")
        self.assertEqual(result["analysis"]["selection"],"abstained")
        self.assertIsNotNone(result["recovery_context_selection"])

    def test_recovery_evidence_preserves_whole_sources_and_reports_omissions(self):
        from cie10.explanations.explanation_recovery import recovery_evidence
        evidence=EVIDENCE+[dict(id="parent",type="SNOMED",concept_id=CID,role="parent",text="Tumor maligno"),dict(id="manual",type="CIE10",volume=2,text="Texto general del manual.")]
        selected,report=recovery_evidence(evidence,None)
        self.assertEqual(selected,evidence[:3])
        self.assertEqual(report["omitted_evidence_ids"],["manual"])
        self.assertTrue(report["full_documentary_checks_retained"])

    def test_quotes_around_a_field_label_are_not_treated_as_a_medical_quote(self):
        value=answer(TEXT+" El atributo ‘finding_site’ describe el hígado.")
        evidence=EVIDENCE+[dict(id="site",type="SNOMED",role="finding_site",concept_id=CID,text="Hígado")]
        value["claims"][0]["evidence_refs"].append("sct_2")
        result=explain_candidate(CID,None,evidence,transport=lambda _:dict(content=json.dumps(value)),response_profile="local")
        self.assertEqual(result["status"],"explanation_available")
        self.assertNotIn("‘sitio del hallazgo SNOMED’",result["analysis"]["justification"])

    def test_unknown_medical_quote_cannot_be_removed_as_a_field_label(self):
        value=answer(TEXT+" El término SNOMED dice ‘carcinoma del riñón’.")
        result=explain_candidate(CID,None,EVIDENCE,transport=lambda _:dict(content=json.dumps(value)),response_profile="local")
        self.assertEqual(result["status"],"explanation_rejected")

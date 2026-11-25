import unittest
from cie10.reasoning.literal_assertions import literal_constraint
from cie10.explanations.candidate_explanation import explain_candidate, model_evidence_view

ID='128350005'
def evidence(title='Conjuntivitis, no especificada',term='conjuntivitis bacteriana',text=None):
 rows=[{'id':'cie-title','type':'CIE10','role':'title','text':title},{'id':'snomed-term','type':'SNOMED','role':'candidate_term','concept_id':ID,'text':term}]
 if text:rows.append({'id':'input-diagnostic','type':'INPUT','text':text})
 return rows

class LiteralAssertionTests(unittest.TestCase):
 def test_bacterial_qualifier_without_input_needs_detail(self):
  r=literal_constraint(evidence());self.assertEqual(r['assessment'],'undetermined');self.assertTrue(r['additional_detail_needed'])
 def test_chronic_qualifier_without_input_needs_detail(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos crónica'))['assessment'],'undetermined')
 def test_confirmed_qualifier_is_delegated_not_auto_approved(self):
  self.assertIsNone(literal_constraint(evidence(text='Conjuntivitis bacteriana.')))
 def test_existing_code_qualifier_does_not_require_more_data(self):
  self.assertIsNone(literal_constraint(evidence('Bronquitis crónica','bronquitis crónica')))
 def test_exact_current_negation_overrides_missing_detail(self):
  r=literal_constraint(evidence(text='Informe corregido: no hay conjuntivitis; diagnóstico de catarata.'));self.assertEqual(r['assessment'],'incompatible')
 def test_denial_and_other_person(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos','El paciente no tiene tos; la tos corresponde a su acompañante.'))['assessment'],'incompatible')
 def test_positive_and_negative_requires_clarification(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos','No tiene tos; presenta tos.'))['assessment'],'undetermined')
 def test_other_person_is_not_a_patient_fact(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos','Su madre presenta tos.'))['assessment'],'undetermined')
 def test_other_person_negative_is_not_patient_denial(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos','Su madre no tiene tos.'))['assessment'],'undetermined')
 def test_double_negation_does_not_mean_absence(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos','No se descarta tos.'))['assessment'],'undetermined')
 def test_hypothetical_denial_is_not_an_assertion(self):
  self.assertEqual(literal_constraint(evidence('Tos','tos','Si no hay tos.'))['assessment'],'undetermined')
 def test_negated_other_symptom_does_not_deny_target(self):
  self.assertIsNone(literal_constraint(evidence('Tos','tos','Niega fiebre; presenta tos.')))
 def test_time_limited_negation_not_expanded_to_all_conditions(self):
  self.assertIsNone(literal_constraint(evidence('Tos','tos','Niega tos por la mañana, pero presenta tos por la noche.')))
 def test_unrecognized_heads_do_not_trigger_guards(self):
  self.assertIsNone(literal_constraint(evidence('Enfermedad renal crónica','neumonía bacteriana')))
 def test_unknown_paraphrase_is_delegated_without_clinical_inference(self):
  self.assertIsNone(literal_constraint(evidence(text='La inflamación de la conjuntiva es bacteriana.')))
 def test_qualifier_in_another_sentence_is_not_support(self):
  r=literal_constraint(evidence(text='Conjuntivitis sin precisar causa. Infección bacteriana del oído.'));self.assertEqual(r['assessment'],'undetermined')
 def test_explicit_rules_use_citations_and_preserve_selection_contract(self):
  for items,selection in [(evidence(),'not_requested'),(evidence(text='No hay conjuntivitis.'),'abstained')]:
   r=explain_candidate(ID,None if len(items)==2 else items[-1]['text'],items,transport=lambda _:self.fail('No model needed'))
   self.assertEqual(r['status'],'explanation_available');self.assertEqual(r['analysis']['selection'],selection);self.assertIn('cie-title',r['analysis']['evidence_refs'])
 def test_model_role_is_readable_without_mutating_source(self):
  row={'id':'sct_1','type':'SNOMED','role':'116676008','text':'morfología inflamatoria'}
  self.assertEqual(model_evidence_view(row)['role'],'associated_morphology');self.assertEqual(row['role'],'116676008')

 def test_qualified_target_can_be_explicitly_denied(self):
  self.assertEqual(literal_constraint(evidence('Bronquitis aguda, no especificada','bronquitis aguda','No hay bronquitis aguda.'))['assessment'],'incompatible')
 def test_denial_of_a_subtype_does_not_deny_generic_condition(self):
  self.assertIsNone(literal_constraint(evidence('Tos','tos','Niega tos crónica.')))

 def test_model_prompt_has_semantic_morphology_but_original_source_is_intact(self):
  from cie10.explanations.candidate_explanation import generation_setup
  rows=evidence();rows.append({'id':'snomed-116676008-409774005','type':'SNOMED','role':'116676008','concept_id':ID,'text':'morfología inflamatoria'})
  _,prompt=generation_setup(ID,None,rows)
  self.assertNotIn('116676008',prompt);self.assertIn('associated_morphology',prompt);self.assertEqual(rows[-1]['role'],'116676008')

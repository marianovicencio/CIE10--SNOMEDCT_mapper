import unittest,json
from cie10.reasoning.safety import safety_constraint,qualifier_conflict,scope_marker
from cie10.candidate_explanation import explain_candidate
from cie10.reasoning.comparisons import literal_label_analysis
from cie10.explanation_attribution import validate_claim_attribution

ID='39450006'
def ev(title,term,text=None):
 a=[dict(id='t',type='CIE10',role='title',text=title),dict(id='s',type='SNOMED',role='candidate_term',concept_id=ID,text=term)]
 if text:a.append(dict(id='i',type='INPUT',text=text))
 return a

class SafetyTests(unittest.TestCase):
 def test_opposed_senility_without_promoting_generic_overlap(self):
  self.assertTrue(qualifier_conflict('Catarata senil, no especificada','catarata no senil'))
  self.assertFalse(qualifier_conflict('Catarata senil','demencia no senil'))
  self.assertEqual(safety_constraint(ev('Catarata senil','catarata no senil'))['assessment'],'incompatible')
 def test_hypothesis_is_not_current_diagnosis(self):
  e=ev('Catarata senil','catarata senil','Si el paciente tuviera catarata senil, se solicitaría evaluación. Es una hipótesis.')
  r=explain_candidate(ID,e[-1]['text'],e,transport=lambda _:self.fail('Model called'))
  self.assertEqual(r['analysis']['selection'],'abstained');self.assertIn('hypothetical',r['constraint_id'])
 def test_unrelated_hypothesis_does_not_negate_confirmed_condition(self):
  self.assertIsNone(safety_constraint(ev('Catarata senil','catarata senil','Si tuviera fiebre, se reevaluaría. Tiene catarata senil.')))
 def test_direct_candidate_denial_without_equal_title_heads(self):
  self.assertEqual(safety_constraint(ev('Hipertensión esencial (primaria)','hipertensión arterial esencial','Se descarta hipertensión arterial esencial.'))['assessment'],'incompatible')
 def test_negated_other_symptom_or_family_denial_is_not_patient_denial(self):
  for text in ['Se descarta fiebre. Tiene psoriasis.','Su madre no tiene psoriasis.','No se descarta psoriasis.']:
   self.assertIsNone(safety_constraint(ev('Psoriasis','psoriasis',text)))
 def test_explicit_with_without_conflict(self):
  r=safety_constraint(ev('Cálculo de la vesícula biliar sin colecistitis','cálculo de vesícula biliar sin colecistitis o colangitis','Cálculos vesiculares con colecistitis aguda confirmada.'))
  self.assertEqual(r['assessment'],'incompatible')
 def test_additional_absence_is_not_inferred(self):
  title='Cálculo de la vesícula biliar sin colecistitis';term='cálculo de vesícula biliar sin colecistitis o colangitis'
  self.assertEqual(safety_constraint(ev(title,term))['assessment'],'undetermined')
  self.assertIsNone(safety_constraint(ev(title,term,'Cálculos vesiculares sin colecistitis ni colangitis.')))
 def test_literal_header_uses_explicit_source_identity(self):
  e=ev('Psoriasis, no especificada','psoriasis','Se confirma psoriasis.')
  r={'analysis':literal_label_analysis(ID,e[-1]['text'],e)}
  self.assertEqual(r['analysis']['selection'],'proposed')
 def test_failed_generation_abstains_without_erasing_errors(self):
  e=ev('Hipertensión esencial','hipertensión arterial esencial','Hipertensión primaria.')
  r=explain_candidate(ID,e[-1]['text'],e,transport=lambda _:dict(content='invalid'))
  self.assertEqual(r['status'],'explanation_rejected');self.assertIsNone(r['analysis']);self.assertEqual(len(r['errors']),2)
 def test_unattributed_mechanism_and_internal_role_rejected(self):
  sources={x['id']:x for x in ev('Psoriasis','psoriasis')}
  for text in ['El candidato tiene naturaleza citotóxica mediada por células.','El término candidate_term coincide.']:
   with self.assertRaises(ValueError):validate_claim_attribution(text,['t','s'],sources)
 def test_reranker_recognizes_hypothetical_scope(self):self.assertTrue(scope_marker('Si el paciente tuviera catarata senil.'))

 def test_unrelated_unspecified_subtype_does_not_erase_literal_support(self):
  e=ev('Psoriasis, no especificada','psoriasis','Se confirma psoriasis; no se especifica una variedad.')
  r={'analysis':literal_label_analysis(ID,e[-1]['text'],e)}
  self.assertEqual(r['analysis']['selection'],'proposed')

 def test_official_same_concept_alias_can_back_literal_input_match(self):
  e=ev('Catarata senil, no especificada','catarata senil','Diagnóstico: catarata relacionada con la edad.')
  e.append(dict(id='alias',type='SNOMED',role='candidate_alias',concept_id=ID,text='catarata relacionada con la edad'))
  r={'analysis':literal_label_analysis(ID,e[2]['text'],e)}
  self.assertIn('alias',r['analysis']['evidence_refs']);self.assertEqual(r['analysis']['selection'],'proposed')

 def test_negated_manifestation_does_not_activate_index_pair(self):
  from cie10.index_reasoning import index_constraint
  e=ev('Enfermedad de Alzheimer','enfermedad de Alzheimer','Enfermedad de Alzheimer. No se menciona demencia.')
  e.append(dict(id='index-pair',type='CIE10',volume=3,role='index_entry',route=['Demencia','Alzheimer'],text='G30.9† F00.9*',code_references=['G30.9†','F00.9*']))
  self.assertIsNone(index_constraint(e))

class GrammaticalLabelTests(unittest.TestCase):
 def test_transversal_articles_without_model(self):
  for left,right in [
   ('Angiosarcoma del hígado','angiosarcoma de hígado'),
   ('Cálculo de la vesícula biliar','cálculo de vesícula biliar'),
   ('Fractura del fémur','fractura de fémur'),
   ('Enfermedad de los nervios periféricos','enfermedad de nervios periféricos')]:
   with self.subTest(left=left):
    evidence=ev(left,right)
    result={'analysis':literal_label_analysis(ID,None,evidence)}
    self.assertEqual(result['analysis']['assessment'],'compatible')
    self.assertEqual(result['analysis']['selection'],'not_requested')
    self.assertEqual([x['text'] for x in result['analysis']['quotes']],[left,right])
 def test_content_qualifiers_and_names_preserved(self):
  from cie10.reasoning.comparisons import label_comparison_kind
  for left,right in [
   ('Angiosarcoma del hígado','angiosarcoma de bazo'),
   ('Catarata senil','catarata no senil'),
   ('Fractura del fémur izquierdo','fractura de fémur derecho'),
   ('Enfermedad renal etapa 5','enfermedad renal etapa 4'),
   ('Hepatitis aguda','hepatitis crónica'),
   ('Tumor primario del hígado','tumor secundario de hígado'),
   ('Cálculo sin colecistitis','cálculo con colecistitis'),
   ('Cólera de El Tor','cólera de Tor'),
   ('Síndrome de la Cruz','síndrome de Cruz'),
   ('Dolor en hígado','dolor de hígado')]:
   with self.subTest(left=left):self.assertIsNone(label_comparison_kind(left,right))
 def test_diagnostic_grammar_is_source_bound(self):
  e=ev('Angiosarcoma del hígado','angiosarcoma de hígado','Se confirma angiosarcoma del hígado.')
  r={'analysis':literal_label_analysis(ID,e[-1]['text'],e)}
  self.assertEqual(r['analysis']['selection'],'proposed')
  self.assertIn('i',r['analysis']['evidence_refs'])
 def test_unsafe_diagnostic_does_not_become_positive(self):
  from cie10.reasoning.comparisons import literal_label_analysis
  for text in ['No tiene angiosarcoma del hígado.', 'Su madre tiene angiosarcoma del hígado.', 'Sospecha de angiosarcoma del hígado.']:
   with self.subTest(text=text):
    e=ev('Angiosarcoma del hígado','angiosarcoma de hígado',text)
    self.assertIsNone(literal_label_analysis(ID,text,e))
 def test_exclusion_precedes_grammatical_agreement(self):
  e=ev('Tumor del hígado','tumor de hígado')
  e += [dict(id='ex',type='CIE10',role='exclusion',inherited=False,text='hígado (C22)'),dict(id='site',type='SNOMED',role='finding_site',concept_id=ID,text='hígado')]
  r=explain_candidate(ID,None,e,transport=lambda _:self.fail('Model called'))
  self.assertEqual(r['analysis']['assessment'],'incompatible')

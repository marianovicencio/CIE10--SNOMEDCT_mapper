import copy,unittest
from cie10.shortlist_reranker import apply_scores,scope_status,query_text,LocalCrossEncoder
from cie10.mapping_context import ContextError

class ShortlistTests(unittest.TestCase):
 def candidates(self):return [{'concept_id':str(i),'display':'published '+str(i),'fusion_score':.1} for i in range(5)]
 def test_permutation_preserves_candidates_metadata_and_input(self):
  rows=self.candidates();before=copy.deepcopy(rows);out=apply_scores(rows,{str(i):float(i) for i in range(5)})
  self.assertEqual({c['concept_id'] for c in out},{c['concept_id'] for c in rows});self.assertEqual(rows,before);self.assertEqual(out[0]['baseline_rank'],5);self.assertEqual(out[0]['fusion_score'],.1)
 def test_ties_preserve_original_order(self):
  rows=self.candidates();self.assertEqual([c['concept_id'] for c in apply_scores(rows,{str(i):0. for i in range(5)})],[c['concept_id'] for c in rows])
 def test_missing_extra_nonfinite_boolean_scores_rejected(self):
  scores={str(i):0. for i in range(5)}
  for bad in [{},dict(scores,extra=0),dict(scores,**{'0':float('nan')}),dict(scores,**{'0':True})]:
   with self.assertRaises(ContextError):apply_scores(self.candidates(),bad)
 def test_duplicate_candidates_rejected(self):
  with self.assertRaises(ContextError):apply_scores([{'concept_id':'a'}]*5,{'a':0})
 def test_code_only_keeps_baseline(self):self.assertEqual(scope_status(''),'code_only_unchanged')
 def test_scope_markers_skip_without_claiming_a_medical_conflict(self):
  for text in ['No hay tos.','Su madre presenta tos.','Niega fiebre; presenta tos.','No se descarta tos.']:
   self.assertEqual(scope_status(text),'scope_marker_keep_baseline')
 def test_unspecified_metadata_is_not_a_presence_negation(self):
  self.assertEqual(scope_status('Obesidad; no se especifica tipo.'),'eligible_for_scoring')
 def test_query_retains_the_original_strings(self):
  self.assertEqual(query_text('Título oficial','Dato original.'),'CIE-10: Título oficial\nDiagnóstico: Dato original.')

 def test_oversized_pairs_rejected_before_model_without_truncation(self):
  model=object.__new__(LocalCrossEncoder);model.max_tokens=512
  def tokenizer(a,b,**kwargs):
   self.assertIs(kwargs['truncation'],False);return {'input_ids':[0]*513}
  model.tokenizer=tokenizer
  with self.assertRaises(ContextError):model.score('original text',['published term'])

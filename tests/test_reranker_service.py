import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from cie10.reranker_service import apply_configured_reranker,published_fsns
from cie10.shortlist_reranker import REPOSITORY,REVISION,POLICY
from cie10.retrieval_evaluation import sha256
from cie10.mapping_context import ContextError

class FakeEncoder:
 closed=False
 def __init__(self,*a):FakeEncoder.closed=False
 def score(self,*a):return [.1,.3,.5,.4,.2],[12]*5
 def close(self):FakeEncoder.closed=True

class RerankerServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.index=self.root/'data/indexes/snomed/full';self.index.mkdir(parents=True);(self.index/'index.json').write_text('{}')
  self.config=self.root/'infra/retrieval/active-reranker.json';self.config.parent.mkdir(parents=True)
  self.result={'status':'candidates_retrieved_unreviewed','candidates':[{'concept_id':str(i),'rank':i+1,'display':'term','fusion_score':.1} for i in range(5)]}
  self.plan={'baseline_query_id':'q','queries':[{'id':'q','text':'Título oficial'}]}
 def tearDown(self):self.tmp.cleanup()
 def enable(self,**override):
  cfg={'status':'enabled_local_experimental','repository':REPOSITORY,'revision':REVISION,'policy':POLICY,'index_manifest_sha256':sha256(self.index/'index.json'),'implementation_sha256':{}};cfg.update(override);self.config.write_text(json.dumps(cfg))
 def runit(self,text='Afección afirmada.'):
  return apply_configured_reranker(self.result,{'diagnostic_text':text},self.plan,self.index,{},self.root)
 def test_disabled_keeps_baseline_without_loading(self):
  with patch('cie10.reranker_service.LocalCrossEncoder') as model:
   out=self.runit();self.assertFalse(out['reranking']['applied']);model.assert_not_called()
 def test_code_only_and_scope_marker_do_not_load_model(self):
  self.enable()
  with patch('cie10.reranker_service.LocalCrossEncoder') as model:
   for text in ['', 'No hay tos.']:
    out=self.runit(text);self.assertEqual(out['candidates'],self.result['candidates']);self.assertFalse(out['reranking']['applied'])
   model.assert_not_called()
 def test_success_updates_public_rank_preserves_retrieval_metadata(self):
  self.enable();before=copy.deepcopy(self.result)
  with patch('cie10.reranker_service.published_fsns',return_value=['a']*5),patch('cie10.reranker_service.LocalCrossEncoder',FakeEncoder):out=self.runit()
  self.assertEqual(out['candidates'][0]['concept_id'],'2');self.assertEqual([c['rank'] for c in out['candidates']],[1,2,3,4,5]);self.assertEqual(out['candidates'][0]['baseline_rank'],3);self.assertEqual(self.result,before);self.assertTrue(FakeEncoder.closed);self.assertFalse(out['reranking']['automatic_selection'])
 def test_missing_runtime_dependency_keeps_baseline(self):
  self.enable()
  with patch('cie10.reranker_service.published_fsns',return_value=['a']*5),patch('cie10.reranker_service.LocalCrossEncoder',side_effect=ImportError):out=self.runit()
  self.assertEqual(out['candidates'],self.result['candidates']);self.assertEqual(out['reranking']['reason'],'reranker_unavailable_baseline_retained')
 def test_invalid_configuration_keeps_baseline(self):
  self.enable(index_manifest_sha256='changed');out=self.runit();self.assertEqual(out['candidates'],self.result['candidates']);self.assertFalse(out['reranking']['applied'])
 def test_busy_explanation_does_not_load_another_model(self):
  self.enable()
  with patch('cie10.reranker_service.published_fsns',return_value=['a']*5),patch('cie10.reranker_service.fcntl.flock',side_effect=BlockingIOError),patch('cie10.reranker_service.LocalCrossEncoder') as model:out=self.runit();model.assert_not_called()
  self.assertEqual(out['reranking']['reason'],'local_model_busy_baseline_retained')
 def test_overlong_pair_keeps_baseline_and_frees_model(self):
  self.enable()
  with patch('cie10.reranker_service.published_fsns',return_value=['a']*5),patch('cie10.reranker_service.LocalCrossEncoder',FakeEncoder),patch.object(FakeEncoder,'score',side_effect=ContextError('Too long')):out=self.runit()
  self.assertFalse(out['reranking']['applied']);self.assertTrue(FakeEncoder.closed)

 def make_catalog(self,rows):
  catalog=self.root/'data/catalogs/snomed/test';catalog.mkdir(parents=True)
  (catalog/'catalog.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
  (catalog/'catalog.json').write_text(json.dumps({'files':{'catalog.jsonl':sha256(catalog/'catalog.jsonl')}}))
  return {'catalog_path':str(catalog),'catalog_manifest_sha256':sha256(catalog/'catalog.json')}
 def test_candidate_view_uses_published_fsn_instead_of_matching_synonym(self):
  rows=[{'concept_id':'a','description_type_id':'900000000000013009','term':'alias','active':True,'language':'es'},{'concept_id':'a','description_type_id':'900000000000003001','term':'nombre completo (trastorno)','active':True,'language':'es'}]
  info=self.make_catalog(rows);self.assertEqual(published_fsns(self.root,info,['a']),['nombre completo (trastorno)'])
 def test_inactive_fsn_is_never_scored(self):
  info=self.make_catalog([{'concept_id':'a','description_type_id':'900000000000003001','term':'inactive','active':False,'language':'es'}])
  with self.assertRaises(ContextError):published_fsns(self.root,info,['a'])

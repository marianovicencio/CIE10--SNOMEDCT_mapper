from copy import deepcopy
import json,tempfile,unittest,sqlite3
from pathlib import Path
from cie10.retrieval_title_fragments import prepare_queries,inspect_fragment,load_bundle,KIND,search_lexical
from cie10.retrieval_queries import prepare_queries as legacy,check_token_budget,queries_for_encoding,pointer_get
from cie10.mapping_context import ContextError,digest
from cie10.retrieval_core import sha256,write_json
from test_retrieval_queries import pack,reseal

def titled(title,**kwargs):
 p=pack(**kwargs);p['context']['documentary_context']['title']=title;p['audit']['records']['r']['description']=title;reseal(p);return p

class FragmentTests(unittest.TestCase):
 def test_literal_fragment_preserves_title_input_and_source(self):
  p=titled('Trastornos del sueño [insomnios]',inclusions=[]);original=deepcopy(p);base=legacy(p);v=prepare_queries(p)
  self.assertEqual(p,original);self.assertEqual(v['queries'][:len(base['queries'])],base['queries'])
  q=next(q for q in v['queries'] if q['kind']==KIND);segment=v['segments'][q['segment_refs'][0]];full=pointer_get(p[segment['container']],segment['pointer'])
  self.assertEqual(full[segment['start']:segment['end']],q['text']);self.assertEqual(q['text'],'insomnios');self.assertEqual(segment['evidence_refs'],['e:r']);self.assertFalse(q['patient_assertion']);self.assertFalse(v['policy']['fragments_assert_clinical_equivalence'])
 def test_unicode_offsets_and_inner_whitespace(self):
  p=titled('Trastornos 🩺 [insomnios]',inclusions=[]);v=prepare_queries(p);s=next(s for s in v['segments'].values() if s['role']==KIND)
  self.assertEqual(p['context']['documentary_context']['title'][s['start']:s['end']],'insomnios');self.assertEqual(s['offset_unit'],'unicode_code_points');self.assertEqual(inspect_fragment('Trastornos [  insomnios  ]')[0]['text'],'insomnios')
 def test_diagnostic_input_is_never_parsed_or_omitted(self):
  p=titled('Trastornos [insomnios]',diagnostic='Texto [no hay tos].');v=prepare_queries(p)
  self.assertEqual(v['queries'],legacy(p)['queries']);self.assertEqual(v['title_fragment_review'][0]['reason'],'diagnostic_present_preserve_existing_queries')
 def test_no_brackets_preserves_all_existing_queries(self):self.assertEqual(prepare_queries(pack())['queries'],legacy(pack())['queries'])
 def test_nested_multiple_unbalanced_and_nonterminal_are_held(self):
  for title in ['A [b [c]]','A [uno] [dos]','A [no cerrado','A [término] debido a otra causa']:
   self.assertIsNotNone(inspect_fragment(title)[1])
 def test_codes_and_dual_coding_are_not_aliases(self):
  for title in ['Diagnóstico [C74.–]','Diagnóstico [F02.8*]','Diagnóstico [tipo 1]']:
   self.assertIsNotNone(inspect_fragment(title)[1])
 def test_qualifiers_and_acronyms_are_not_standalone_diagnoses(self):
  for title in ['Temblor esencial [benigno]','Enfermedad [VIH]','Trastorno [de conversión]']:
   self.assertIsNotNone(inspect_fragment(title)[1])
 def test_scope_is_not_removed(self):
  for title in ['Enfermedad sin complicaciones [alternativa]','Infección debida a organismo [otro nombre]','Enfermedad crónica [otro nombre]']:
   self.assertIsNotNone(inspect_fragment(title)[1])
 def test_byte_budget_does_not_truncate_a_term(self):
  self.assertEqual(inspect_fragment('Enfermedad ['+'á'*25+']')[1],'literal_fragment_byte_budget')
 def test_original_budget_has_priority_over_extra_fragment(self):
  p=titled('Trastorno [alternativa]');v=prepare_queries(p,max_queries=2)
  self.assertEqual(v['queries'],legacy(p,max_queries=2)['queries']);self.assertEqual(v['title_fragment_review'][0]['reason'],'query_budget')
 def test_shared_qualifier_and_source_review_are_not_dropped(self):
  p=titled('Diabetes [alternativa]',shared=True);v=prepare_queries(p);self.assertFalse(any(q['kind']==KIND for q in v['queries']))
  p=titled('Trastorno [alternativa]');p['audit']['records']['r']['structure_issues']=['review'];v=prepare_queries(p);self.assertEqual(v['title_fragment_review'][0]['reason'],'primary_source_requires_review')
 def test_token_budget_still_checks_every_query(self):
  p=prepare_queries(titled('Trastornos [insomnios]',inclusions=[]));spec={'test':'tokenizer'}
  checked=check_token_budget(p,lambda t,**k:{'input_ids':[1,2]},64,spec)
  self.assertEqual(len(queries_for_encoding(checked,spec,64)),len(p['queries']))
 def test_tampered_fragment_offsets_rejected_even_with_resealed_hashes(self):
  p=titled('Trastornos [insomnios]',inclusions=[]);v=prepare_queries(p)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name,value in {**p,'queries':v}.items():write_json(root/(name+'.json'),value)
   def seal():write_json(root/'manifest.json',{'files':{x.name:sha256(x) for x in root.iterdir() if x.name!='manifest.json'}})
   seal();self.assertEqual(load_bundle(root),v)
   s=next(s for s in v['segments'].values() if s['role']==KIND);s['start']+=1;v['plan_sha256']=digest({k:x for k,x in v.items() if k!='plan_sha256'});write_json(root/'queries.json',v);seal()
   with self.assertRaises(ContextError):load_bundle(root)
 def test_legacy_bundles_are_still_supported(self):
  p=pack();v=legacy(p)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name,value in {**p,'queries':v}.items():write_json(root/(name+'.json'),value)
   write_json(root/'manifest.json',{'files':{x.name:sha256(x) for x in root.iterdir()}})
   self.assertEqual(load_bundle(root),v)

 def test_prefix_expansion_only_for_literal_fragment_not_original_or_diagnosis(self):
  db=sqlite3.connect(':memory:');db.executescript("CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id,term,description_id,normalized); CREATE VIRTUAL TABLE lexical USING fts5(normalized,content='aliases',content_rowid='alias_no'); INSERT INTO aliases VALUES(1,'a','insomnio','d','insomnio'); INSERT INTO lexical(lexical) VALUES('rebuild');")
  self.assertEqual(search_lexical(db,{'kind':KIND,'text':'insomnios'},5)[0]['concept_id'],'a')
  self.assertEqual(search_lexical(db,{'kind':'diagnostic_original','text':'insomnios'},5),[])
  self.assertEqual(search_lexical(db,{'kind':'official_description','text':'insomnios'},5),[]);db.close()

class ActivationTests(unittest.TestCase):
 def test_disabled_for_missing_wrong_index_and_changed_source(self):
  from cie10.retrieval_title_fragments import enabled,POLICY
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);index=root/'index';index.mkdir();write_json(index/'index.json',{'v':1})
   config=root/'infra/retrieval/active-query-variants.json';config.parent.mkdir(parents=True)
   self.assertFalse(enabled(root,index))
   source=root/'source.py';source.write_text('original')
   cfg={'status':'enabled_local_experimental','policy':POLICY,'index_manifest_sha256':sha256(index/'index.json'),'implementation_sha256':{'source.py':sha256(source)}}
   write_json(config,cfg);self.assertTrue(enabled(root,index))
   source.write_text('changed');self.assertFalse(enabled(root,index))
   source.write_text('original');write_json(index/'index.json',{'v':2});self.assertFalse(enabled(root,index))
 def test_documentary_and_specific_qualifiers_held(self):
  for title in ['Enfermedad [véase nota]','Trastorno específico del deletreo [ortografía]','Trastorno [orgánico]']:
   self.assertIsNotNone(inspect_fragment(title)[1])

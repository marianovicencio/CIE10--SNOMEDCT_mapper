import unittest,tempfile,sqlite3
from pathlib import Path
try:
 import numpy as np
except ImportError:np=None
from cie10.full_retrieval_runtime import StreamedMatrix,semantic_search_batch,streamed_sha256

@unittest.skipIf(np is None,'Requires retrieval environment')
class StreamedIndexTests(unittest.TestCase):
 def test_streamed_reads_and_rankings_equal_mmap_without_changing_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   from cie10.retrieval_core import sha256
   path=Path(tmp)/'vectors.npy';values=np.random.default_rng(7).normal(size=(45,8)).astype('float32');np.save(path,values)
   self.assertEqual(streamed_sha256(path),sha256(path))
   probe=np.load(path,mmap_mode='r');offset,shape,dtype=probe.offset,probe.shape,probe.dtype;probe._mmap.close()
   stream=StreamedMatrix(path,offset,shape,dtype)
   try:
    for start in (0,1,40):np.testing.assert_array_equal(stream[start:start+5],values[start:start+5])
    np.testing.assert_array_equal(stream[45:45],values[45:45])
    db=sqlite3.connect(':memory:');db.execute('CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id,term,description_id,semantic_eligible)')
    db.executemany('INSERT INTO aliases VALUES(?,?,?,?,?)',[(i+1,str(100000+i//2),'term'+str(i),str(i),1) for i in range(45)])
    vectors=values[:3];expected=semantic_search_batch(db,values,vectors,5,7);actual=semantic_search_batch(db,stream,vectors,5,7)
    self.assertEqual(actual,expected);db.close()
   finally:stream.close()
   np.testing.assert_array_equal(np.load(path),values)

 def test_complete_fixture_runtime_wires_index_and_search_without_a_real_model(self):
  import json
  from unittest.mock import patch
  from cie10.retrieval_core import sha256,write_json
  from cie10.full_retrieval_runtime import run_hybrid
  from cie10 import full_retrieval as stored
  class FakeEngine:
   def __init__(self,*a):self.tokenizer=None
   def encode(self,*a):return np.array([[1,0]],dtype='float32')
   def close(self):pass
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cat=root/'catalog';cat.mkdir();index=root/'index';index.mkdir()
   rows=[{'concept_id':'fixture:a','description_id':'a','active':True,'language':'es','term':'renal'}]
   (cat/'catalog.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
   meta={'status':'completed','kind':'synthetic_fixture','system':'urn:magister:synthetic-fixture','version':'fixture-v1','coverage':'fixture','files':{'catalog.jsonl':sha256(cat/'catalog.jsonl')}};write_json(cat/'catalog.json',meta)
   db=sqlite3.connect(index/'aliases.sqlite');db.executescript("CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id,term,description_id,normalized,semantic_eligible); CREATE VIRTUAL TABLE lexical USING fts5(normalized,content='aliases',content_rowid='alias_no'); INSERT INTO aliases VALUES(1,'fixture:a','renal','a','renal',1); INSERT INTO lexical(lexical) VALUES('rebuild');");db.commit();db.close()
   np.save(index/'embeddings.npy',np.array([[1,0]],dtype='float32'))
   info={'status':'completed','schema_version':'0.2.0','implementation_sha256':sha256(stored.__file__),'encoder_implementation_sha256':sha256(Path(stored.__file__).with_name('retrieval_core.py')),'packages':{},'catalog_path':str(cat),'catalog_manifest_sha256':sha256(cat/'catalog.json'),'files':{n:sha256(index/n) for n in ('aliases.sqlite','embeddings.npy')},'aliases':1,'embedding_dimension':2,'model':{}}
   write_json(index/'index.json',info)
   plan={'code':'C64','input_mode':'code_only','plan_sha256':'fixture','source_snapshot_sha256':'fixture','context_sha256':'fixture','policy':{}}
   queries=[{'id':'q1','text':'renal'}]
   with patch('cie10.full_retrieval_runtime.load_bundle',return_value=plan),patch('cie10.full_retrieval_runtime.TransformerRetriever',FakeEngine),patch('cie10.full_retrieval_runtime.check_token_budget',return_value={'queries':queries}),patch('cie10.full_retrieval_runtime.queries_for_encoding',return_value=queries):
    result=run_hybrid(root/'bundle',index,root/'result',device='cpu',allow_fixture=True)
   self.assertEqual(result['status'],'fixture_candidates_retrieved');self.assertEqual(result['candidates'][0]['concept_id'],'fixture:a')
   self.assertEqual(result['index_read_strategy'],'bounded_pread_drop_consumed_file_cache')

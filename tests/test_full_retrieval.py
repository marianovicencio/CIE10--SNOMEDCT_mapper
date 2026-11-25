import sqlite3,unittest
try:
 import numpy as np
except ImportError:
 np=None
from cie10.full_retrieval import semantic_search_batch

@unittest.skipIf(np is None,'Run with infra/retrieval/.venv/bin/python for vector tests')
class FullSearchTests(unittest.TestCase):
 def test_batched_search_matches_exhaustive_with_duplicates_ties_and_ineligible(self):
  rng=np.random.default_rng(42)
  db=sqlite3.connect(':memory:')
  db.execute('CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id,term,description_id,semantic_eligible)')
  rows=[(i+1,str(100000+i//3),'term-%03d'%i,str(i+100000),int(i%11!=0)) for i in range(97)]
  db.executemany('INSERT INTO aliases VALUES(?,?,?,?,?)',rows)
  matrix=rng.normal(size=(97,8)).astype('float32');matrix[3:7]=matrix[1]
  vectors=np.array([matrix[1],rng.normal(size=8)],dtype='float32')
  for chunk in (1,4,13,100):
   got=semantic_search_batch(db,matrix,vectors,5,chunk)
   for j,vector in enumerate(vectors):
    scores=matrix@vector;best={}
    for row,score in zip(rows,scores):
     _,c,t,d,eligible=row
     if not eligible:continue
     item={'concept_id':c,'term':t,'description_id':d,'score':float(score)}
     old=best.get(c)
     if old is None or (-score,t)<(-old['score'],old['term']):best[c]=item
    expected=sorted(best.values(),key=lambda x:(-x['score'],x['concept_id']))[:5]
    self.assertEqual([(x['concept_id'],x['term']) for x in got[j]],[(x['concept_id'],x['term']) for x in expected])
    np.testing.assert_allclose([x['score'] for x in got[j]],[x['score'] for x in expected],rtol=1e-5)
  db.close()

 def test_equal_scores_choose_lowest_concept_and_term_across_chunks(self):
  db=sqlite3.connect(':memory:');db.execute('CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id,term,description_id,semantic_eligible)')
  db.executemany('INSERT INTO aliases VALUES(?,?,?,?,?)',[(1,'300000','z','1',1),(2,'100000','b','2',1),(3,'100000','a','3',1),(4,'200000','x','4',1),(5,'000000','excluded','5',0)])
  result=semantic_search_batch(db,np.ones((5,2),dtype='float32'),np.ones((1,2),dtype='float32'),2,2)[0]
  self.assertEqual([(x['concept_id'],x['term']) for x in result],[('100000','a'),('200000','x')]);db.close()

 def test_long_text_is_retained_lexically_and_encoding_resumes_after_checkpoint(self):
  import tempfile,json
  from pathlib import Path
  from types import SimpleNamespace
  from unittest.mock import patch
  from cie10.full_retrieval import build_index,lexical_search
  from cie10.retrieval_evaluation import sha256
  class FakeEngine:
   calls=0;fail=True
   def __init__(self,*args):self.model=SimpleNamespace(config=SimpleNamespace(hidden_size=2))
   def tokenizer(self,texts,**kwargs):return {'input_ids':[[0]*len(text.split()) for text in texts]}
   def encode(self,texts,ids,role):
    FakeEngine.calls+=1
    if FakeEngine.fail and FakeEngine.calls==2:raise RuntimeError('simulated interruption')
    return np.tile(np.array([[1,0]],dtype='float32'),(len(texts),1))
   def close(self):pass
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);cat=root/'catalog';cat.mkdir();out=root/'index'
   rows=[{'concept_id':'fixture:'+str(i),'description_id':str(i),'active':True,'language':'es','term':('palabra '*520 if i==0 else 'renal '+str(i))} for i in range(514)]
   (cat/'catalog.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
   (cat/'catalog.json').write_text(json.dumps({'status':'completed','kind':'synthetic_fixture','system':'urn:magister:synthetic-fixture','version':'fixture-v1','counts':{'aliases':514,'concepts':514},'files':{'catalog.jsonl':sha256(cat/'catalog.jsonl')}}))
   with patch('cie10.full_retrieval.TransformerRetriever',FakeEngine):
    with self.assertRaises(RuntimeError):build_index(cat,out,{},device='cpu',allow_fixture=True)
    partial=json.loads((out/'index.json').read_text());self.assertEqual(partial['processed_aliases'],512)
    FakeEngine.fail=False;done=build_index(cat,out,{},device='cpu',allow_fixture=True)
   self.assertEqual(done['status'],'completed');self.assertEqual(done['semantic_aliases'],513);self.assertEqual(done['lexical_only_aliases'],1)
   db=sqlite3.connect(out/'aliases.sqlite');found=lexical_search(db,'palabra',1)
   self.assertEqual(found[0]['term'],rows[0]['term']);db.close()
   self.assertEqual(np.load(out/'embeddings.npy').shape,(514,2))

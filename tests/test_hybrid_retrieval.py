import csv
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cie10.hybrid_retrieval import fuse_rankings,lexical_search,load_bundle,run_hybrid
from cie10.mapping_context import ContextError,digest
from cie10.retrieval_evaluation import normalize,sha256,write_json
from cie10.snomed_catalog import aliases_from,import_rf2,load_catalog
from cie10.snowstorm_verification import SnowstormFHIR
from cie10.retrieval_queries import prepare_queries
from test_retrieval_queries import pack


EDITION='http://snomed.info/sct/900000000000207008/version/20261001'


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def rf2(self,changes=None):
        # Numeric component identifiers below are synthetic RF2 test rows,
        # never a published SNOMED catalogue or a clinical mapping example.
        concepts=self.root/'Concept_Snapshot_fixture.txt'
        desc=self.root/'Description_Snapshot_fixture.txt'
        ch=['id','effectiveTime','active','moduleId','definitionStatusId']
        dh=['id','effectiveTime','active','moduleId','conceptId','languageCode','typeId','term','caseSignificanceId']
        rows=[['100000','20260101','1','900000000000207008','900000000000074008'],
              ['200000','20260101','0','900000000000207008','900000000000074008']]
        dr=[['100001','20260101','1','900000000000207008','100000','es','900000000000013009','Ejemplo renal alfa','900000000000448009'],
            ['100002','20260101','1','900000000000207008','100000','es','900000000000013009','Ejemplo renal alfa','900000000000448009'],
            ['100003','20260101','1','900000000000207008','200000','es','900000000000013009','Concepto inactivo','900000000000448009'],
            ['100004','20260101','0','900000000000207008','100000','es','900000000000013009','Descripción inactiva','900000000000448009'],
            ['100005','20260101','1','900000000000207008','100000','en','900000000000013009','English term','900000000000448009']]
        if changes:changes(rows,dr)
        for p,header,data in ((concepts,ch,rows),(desc,dh,dr)):
            with p.open('w',newline='') as f:
                writer=csv.writer(f,delimiter='\t');writer.writerow(header);writer.writerows(data)
        return concepts,desc

    def test_rf2_only_active_spanish_aliases_of_active_concepts_are_eligible(self):
        concepts,desc=self.rf2()
        output=self.root/'catalog'
        manifest=import_rf2(concepts,[desc],EDITION,output)
        aliases=list(aliases_from(output,load_catalog(output)))
        self.assertEqual(manifest['counts']['aliases'],1)
        self.assertEqual(manifest['counts']['concepts'],1)
        self.assertEqual(aliases[0]['term'],'Ejemplo renal alfa')
        self.assertEqual(aliases[0]['description_id'],'100001')
        self.assertFalse(manifest['module_dependencies_validated'])

    def test_rf2_missing_concepts_future_states_and_unpublished_changes_fail(self):
        mutations=[lambda c,d:d[0].__setitem__(4,'300000'),
                   lambda c,d:d[0].__setitem__(1,'20270101'),
                   lambda c,d:d[0].__setitem__(1,'')]
        for i,mutation in enumerate(mutations):
            c,d=self.rf2(mutation)
            with self.subTest(i=i),self.assertRaises(ContextError):import_rf2(c,[d],EDITION,self.root/f'bad{i}')
            self.assertFalse((self.root/f'bad{i}'/'catalog.json').exists())

    def test_full_or_delta_and_unknown_edition_are_not_silently_used(self):
        c,d=self.rf2()
        c2=self.root/'Concept_Full_fixture.txt';c2.write_bytes(c.read_bytes())
        with self.assertRaises(ContextError):import_rf2(c2,[d],EDITION,self.root/'full')
        with self.assertRaises(ContextError):import_rf2(c,[d],'latest',self.root/'latest')

    def test_catalog_hash_and_fixture_namespace_are_enforced(self):
        folder=self.root/'fixture';folder.mkdir()
        (folder/'catalog.jsonl').write_text('{}\n')
        meta={'status':'completed','kind':'synthetic_fixture','system':'urn:magister:synthetic-fixture',
              'version':'fixture-v1','files':{'catalog.jsonl':sha256(folder/'catalog.jsonl')}}
        write_json(folder/'catalog.json',meta)
        with self.assertRaises(ContextError):load_catalog(folder)
        self.assertEqual(load_catalog(folder,True)['kind'],'synthetic_fixture')
        (folder/'catalog.jsonl').write_text('{"changed":true}\n')
        with self.assertRaises(ContextError):load_catalog(folder,True)

    def test_lexical_returns_unique_concepts_despite_many_synonyms(self):
        db=sqlite3.connect(':memory:')
        db.executescript("CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id TEXT,term TEXT,description_id TEXT,normalized TEXT); CREATE VIRTUAL TABLE lexical USING fts5(normalized,content='aliases',content_rowid='alias_no');")
        for i in range(30):
            text='Riñón crónico variante '+str(i)
            db.execute('INSERT INTO aliases VALUES (?,?,?,?,?)',(i+1,'fixture:a',text,str(i),normalize(text)))
        db.execute('INSERT INTO aliases VALUES (?,?,?,?,?)',(31,'fixture:b','Enfermedad renal crónica','b',normalize('Enfermedad renal crónica')))
        db.execute("INSERT INTO lexical(lexical) VALUES ('rebuild')")
        found=lexical_search(db,'riñón enfermedad renal crónica',2)
        self.assertEqual({x['concept_id'] for x in found},{'fixture:a','fixture:b'})
        self.assertEqual(lexical_search(db,'palabrainexistente',10),[])
        # Punctuation/operators never execute as FTS syntax.
        self.assertIsInstance(lexical_search(db,'" OR * NEAR( )',2),list)
        db.close()

    def ranking(self,method,query,ids):
        return {'method':method,'query_id':query,'candidates':[
            {'concept_id':c,'term':'Término '+c,'description_id':'d','score':.9-i*.1} for i,c in enumerate(ids)]}

    def test_rrf_balances_methods_and_deduplicates_concepts(self):
        listings=[self.ranking('lexical','q1',['a','b']),self.ranking('semantic','q1',['b','c'])]
        result=fuse_rankings(listings,2)
        self.assertEqual(result['candidates'][0]['concept_id'],'b')
        self.assertEqual(result['pool_concepts'],3)
        self.assertTrue(result['truncated'])
        self.assertFalse(result['score_is_probability'])
        self.assertAlmostEqual(result['candidates'][0]['fusion_score'],.5/62+.5/61)

    def test_repeated_variants_do_not_multiply_votes_for_one_method(self):
        base=[self.ranking('lexical','q1',['a']),self.ranking('semantic','q1',['b'])]
        first=fuse_rankings(base)
        repeated=fuse_rankings(base+[self.ranking('lexical','q2',['a'])])
        self.assertEqual([(x['concept_id'],x['fusion_score']) for x in first['candidates']],
                         [(x['concept_id'],x['fusion_score']) for x in repeated['candidates']])

    def test_duplicate_rankings_nonfinite_values_and_fake_duplicate_candidates_fail(self):
        item=self.ranking('lexical','q',['a'])
        for lists in ([item,item],[self.ranking('lexical','q',['a','a'])]):
            with self.assertRaises(ContextError):fuse_rankings(lists)
        item['candidates'][0]['score']=float('nan')
        with self.assertRaises(ContextError):fuse_rankings([item])

    def bundle(self):
        folder=self.root/'bundle';folder.mkdir()
        data=pack();plan=prepare_queries(data)
        for name,payload in {**data,'queries':plan}.items():write_json(folder/(name+'.json'),payload)
        write_json(folder/'manifest.json',{'files':{p.name:sha256(p) for p in folder.iterdir() if p.is_file()}})
        return folder

    def test_bundle_is_rebuilt_from_evidence_not_just_trusted_by_hash(self):
        folder=self.bundle()
        p=load_bundle(folder)
        self.assertEqual(p['code'],'C76.0')
        p['queries'][0]['text']='Texto inventado sin respaldo'
        p.pop('plan_sha256');p['plan_sha256']=digest(p)
        write_json(folder/'queries.json',p)
        manifest=json.loads((folder/'manifest.json').read_text())
        manifest['files']['queries.json']=sha256(folder/'queries.json')
        write_json(folder/'manifest.json',manifest)
        with self.assertRaises(ContextError):load_bundle(folder)

    def test_missing_catalog_blocks_without_loading_a_model_or_faking_no_candidates(self):
        result=run_hybrid(self.bundle(),self.root/'missing',self.root/'blocked')
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['candidates'],[])
        self.assertFalse(result['retrieval_started'])
        self.assertFalse(result['snomed_search_executed'])
        self.assertTrue((self.root/'blocked/result.md').exists())

    def fhir(self,mutation=None):
        data={'resourceType':'Parameters','parameter':[{'name':'version','valueString':EDITION},
            {'name':'display','valueString':'Término de prueba de respuesta simulada'},
            {'name':'property','part':[{'name':'code','valueCode':'inactive'},{'name':'value','valueBoolean':False}]}]}
        if mutation:mutation(data)
        self.requested=[]
        def transport(path):
            self.requested.append(path)
            if path.startswith('/CodeSystem?'):
                return {'resourceType':'Bundle','entry':[{'resource':{'resourceType':'CodeSystem','url':'http://snomed.info/sct','version':EDITION}}]}
            return data
        return SnowstormFHIR('http://localhost:8081/fhir',EDITION,transport)

    def test_fhir_always_pins_version_and_checks_active_status(self):
        f=self.fhir();f.require_version()
        result=f.lookup_active('100000')
        self.assertTrue(result['active'])
        self.assertTrue(all('version=' in p for p in self.requested))
        self.assertIn('code=100000',self.requested[-1])

    def test_fhir_other_edition_inactive_or_operation_outcome_are_rejected(self):
        mutations=[lambda d:d['parameter'][0].__setitem__('valueString','other'),
                   lambda d:d['parameter'][2]['part'][1].__setitem__('valueBoolean',True),
                   lambda d:d.__setitem__('resourceType','OperationOutcome')]
        for i,m in enumerate(mutations):
            with self.subTest(i=i),self.assertRaises(ContextError):self.fhir(m).lookup_active('100000')

    def test_empty_server_is_not_accepted_as_a_resolved_catalog(self):
        f=SnowstormFHIR('http://localhost:8081/fhir',EDITION,lambda path:{'resourceType':'Bundle','total':0})
        with self.assertRaises(ContextError):f.require_version()
        with self.assertRaises(ContextError):self.fhir().lookup_active('fixture:renal')


if __name__=='__main__':unittest.main()

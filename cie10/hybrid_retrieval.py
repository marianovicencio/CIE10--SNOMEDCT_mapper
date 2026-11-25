"""Persistent local lexical/encoder retrieval. Output is an unreviewed pool."""
from collections import defaultdict
from datetime import datetime, timezone
import heapq
import importlib.metadata
import json
import math
from pathlib import Path
import sqlite3
import time

from .mapping_context import ContextError, digest
from .retrieval_evaluation import TransformerRetriever, normalize, sha256, write_json
from .retrieval_queries import check_token_budget, prepare_queries, queries_for_encoding
from .snomed_catalog import SYSTEM, aliases_from, load_catalog

VERSION='0.1.0'


def load_bundle(folder):
    folder=Path(folder)
    manifest=json.loads((folder/'manifest.json').read_text())
    for name in ('context.json','audit.json','queries.json'):
        if sha256(folder/name)!=manifest.get('files',{}).get(name):raise ContextError('Cambió el paquete: '+name)
    pack={name:json.loads((folder/(name+'.json')).read_text()) for name in ('context','audit')}
    plan=json.loads((folder/'queries.json').read_text())
    rebuilt=prepare_queries(pack,plan['max_queries'])
    for key in ('queries','segments','review_context','policy','context_sha256','audit_sha256','implementation_sha256'):
        if key=='queries':
            actual=[{k:v for k,v in q.items() if k not in ('tokens','encoding_status')} for q in plan[key]]
            expected=[{k:v for k,v in q.items() if k not in ('tokens','encoding_status')} for q in rebuilt[key]]
        else:actual,expected=plan[key],rebuilt[key]
        if actual!=expected:raise ContextError('El plan no corresponde a sus fuentes o versión: '+key)
    if plan.get('plan_sha256')!=digest({k:v for k,v in plan.items() if k!='plan_sha256'}):
        raise ContextError('La huella del plan no coincide.')
    return plan


def preflight(tokenizer, texts, max_length, identifiers):
    for text,identifier in zip(texts,identifiers,strict=True):
        n=len(tokenizer(text,add_special_tokens=True,truncation=False)['input_ids'])
        if n>max_length:raise ContextError(f'No se recorta {identifier}: {n} tokens exceden {max_length}.')


def build_index(catalog, output, spec, device='cuda', max_catalog_tokens=256, batch_size=8, allow_fixture=False):
    import numpy as np
    catalog,output=Path(catalog),Path(output)
    meta=load_catalog(catalog,allow_fixture)
    if type(max_catalog_tokens) is not int or not 4<=max_catalog_tokens<=512:
        raise ContextError('Presupuesto de tokens del catálogo inválido.')
    if output.exists():raise ContextError('El índice de salida ya existe.')
    output.mkdir(parents=True)
    info={'status':'building','schema_version':VERSION,'catalog_path':str(catalog.resolve()),
        'catalog_manifest_sha256':sha256(catalog/'catalog.json'),'catalog':meta,'model':spec,
        'catalog_max_tokens':max_catalog_tokens,'batch_size':batch_size,'device':device,
        'implementation_sha256':sha256(__file__),'lexical_method':'sqlite_fts5_bm25_unicode61',
        'encoder_implementation_sha256':sha256(Path(__file__).with_name('retrieval_evaluation.py')),
        'packages':{p:importlib.metadata.version(p) for p in ('torch','transformers','numpy')},
        'embedding':{'pooling':'cls','normalization':'l2','dtype':'float32'}}
    write_json(output/'index.json',info)
    engine=None
    db=sqlite3.connect(output/'aliases.sqlite')
    started=time.perf_counter()
    try:
        db.executescript("PRAGMA journal_mode=OFF; PRAGMA temp_store=FILE; CREATE TABLE aliases(alias_no INTEGER PRIMARY KEY,concept_id TEXT NOT NULL,term TEXT NOT NULL,description_id TEXT,normalized TEXT NOT NULL,UNIQUE(concept_id,term)); CREATE VIRTUAL TABLE lexical USING fts5(normalized,content='aliases',content_rowid='alias_no',tokenize='unicode61 remove_diacritics 2');")
        i=0
        for i,row in enumerate(aliases_from(catalog,meta),1):
            db.execute('INSERT INTO aliases VALUES (?,?,?,?,?)',(i,row['concept_id'],row['term'],row.get('description_id'),normalize(row['term'])))
        if not i:raise ContextError('El catálogo está vacío.')
        if i!=meta['counts']['aliases']:raise ContextError('El número de alias no coincide con el manifiesto.')
        count=db.execute('SELECT COUNT(DISTINCT concept_id) FROM aliases').fetchone()[0]
        if count!=meta['counts']['concepts']:raise ContextError('El número de conceptos no coincide.')
        db.execute("INSERT INTO lexical(lexical) VALUES ('rebuild')")
        db.commit()
        engine=TransformerRetriever(spec,device,str(Path(__file__).resolve().parents[1]/'infra/retrieval/model-cache'),max_catalog_tokens,batch_size)
        matrix=None
        cursor=db.execute('SELECT alias_no,concept_id,term FROM aliases ORDER BY alias_no')
        offset=0
        while rows:=cursor.fetchmany(256):
            texts=[r[2] for r in rows]; identifiers=[str(r[0]) for r in rows]
            preflight(engine.tokenizer,texts,max_catalog_tokens,identifiers)
            values=engine.encode(texts,identifiers,'catalog')
            if not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values,axis=1),1,atol=1e-4):
                raise ContextError('Embeddings no finitos o sin normalizar.')
            if matrix is None:matrix=np.lib.format.open_memmap(output/'embeddings.npy',mode='w+',dtype='float32',shape=(i,values.shape[1]))
            matrix[offset:offset+len(rows)]=values
            offset+=len(rows)
        matrix.flush()
        info.update(status='completed',aliases=i,concepts=count,embedding_dimension=int(matrix.shape[1]),
            index_bytes=int(matrix.nbytes),seconds=time.perf_counter()-started,
            gpu_peak_allocated_bytes=engine.torch.cuda.max_memory_allocated() if device=='cuda' else None)
        del matrix
        db.close();db=None
        if sha256(catalog/'catalog.json')!=info['catalog_manifest_sha256'] or sha256(catalog/'catalog.jsonl')!=meta['files']['catalog.jsonl']:
            raise ContextError('El catálogo cambió durante la indexación.')
        info['files']={p:sha256(output/p) for p in ('aliases.sqlite','embeddings.npy')}
        write_json(output/'index.json',info)
        return info
    except Exception as e:
        info.update(status='failed',error=str(e));write_json(output/'index.json',info);raise
    finally:
        if db is not None:db.close()
        if engine is not None:engine.close()


def lexical_search(db, text, k):
    # Terms are quoted individually; input cannot become FTS/SQL syntax.
    stop={'de','del','el','la','los','las','un','una','y','o','en','por','con','al'}
    tokens=sorted(set(normalize(text).split())-stop)
    if not tokens:return []
    expression=' OR '.join('"'+t+'"' for t in tokens)
    cursor=db.execute('SELECT a.concept_id,a.term,a.description_id,bm25(lexical) score FROM lexical JOIN aliases a ON a.alias_no=lexical.rowid WHERE lexical MATCH ? ORDER BY score,a.concept_id,a.term',(expression,))
    result=[];seen=set()
    for concept,term,description,score in cursor:
        if concept in seen:continue
        seen.add(concept)
        result.append({'concept_id':concept,'term':term,'description_id':description,'score':-float(score)})
        if len(result)==k:break
    return result


def semantic_search(db, matrix, vector, k, chunk_size=8192):
    import numpy as np
    best={}
    cursor=db.execute('SELECT alias_no,concept_id,term,description_id FROM aliases ORDER BY alias_no')
    offset=0
    while rows:=cursor.fetchmany(chunk_size):
        scores=matrix[offset:offset+len(rows)]@vector
        if not np.isfinite(scores).all():raise ContextError('Puntuación semántica no finita.')
        for row,score in zip(rows,scores,strict=True):
            alias,concept,term,description=row
            item={'concept_id':concept,'term':term,'description_id':description,'score':float(score)}
            old=best.get(concept)
            if old is None or item['score']>old['score'] or (item['score']==old['score'] and term<old['term']):best[concept]=item
        offset+=len(rows)
    if offset!=len(matrix):raise ContextError('El índice vectorial y sus alias no coinciden.')
    return heapq.nsmallest(k,best.values(),key=lambda x:(-x['score'],x['concept_id']))


def fuse_rankings(rankings, top_k=10, rrf_constant=60):
    if type(top_k) is not int or not 1<=top_k<=20 or type(rrf_constant) is not int or rrf_constant<1:
        raise ContextError('Presupuesto o constante de fusión inválidos.')
    matches=defaultdict(list);seen_lists=set()
    for listing in rankings:
        method,query_id=listing['method'],listing['query_id']
        if method not in ('lexical','semantic') or (method,query_id) in seen_lists:raise ContextError('Ranking duplicado o método no admitido.')
        seen_lists.add((method,query_id));ids=set()
        for rank,candidate in enumerate(listing['candidates'],1):
            c=candidate['concept_id']
            if c in ids or not math.isfinite(candidate['score']):raise ContextError('Ranking con conceptos duplicados o puntuación no finita.')
            ids.add(c)
            matches[c].append({**candidate,'query_id':query_id,'method':method,'rank':rank})
    fused=[]
    for c,support in matches.items():
        best={m:min((x['rank'] for x in support if x['method']==m),default=None) for m in ('lexical','semantic')}
        score=sum(.5/(rrf_constant+r) for r in best.values() if r is not None)
        display=min(support,key=lambda x:(x['rank'],x['method'],x['query_id'],x['term']))
        fused.append({'concept_id':c,'display':display['term'],'display_language':'es',
            'display_is_preferred_term':False,'fusion_score':score,'best_rank_by_method':best,'matches':support,
            'status':'retrieved_unreviewed','patient_assertion':False})
    fused.sort(key=lambda x:(-x['fusion_score'],x['concept_id']))
    return {'candidates':[{**x,'rank':i} for i,x in enumerate(fused[:top_k],1)],
        'pool_concepts':len(fused),'truncated':len(fused)>top_k,
        'method':'equal_method_weight_best_rank_rrf','rrf_constant':rrf_constant,
        'score_is_probability':False,'multiple_query_votes_per_method':False}


def run_hybrid(bundle, index, output, pool_k=50, top_k=10, device='cuda', allow_fixture=False, fhir=None):
    from .snowstorm_verification import SnowstormFHIR
    output,index=Path(output),Path(index)
    if output.exists():raise ContextError('La salida de búsqueda ya existe.')
    output.mkdir(parents=True)
    report={'status':'running','created_at':datetime.now(timezone.utc).isoformat(),'candidates':[],
        'snomed_search_executed':False,'retrieval_started':False,'clinical_validation':False,'selection':'not_evaluated',
        'mapping_contract_response':False,'proposed_equivalence':False,'automatic_recoding':False}
    engine=None;db=None
    try:
        plan=load_bundle(bundle)
        report.update(code=plan['code'],input_mode=plan['input_mode'],plan_sha256=plan['plan_sha256'],
            query_bundle_path=str(Path(bundle).resolve()),source_snapshot_sha256=plan['source_snapshot_sha256'],
            context_sha256=plan['context_sha256'])
        if not (index/'index.json').is_file():
            report.update(status='blocked',blocker='target_catalog_or_index_unavailable');return report
        if type(pool_k) is not int or not 1<=pool_k<=1000 or type(top_k) is not int or not 1<=top_k<=20:
            raise ContextError('Presupuesto de candidatos inválido.')
        info=json.loads((index/'index.json').read_text())
        if info.get('status')!='completed':raise ContextError('El índice está incompleto.')
        if info.get('implementation_sha256')!=sha256(__file__) or info.get('encoder_implementation_sha256')!=sha256(Path(__file__).with_name('retrieval_evaluation.py')):
            raise ContextError('La implementación cambió; se requiere reconstruir el índice.')
        if any(importlib.metadata.version(p)!=v for p,v in info['packages'].items()):
            raise ContextError('El entorno del índice cambió; se requiere reconstruirlo.')
        catalog=Path(info['catalog_path']);meta=load_catalog(catalog,allow_fixture)
        if sha256(catalog/'catalog.json')!=info['catalog_manifest_sha256']:raise ContextError('La revisión del catálogo cambió.')
        for name in ('aliases.sqlite','embeddings.npy'):
            if sha256(index/name)!=info['files'][name]:raise ContextError('Cambió un archivo del índice: '+name)
        requested=plan['policy'].get('target_version')
        if requested and requested!=meta['version']:raise ContextError('El catálogo no corresponde a la versión solicitada.')
        if fhir and meta['kind']!='snomed_rf2_snapshot':raise ContextError('Los datos sintéticos no se envían a Snowstorm.')
        verifier=SnowstormFHIR(fhir,meta['version']) if fhir else None
        if verifier:
            report['fhir_version_verification']=verifier.require_version()
            report['fhir_base_url']=fhir
        spec=info['model'];max_tokens=64
        engine=TransformerRetriever(spec,device,str(Path(__file__).resolve().parents[1]/'infra/retrieval/model-cache'),max_tokens,8)
        checked=check_token_budget(plan,engine.tokenizer,max_tokens,spec)
        write_json(output/'queries-checked.json',checked)
        queries=queries_for_encoding(checked,spec,max_tokens)
        import numpy as np
        matrix=np.load(index/'embeddings.npy',mmap_mode='r',allow_pickle=False)
        if matrix.shape!=(info['aliases'],info['embedding_dimension']) or matrix.dtype!=np.float32:
            raise ContextError('Forma o tipo del índice incorrectos.')
        db=sqlite3.connect((index/'aliases.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        report['retrieval_started']=True
        encoded=engine.encode([q['text'] for q in queries],[q['id'] for q in queries],'query')
        rankings=[];started=time.perf_counter()
        for q,vector in zip(queries,encoded,strict=True):
            for method,candidates in [('lexical',lexical_search(db,q['text'],pool_k)),
                                      ('semantic',semantic_search(db,matrix,vector,pool_k))]:
                rankings.append({'query_id':q['id'],'method':method,'candidates':candidates})
        report['snomed_search_executed']=meta['kind']=='snomed_rf2_snapshot'
        write_json(output/'rankings.json',rankings)
        fused=fuse_rankings(rankings,top_k)
        for candidate in fused['candidates']:
            candidate['catalog_verification']='member_of_indexed_fixture' if meta['kind']=='synthetic_fixture' else 'active_in_supplied_rf2_snapshot'
            if verifier:candidate['fhir_verification']=verifier.lookup_active(candidate['concept_id'])
        report.update(status='fixture_candidates_retrieved' if meta['kind']=='synthetic_fixture' else 'candidates_retrieved_unreviewed',
            target={'system':meta['system'],'version':meta['version'],'catalog_kind':meta['kind'],
                    'coverage':meta['coverage'],'edition_binding':meta.get('edition_binding')},
            candidates=fused['candidates'],fusion={k:v for k,v in fused.items() if k!='candidates'},
            snomed_search_executed=meta['kind']=='snomed_rf2_snapshot',pool_k_per_method_per_query=pool_k,
            top_k=top_k,query_ids=[q['id'] for q in queries],query_plan=checked,
            retrieval_seconds=time.perf_counter()-started,model=spec,device=device,
            gpu_peak_allocated_bytes=engine.torch.cuda.max_memory_allocated() if device=='cuda' else None,
            index_manifest_sha256=sha256(index/'index.json'),
            implementation_sha256=sha256(__file__),
            limitations=['Solo se explora el catálogo local configurado y el pool recuperado.',
                'No se evaluaron negación, temporalidad, causalidad, exclusiones ni pertinencia al caso.',
                'Las inclusiones exploradas son alternativas; no implican diagnósticos coexistentes.',
                'El ranking no constituye correspondencia ni explicación clínica aprobada.'])
        report.pop('query_plan')
        return report
    except Exception as e:
        report.update(status='blocked',blocker=str(e),candidates=[])
        raise
    finally:
        if engine is not None:engine.close()
        if db is not None:db.close()
        write_json(output/'result.json',report)
        rows=['# Recuperación combinada: '+report.get('code',''),'',report['status'],'',
              'Candidatos sin revisión clínica. Un puntaje de fusión no es probabilidad ni equivalencia.','',
              '| ID | Término recuperado | Posición textual | Posición semántica |','|---|---|---:|---:|']
        for c in report['candidates']:
            rows.append('| '+c['concept_id']+' | '+c['display'].replace('|','\\|')+' | '+str(c['best_rank_by_method']['lexical'])+' | '+str(c['best_rank_by_method']['semantic'])+' |')
        if report.get('blocker'):rows+=['','Motivo: '+report['blocker']]
        if report['status'].startswith('fixture'):rows+=['','Datos sintéticos: estos identificadores NO son SCTID ni propuestas SNOMED.']
        (output/'result.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')

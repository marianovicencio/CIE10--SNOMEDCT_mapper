"""Read the immutable v2 index in bounded blocks without retaining its file cache.

This changes I/O only. Encoding and ranking are unchanged. Source fingerprints are checked against
the exact build or an explicitly audited refactor; index files remain immutable.
"""
import os
import sqlite3
import heapq
import importlib.metadata
import json
import time
from datetime import datetime,timezone
from pathlib import Path
from .full_retrieval import load_bundle,lexical_search,semantic_search_batch,fuse_rankings
from .mapping_context import ContextError
from .retrieval_core import TransformerRetriever,sha256,write_json
from .retrieval_queries import check_token_budget,queries_for_encoding
from .snomed_catalog import load_catalog
from .retrieval_configuration import verify_index_implementation


def streamed_sha256(path):
    """Check every byte without retaining gigabytes of consumed file cache."""
    import hashlib
    h=hashlib.sha256();offset=0
    with open(path,'rb',buffering=0) as stream:
        if hasattr(os,'posix_fadvise'):os.posix_fadvise(stream.fileno(),0,0,os.POSIX_FADV_RANDOM)
        while block:=stream.read(4*1024*1024):
            h.update(block)
            if hasattr(os,'posix_fadvise'):os.posix_fadvise(stream.fileno(),offset,len(block),os.POSIX_FADV_DONTNEED)
            offset+=len(block)
    return h.hexdigest()


class StreamedMatrix:
    def __init__(self,path,offset,shape,dtype):
        import numpy as np
        self.shape=shape;self.dtype=np.dtype(dtype);self.offset=int(offset)
        self.fd=os.open(path,os.O_RDONLY)
        if hasattr(os,'posix_fadvise'):
            os.posix_fadvise(self.fd,0,0,os.POSIX_FADV_RANDOM)

    def __len__(self):return self.shape[0]

    def __getitem__(self,key):
        import numpy as np
        if not isinstance(key,slice) or key.step not in (None,1):raise ContextError('Se requiere un bloque contiguo.')
        start,end,step=key.indices(len(self));count=max(0,end-start)
        position=self.offset+start*self.shape[1]*self.dtype.itemsize
        size=count*self.shape[1]*self.dtype.itemsize
        chunks=[];read=0
        while read<size:
            chunk=os.pread(self.fd,size-read,position+read)
            if not chunk:raise ContextError('Lectura incompleta del índice.')
            chunks.append(chunk);read+=len(chunk)
        data=chunks[0] if len(chunks)==1 else b''.join(chunks)
        # The array owns a bounded bytes buffer, so file-cache pages can be freed.
        if size and hasattr(os,'posix_fadvise'):
            os.posix_fadvise(self.fd,position,size,os.POSIX_FADV_DONTNEED)
        return np.frombuffer(data,dtype=self.dtype).reshape(count,self.shape[1])

    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None


def run_hybrid(bundle, index, output, pool_k=50, top_k=10, device='cuda', allow_fixture=False, fhir=None, plan_loader=None, lexical_searcher=None):
    from .snowstorm_verification import SnowstormFHIR
    output,index=Path(output),Path(index)
    if output.exists():raise ContextError('La salida de búsqueda ya existe.')
    output.mkdir(parents=True)
    report={'status':'running','created_at':datetime.now(timezone.utc).isoformat(),'candidates':[],
        'snomed_search_executed':False,'retrieval_started':False,'clinical_validation':False,'selection':'not_evaluated',
        'mapping_contract_response':False,'proposed_equivalence':False,'automatic_recoding':False}
    engine=None;db=None;matrix=None
    try:
        plan=(plan_loader or load_bundle)(bundle)
        report.update(code=plan['code'],input_mode=plan['input_mode'],plan_sha256=plan['plan_sha256'],
            query_bundle_path=str(Path(bundle).resolve()),source_snapshot_sha256=plan['source_snapshot_sha256'],
            context_sha256=plan['context_sha256'])
        if not (index/'index.json').is_file():
            report.update(status='blocked',blocker='target_catalog_or_index_unavailable');return report
        if type(pool_k) is not int or not 1<=pool_k<=1000 or type(top_k) is not int or not 1<=top_k<=20:
            raise ContextError('Presupuesto de candidatos inválido.')
        info=json.loads((index/'index.json').read_text())
        if info.get('schema_version')!='0.2.0':raise ContextError('Formato de índice incompatible.')
        if info.get('status')!='completed':raise ContextError('El índice está incompleto.')
        report['implementation_verification'] = verify_index_implementation(info)
        if any(importlib.metadata.version(p)!=v for p,v in info['packages'].items()):
            raise ContextError('El entorno del índice cambió; se requiere reconstruirlo.')
        catalog=Path(info['catalog_path']);meta=load_catalog(catalog,allow_fixture)
        if sha256(catalog/'catalog.json')!=info['catalog_manifest_sha256']:raise ContextError('La revisión del catálogo cambió.')
        for name in ('aliases.sqlite','embeddings.npy'):
            if streamed_sha256(index/name)!=info['files'][name]:raise ContextError('Cambió un archivo del índice: '+name)
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
        offset,shape,dtype=matrix.offset,matrix.shape,matrix.dtype
        matrix._mmap.close()
        matrix=StreamedMatrix(index/'embeddings.npy',offset,shape,dtype)
        report['index_read_strategy']='bounded_pread_drop_consumed_file_cache'
        db=sqlite3.connect((index/'aliases.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        report['retrieval_started']=True
        encoded=engine.encode([q['text'] for q in queries],[q['id'] for q in queries],'query')
        rankings=[];started=time.perf_counter()
        semantic_rankings=semantic_search_batch(db,matrix,encoded,pool_k)
        for q,semantic in zip(queries,semantic_rankings,strict=True):
            for method,candidates in [('lexical',lexical_searcher(db,q,pool_k) if lexical_searcher else lexical_search(db,q['text'],pool_k)),
                                      ('semantic',semantic)]:
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
        if matrix is not None and hasattr(matrix,'close'):matrix.close()
        write_json(output/'result.json',report)
        rows=['# Recuperación combinada: '+report.get('code',''),'',report['status'],'',
              'Candidatos sin revisión clínica. Un puntaje de fusión no es probabilidad ni equivalencia.','',
              '| ID | Término recuperado | Posición textual | Posición semántica |','|---|---|---:|---:|']
        for c in report['candidates']:
            rows.append('| '+c['concept_id']+' | '+c['display'].replace('|','\\|')+' | '+str(c['best_rank_by_method']['lexical'])+' | '+str(c['best_rank_by_method']['semantic'])+' |')
        if report.get('blocker'):rows+=['','Motivo: '+report['blocker']]
        if report['status'].startswith('fixture'):rows+=['','Datos sintéticos: estos identificadores NO son SCTID ni propuestas SNOMED.']
        (output/'result.md').write_text('\n'.join(rows)+'\n',encoding='utf-8')

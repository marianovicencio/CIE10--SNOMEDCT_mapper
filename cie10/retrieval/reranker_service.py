"""Optional local shortlist permutation. User explanations remain on demand."""
import fcntl,json,tempfile,time
from pathlib import Path
from cie10.retrieval.shortlist_reranker import (
    LocalCrossEncoder,
    apply_scores,
    query_text,
    scope_status,
    REPOSITORY,
    REVISION,
    POLICY,
)
from cie10.retrieval.full_retrieval_runtime import streamed_sha256
from cie10.retrieval.retrieval_core import sha256
from cie10.api.mapping_context import ContextError, digest


def published_fsns(root,index_info,ids):
    root=Path(root).resolve();catalog=Path(index_info['catalog_path']).resolve()
    if not catalog.is_relative_to(root/'data/catalogs/snomed'):raise ContextError('Catálogo fuera del proyecto.')
    if sha256(catalog/'catalog.json')!=index_info['catalog_manifest_sha256']:raise ContextError('Cambió el catálogo.')
    meta=json.loads((catalog/'catalog.json').read_text())
    if streamed_sha256(catalog/'catalog.jsonl')!=meta['files']['catalog.jsonl']:raise ContextError('Cambió el texto del catálogo.')
    wanted=set(ids);found={}
    with (catalog/'catalog.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            if row['concept_id'] in wanted and row['description_type_id']=='900000000000003001':
                if row.get('active') is not True or row.get('language')!='es':raise ContextError('FSN no activo o no español.')
                found[row['concept_id']]=row['term']
                if len(found)==len(wanted):break
    if set(found)!=wanted:raise ContextError('Falta un nombre oficial del candidato.')
    return [found[cid] for cid in ids]


def apply_configured_reranker(result,request,plan,index,index_info,root):
    root=Path(root);config_path=root/'infra/retrieval/active-reranker.json';started=time.perf_counter()
    def unchanged(reason):
        return {**result,'reranking':{'applied':False,'reason':reason,'policy':POLICY,'same_candidate_set':True,'automatic_selection':False,'score_is_probability':False}}
    if not config_path.is_file():return unchanged('disabled')
    engine=None
    try:
        cfg=json.loads(config_path.read_text())
        if cfg.get('status')!='enabled_local_experimental':return unchanged('disabled')
        if (cfg.get('repository'),cfg.get('revision'),cfg.get('policy'))!=(REPOSITORY,REVISION,POLICY):raise ContextError('Configuración incompatible.')
        if sha256(Path(index)/'index.json')!=cfg['index_manifest_sha256']:raise ContextError('Edición de índice diferente.')
        for name,fingerprint in cfg['implementation_sha256'].items():
            if sha256(root/name)!=fingerprint:raise ContextError('La implementación cambió.')
        from cie10.reasoning.safety import scope_marker
        if scope_marker(request.get('diagnostic_text','')):
            return unchanged('hypothetical_scope_keep_baseline')
        status=scope_status(request.get('diagnostic_text',''))
        if status!='eligible_for_scoring':return unchanged(status)
        candidates=result['candidates'];ids=[c['concept_id'] for c in candidates]
        if len(ids)!=5 or len(set(ids))!=5:raise ContextError('Shortlist incompatible.')
        official=next(q['text'] for q in plan['queries'] if q['id']==plan['baseline_query_id'])
        query=query_text(official,request['diagnostic_text']);passages=published_fsns(root,index_info,ids)
        # Share the existing explanation lock; concurrent Gemma work keeps the baseline.
        with (Path(tempfile.gettempdir())/'magister-explanation-11435.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return unchanged('local_model_busy_baseline_retained')
            engine=LocalCrossEncoder(root)
            scores,lengths=engine.score(query,passages)
            ordered=apply_scores(candidates,dict(zip(ids,scores)))
            # Public rank denotes the displayed order; retrieval ranks stay in matches.
            ordered=[{**c,'rank':i} for i,c in enumerate(ordered,1)]
            return {**result,'candidates':ordered,'reranking':{'applied':True,'status':'experimental_unreviewed','repository':REPOSITORY,'revision':REVISION,'policy':POLICY,'same_candidate_set':True,'automatic_selection':False,'score_is_probability':False,'candidate_view':'published_spanish_fsn','pair_tokens':lengths,'elapsed_seconds':round(time.perf_counter()-started,3),'query_sha256':digest(query)}}
    except Exception:
        # This optional stage must not discard an already verified baseline.
        return unchanged('reranker_unavailable_baseline_retained')
    finally:
        if engine is not None:engine.close()

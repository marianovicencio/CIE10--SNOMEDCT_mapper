"""Local Nuxt bridge. Read one request from stdin; emit a compact response."""
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cie10.retrieval_configuration import load_active_index
from cie10.mapping_context import ContextError, MappingContextClient
from cie10.retrieval_evaluation import sha256, write_json
from cie10.retrieval_queries import prepare_queries

FHIR = 'http://127.0.0.1:8081/fhir'


def compact_result(result, plan):
    keys = ('status', 'code', 'input_mode', 'target', 'fusion', 'top_k', 'clinical_validation')
    out = {key: result[key] for key in keys if key in result}
    out['queries'] = [{k: q[k] for k in ('id', 'kind', 'text')} for q in plan['queries']]
    if 'qualifier_ordering' in result:
        out['qualifier_ordering'] = result['qualifier_ordering']
    if 'query_preparation' in result:
        out['query_preparation'] = result['query_preparation']
    if 'reranking' in result:
        out['reranking'] = result['reranking']
    out['candidates'] = [{
        'id': c['concept_id'], 'term': c['display'], 'rank': c['rank'],
        **{k: c[k] for k in ('baseline_rank', 'reranker_score', 'pre_qualifier_rank') if k in c},
        'active': c.get('fhir_verification', {}).get('active') is True,
        'methods': c['best_rank_by_method'],
        'matches': [{k: m[k] for k in ('query_id', 'method', 'term', 'rank')} for m in c['matches']],
    } for c in result['candidates']]
    return out


def catalog_status():
    index, info = load_active_index(ROOT)
    return {'name': index.name, 'concepts': info['concepts'], 'aliases': info['aliases'],
            'version': info['catalog']['version'], 'coverage': info['catalog']['coverage']}


def search(request):
    if not isinstance(request, dict) or not re.fullmatch(r'[A-Z][0-9]{2}(?:\.[0-9]{1,2})?', request.get('code', '')):
        raise ContextError('Código inválido.')
    request = {**request, 'scope': 'morbidity', 'top_k': 5}
    index, index_info = load_active_index(ROOT)
    if index_info['schema_version'] == '0.2.0':
        from cie10.full_retrieval_runtime import run_hybrid
    else:
        from cie10.hybrid_retrieval import run_hybrid
    pack = MappingContextClient().prepare(request)
    from cie10 import retrieval_title_fragments as fragments
    use_fragments = index_info['schema_version'] == '0.2.0' and fragments.enabled(ROOT, index)
    plan = fragments.prepare_queries(pack) if use_fragments else prepare_queries(pack)
    runtime_options = {'plan_loader': fragments.load_bundle, 'lexical_searcher': fragments.search_lexical} if use_fragments else {}
    with tempfile.TemporaryDirectory(prefix='magister-web-') as directory:
        work = Path(directory)
        for name, value in {**pack, 'queries': plan}.items():
            write_json(work / (name + '.json'), value)
        write_json(work / 'manifest.json', {'files': {
            p.name: sha256(p) for p in work.iterdir()
        }})
        try:
            result = run_hybrid(work, index, work / 'result', pool_k=25, top_k=5, fhir=FHIR, **runtime_options)
        except ContextError:
            path = work / 'result/result.json'
            if not path.is_file():
                raise
            result = json.loads(path.read_text(encoding='utf-8'))
        if result['status'] == 'blocked':
            detail = result.get('blocker', '')
            if 'tokens' in detail:
                message = 'El diagnóstico o una variante supera el límite de búsqueda. Usa un texto más breve conservando los detalles relevantes.'
            else:
                message = 'La búsqueda no está disponible. Comprueba la conexión al catálogo local y a Snowstorm.'
            return {'status': 'blocked', 'code': request['code'], 'message': message}
        if use_fragments:
            result['query_preparation'] = {
                'policy': fragments.POLICY,
                'literal_fragment_queries': sum(q['kind'] == fragments.KIND for q in plan['queries']),
                'asserts_clinical_equivalence': False,
            }
        from cie10.reranker_service import apply_configured_reranker
        result = apply_configured_reranker(result, request, plan, index, index_info, ROOT)
        from cie10.reasoning.assertion_comparison import heading_conflict
        title = next(q['text'] for q in plan['queries'] if q['id'] == plan['baseline_query_id'])
        before = result['candidates']
        ordered = sorted(before, key=lambda c: heading_conflict(title, c['display']))
        if [c['concept_id'] for c in ordered] != [c['concept_id'] for c in before]:
            result['candidates'] = [{**c, 'pre_qualifier_rank': c['rank'], 'rank': i} for i,c in enumerate(ordered,1)]
            result['qualifier_ordering'] = {'policy':'aligned_assertion_polarity_v1','same_candidate_set':True,'automatic_selection':False}
        return compact_result(result, plan)


def terminate(*_):
    raise SystemExit(143)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, terminate)
    try:
        with redirect_stdout(sys.stderr):
            answer = catalog_status() if sys.argv[1:] == ['--catalog'] else search(json.load(sys.stdin))
        print(json.dumps(answer, ensure_ascii=False))
    except ContextError:
        print(json.dumps({'status': 'blocked', 'message': 'No se pudo preparar la consulta con la API documental local.'}, ensure_ascii=False))

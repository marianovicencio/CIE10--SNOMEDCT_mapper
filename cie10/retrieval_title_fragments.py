"""Explore bounded title fragments with exact offsets, never assert equivalence."""
from copy import deepcopy
import hashlib,json,re
from pathlib import Path
from . import retrieval_queries as legacy
from .mapping_context import ContextError,digest
from .retrieval_evaluation import normalize,sha256

VERSION='0.2.0'
KIND='official_title_bracket_fragment'
POLICY='code_only_terminal_bracket_prefix_v2'
LABELS={'benigno','benigna','maligno','maligna','agudo','aguda','cronico','cronica','primario','primaria','secundario','secundaria','simple','complicado','complicada','juvenil','neonatal','sai','ncop','organico','organica','adquirido','adquirida','traumatico','traumatica','afectivo','afectiva','persistente','sindrome','trastorno','enfermedad'}
SCOPE=re.compile(r'\b(?:sin|con|no|excepto|debida|debido|agud[ao]|cronic[ao]|congenit[ao]|tardi[ao]|transmitid[ao]|hereditari[ao]|especific[ao])\b')

def inspect_fragment(title):
    if title.count('[')!=1 or title.count(']')!=1:return None,'multiple_nested_or_unbalanced_brackets'
    m=re.search(r'\[([^\[\]]+)\]\s*$',title)
    if not m:return None,'bracket_not_terminal'
    start=m.start(1)+len(m[1])-len(m[1].lstrip());end=m.end(1)-(len(m[1])-len(m[1].rstrip()))
    text=title[start:end];plain=normalize(text)
    if legacy.CODE_MENTION.search(text) or re.search(r'\d',text):return None,'code_number_or_symbol_reference'
    if not re.fullmatch(r'[A-Za-zÁÉÍÓÚÜÑáéíóúüñ\s–-]+',text):return None,'fragment_not_plain_term'
    if len(text.encode('utf-8'))>48:return None,'literal_fragment_byte_budget'
    words=plain.split()
    if any(w in {'vease','ver','nota','notas','pagina','paginas','subdivision','subdivisiones','inciso'} for w in words):return None,'documentary_reference_not_term'
    if not words or plain in LABELS or plain.rstrip('s') in LABELS or (len(words)==1 and len(text)<=4 and text.isupper()) or words[0] in {'de','del','por','con','sin','en','a'}:return None,'qualifier_acronym_or_explanation_not_standalone'
    if SCOPE.search(normalize(title[:m.start()])):return None,'prefix_scope_or_qualifier_requires_full_heading'
    return {'text':text,'start':start,'end':end,'offset_unit':'unicode_code_points'},None


def prepare_queries(pack,max_queries=12):
    base=legacy.prepare_queries(pack,max_queries);plan=deepcopy(base)
    title_key=plan['original_title_segment'];source=plan['segments'][title_key];title=source['text'];held=[]
    if '[' in title or ']' in title:
        fragment,reason=inspect_fragment(title)
        primary=pack['audit']['records'][pack['audit']['classification']['heading_refs'][0]]
        if plan['input_mode']!='code_only':reason='diagnostic_present_preserve_existing_queries'
        elif pack['audit']['classification']['representation']!='explicit_heading':reason='shared_subdivision_requires_full_qualifiers'
        elif primary.get('structure_issues') or primary.get('semantic_review_issues'):reason='primary_source_requires_review'
        if reason:held.append({'reason':reason,'source_segment':title_key})
        elif len(plan['queries'])>=max_queries:held.append({'reason':'query_budget','source_segment':title_key})
        else:
            key='s:'+digest([source['container'],source['pointer'],fragment['start'],fragment['end'],KIND])[:20]
            plan['segments'][key]={**fragment,'container':source['container'],'pointer':source['pointer'],'source_text_sha256':source['text_sha256'],
                'text_sha256':hashlib.sha256(fragment['text'].encode()).hexdigest(),'evidence_refs':deepcopy(source['evidence_refs']),'role':KIND}
            qid='q:'+digest([KIND,fragment['text'],[key]])[:20]
            plan['queries'].append({'id':qid,'kind':KIND,'text':fragment['text'],'segment_refs':[key],'purpose':'literal_fragment_exploration_not_asserted_synonym_or_equivalence','patient_assertion':False,'encoding_status':'token_budget_not_checked'})
    plan.update(schema_version=VERSION,base_plan_sha256=base['plan_sha256'],base_implementation_sha256=base['implementation_sha256'],implementation_sha256=sha256(__file__),title_fragment_review=held)
    plan['policy'].update(fragment_lexical_prefix_expansion=True,method=POLICY,literal_title_fragment_queries=True,fragments_assert_clinical_equivalence=False,fragments_apply_only_without_diagnostic=True)
    plan['plan_sha256']=digest({k:v for k,v in plan.items() if k!='plan_sha256'})
    return plan


def load_bundle(folder):
    folder=Path(folder);plan=json.loads((folder/'queries.json').read_text())
    if plan.get('schema_version')==legacy.VERSION:
        from .full_retrieval import load_bundle as load_legacy
        return load_legacy(folder)
    if plan.get('schema_version')!=VERSION:raise ContextError('Formato de consultas no admitido.')
    manifest=json.loads((folder/'manifest.json').read_text())
    for name in ('context.json','audit.json','queries.json'):
        if sha256(folder/name)!=manifest.get('files',{}).get(name):raise ContextError('Cambió el paquete: '+name)
    pack={name:json.loads((folder/(name+'.json')).read_text()) for name in ('context','audit')}
    rebuilt=prepare_queries(pack,plan.get('max_queries'))
    if rebuilt!=plan:raise ContextError('El plan no corresponde a sus fuentes, intervalos o versión.')
    return plan


def enabled(root,index):
    root=Path(root);config=root/'infra/retrieval/active-query-variants.json'
    if not config.is_file():return False
    try:
        cfg=json.loads(config.read_text())
        return cfg.get('status')=='enabled_local_experimental' and cfg.get('policy')==POLICY and cfg.get('index_manifest_sha256')==sha256(Path(index)/'index.json') and all(sha256(root/name)==value for name,value in cfg['implementation_sha256'].items())
    except (OSError,ValueError,KeyError,TypeError):return False


def search_lexical(db,query,k):
    from .full_retrieval import lexical_search as legacy_search
    if query.get('kind')!=KIND:return legacy_search(db,query['text'],k)
    stop={'de','del','el','la','los','las','un','una','y','o','en','por','con','al'}
    tokens=sorted(set(normalize(query['text']).split())-stop)
    if not tokens:return []
    # Search expansion, not a rewritten diagnosis or a clinical equivalence rule.
    expression=fragment_expression(query['text'])
    cursor=db.execute('SELECT a.concept_id,a.term,a.description_id,bm25(lexical) score FROM lexical JOIN aliases a ON a.alias_no=lexical.rowid WHERE lexical MATCH ? ORDER BY score,a.concept_id,a.term',(expression,))
    result=[];seen=set()
    for cid,term,description,score in cursor:
        if cid in seen:continue
        seen.add(cid);result.append({'concept_id':cid,'term':term,'description_id':description,'score':-float(score)})
        if len(result)==k:break
    return result


def fragment_expression(text):
    stop={'de','del','el','la','los','las','un','una','y','o','en','por','con','al'}
    tokens=sorted(set(normalize(text).split())-stop)
    return ' OR '.join('"'+(t[:-1] if t.endswith('s') and len(t)>=5 else t)+'"'+('*' if t.endswith('s') and len(t)>=5 else '') for t in tokens)

"""Prepare sourced search variants; never infer patient facts or SNOMED maps."""
from copy import deepcopy
import hashlib
from pathlib import Path
import re
from urllib.parse import quote, unquote

from cie10.api.context_readable import Reader
from cie10.api.mapping_context import ContextError, digest, validate_mapping_input

VERSION = '0.1.0'
CODE_MENTION = re.compile(r'\b[A-Z][0-9]{2}(?:\.[0-9])?|[†*\uf8fc-\uf8ff]')


def pointer_get(value, pointer):
    if not pointer.startswith('/'):
        raise ContextError('La ubicación debe ser un JSON Pointer absoluto.')
    for token in pointer[1:].split('/'):
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def prepare_queries(pack, max_queries=12):
    if type(max_queries) is not int or not 2 <= max_queries <= 64:
        raise ContextError('max_queries debe ser un entero entre 2 y 64.')
    context, audit = pack['context'], pack['audit']
    if context.get('context_sha256') != digest({k:v for k,v in context.items() if k != 'context_sha256'}):
        raise ContextError('La huella del contexto no coincide.')
    if context.get('context_selection'):
        raise ContextError('Se requiere el contexto íntegro, no una selección por pregunta.')
    request = validate_mapping_input(context['input'])
    reading = context['documentary_context']
    if reading['code'] != request['code'] or audit['code'] != request['code']:
        raise ContextError('Código inconsistente en los paquetes.')
    if not context.get('source_snapshot_sha256') or context['source_snapshot_sha256'] != audit.get('source_snapshot_sha256'):
        raise ContextError('La revisión de fuente no coincide.')
    if reading['edition'] != audit['edition']:
        raise ContextError('Las ediciones no coinciden.')
    for obj in (context, audit):
        r = obj['retrieval']
        if not r.get('all_selected_pages_retrieved') or r['selected_records'] != r['total_selected_records']:
            raise ContextError('Faltan páginas de contexto.')
    if not audit.get('pagination', {}).get('complete'):
        raise ContextError('La auditoría no está completa.')
    representation = reading['classification']['representation']
    if representation != audit['classification']['representation'] or representation not in ('explicit_heading', 'shared_subdivision'):
        raise ContextError('Representación del código no admitida.')
    reader = Reader(audit)
    headings = audit['classification']['heading_refs']
    if len(headings) != 1:
        raise ContextError('El título requiere revisión de sus encabezados.')
    primary = audit['records'][headings[0]]
    if reading['title'] != reader.text(primary.get('description', ''), primary) or not reading['title'].strip():
        raise ContextError('El título no corresponde al registro recuperado.')
    def compact_refs(value):
        if isinstance(value,dict):
            if '/v1/records/' in value.get('detail_url',''):
                ref = 'e:'+unquote(value['detail_url'].split('/v1/records/',1)[1])
                return {**{k:compact_refs(v) for k,v in value.items() if k not in ('source','detail_url','reading_url')},
                        'evidence_ref':ref}
            return {k:compact_refs(v) for k,v in value.items()}
        if isinstance(value,list):return [compact_refs(v) for v in value]
        return value
    for name, value in compact_refs(reader.tabular()).items():
        if reading['tabular'].get(name) != value:
            raise ContextError('El texto tabular no corresponde a la auditoría: '+name)

    segments, evidence, queries, held = {}, {}, [], []

    def cite(identifier):
        ref = 'e:'+identifier
        if ref in context['evidence']:
            evidence[ref] = deepcopy(context['evidence'][ref])
        else:
            record = audit['records'][identifier]
            sources = record.get('sources') or [record.get('source', {})]
            locs = [audit['source_locations'].get(s.get('source_ref'),s) for s in sources]
            documents = [audit['documents'][l['document_ref']] for l in locs if l.get('document_ref')]
            if not documents:
                raise ContextError('Falta la procedencia del registro '+identifier)
            evidence[ref] = {'record_id':identifier, 'volume':documents[0]['volume'],
                'pdf_pages':sorted({l['pdf_page'] for l in locs if l.get('pdf_page')}),
                'source_sha256':documents[0]['sha256'], 'detail_path':'/v1/records/'+quote(identifier,safe='')}
        evidence[ref]['source_review_status'] = audit['records'][identifier].get('review_status')
        evidence[ref]['source_warnings'] = deepcopy(audit['records'][identifier].get('warnings', []))
        return ref

    def segment(container, pointer, refs, role):
        text = pointer_get(pack[container], pointer)
        if not isinstance(text,str) or not text.strip():
            raise ContextError('Un segmento de búsqueda está vacío.')
        key = 's:'+digest([container,pointer])[:20]
        segments[key] = {'container':container, 'pointer':pointer, 'text':text,
            'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'evidence_refs':refs, 'role':role}
        return key

    def query(kind, refs, purpose):
        if len(queries) >= max_queries:
            held.append({'segment_refs':refs, 'reason':'query_budget', 'would_be_kind':kind})
            return
        text = ' — '.join(segments[r]['text'] for r in refs)
        key = 'q:'+digest([kind,text,refs])[:20]
        queries.append({'id':key, 'kind':kind, 'text':text, 'segment_refs':refs,
            'purpose':purpose, 'patient_assertion':False, 'encoding_status':'token_budget_not_checked'})
        return key

    title = segment('context','/documentary_context/title',[cite(headings[0])],'official_title')
    full_description = [title]
    if representation == 'shared_subdivision':
        expected_suffix = request['code'][3:]
        rows = audit['classification']['shared_subdivision_rows']
        rendered_rows = []
        if not rows or not any(rows):
            raise ContextError('La subdivisión compartida no tiene texto recuperado.')
        for i, group in enumerate(rows):
            for j, item in enumerate(group):
                row = item['row']
                if row['suffix'] != expected_suffix:
                    raise ContextError('La subdivisión no coincide con el código solicitado.')
                rendered_rows.append({'suffix':row['suffix'], 'text':reader.text(row['text'],audit['records'][item['scheme_ref']])})
                ref = segment('audit',f'/classification/shared_subdivision_rows/{i}/{j}/row/text',
                              [cite(item['scheme_ref'])],'shared_subdivision_qualifier')
                full_description.append(ref)
        if reading['classification'].get('subdivisions') != rendered_rows:
            raise ContextError('La subdivisión legible no coincide con la auditoría.')
    base = query('official_description',full_description,'baseline')
    if 'diagnostic_text' in request:
        source = context.get('input_evidence',{}).get('i:diagnostic_text',{})
        if source.get('text') != request['diagnostic_text'] or source.get('start') != 0 or source.get('end') != len(request['diagnostic_text']):
            raise ContextError('El diagnóstico original no conserva sus intervalos.')
        evidence['i:diagnostic_text'] = deepcopy(source)
        diagnostic = segment('context','/input/diagnostic_text',['i:diagnostic_text'],'user_diagnostic_text_unverified')
        query('diagnostic_original',[diagnostic],'user_text_as_data_not_instructions')
    parent_segments = []
    for i, item in enumerate(reading['classification'].get('hierarchy',[])):
        if not item.get('code') or item['code'] == request['code']:
            continue
        matches = [audit['records'][identifier] for identifier in audit['classification'].get('hierarchy_refs',[])
                   if audit['records'][identifier].get('code') == item['code']]
        if len(matches) != 1 or item['title'] != reader.text(matches[0].get('description',''),matches[0]):
            raise ContextError('La jerarquía legible no corresponde a la auditoría.')
        # An exact prefix already retained in the title adds no new wording.
        if reading['title'].casefold().startswith(item['title'].casefold()):
            continue
        parent_segments.append(segment('context',f'/documentary_context/classification/hierarchy/{i}/title',
                                       [cite(matches[0]['id'])],'coded_parent_heading'))
    if 'diagnostic_text' in request:
        query('description_with_diagnostic',parent_segments+full_description+[diagnostic],'sourced_augmentation_not_conflict_resolution')
    if parent_segments:
        query('description_with_hierarchy',parent_segments+full_description,'parent_heading_context_not_all_parent_diagnoses')
    for i, inclusion in enumerate(reading['tabular']['inclusions']):
        refs = []
        for ref in inclusion.get('references',[]):
            identifier = context['evidence'][ref['evidence_ref']]['record_id']
            refs.append(cite(identifier))
        inc = segment('context',f'/documentary_context/tabular/inclusions/{i}/text',refs,'official_inclusion')
        reason = None
        if inclusion.get('inherited') or inclusion.get('origin') != request['code']:
            reason = 'inherited_or_other_scope_not_a_subcode_assertion'
        elif inclusion.get('source_ambiguity_preserved') or inclusion.get('scope_statement') or inclusion.get('examples'):
            reason = 'conditional_example_or_source_ambiguity'
        elif CODE_MENTION.search(inclusion['text']):
            reason = 'code_reference_or_dual_coding_requires_context'
        elif primary.get('structure_issues') or primary.get('semantic_review_issues') or not refs:
            reason = 'source_requires_review'
        if reason:
            held.append({'segment_refs':[inc], 'reason':reason})
        else:
            query('description_with_inclusion',parent_segments+full_description+[inc],'alternative_term_exploration_not_coexisting_diagnoses')

    guards = []
    for name in ('exclusions','instructions','notes','general_context','coding_relations'):
        items = reading['tabular'].get(name,[])
        guards.append({'container':'context','pointer':'/documentary_context/tabular/'+name,
                       'items':len(items),'use':'candidate_review_only','positive_query_source':False})
    for name in ('manual_context','index_context','shared_context','general_conventions'):
        guards.append({'container':'context','pointer':'/documentary_context/'+name,
                       'items':len(reading.get(name,[])), 'use':'scope_and_conditions_preserved_for_review',
                       'positive_query_source':False})
    for name in ('classification','tabular_annotations','tabular_origin_scopes','quality'):
        pointer = '/documentary_context/classification' if name == 'classification' else '/'+name
        guards.append({'container':'context','pointer':pointer,'use':'review_without_expanding_or_applying_rules',
                       'positive_query_source':False})
    plan = {'schema_version':VERSION, 'status':'queries_prepared_not_executed',
        'code':request['code'], 'edition':reading['edition'], 'input_mode':context['input_mode'],
        'scope':request['scope'], 'source_snapshot_sha256':context['source_snapshot_sha256'],
        'context_sha256':context['context_sha256'], 'audit_sha256':digest(audit),
        'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'context_files':{'context':'context.json','audit':'audit.json'},
        'original_title_segment':title, 'baseline_query_id':base, 'max_queries':max_queries,
        'segments':segments, 'queries':queries, 'held_inclusions_or_variants':held,
        'evidence':evidence, 'review_context':guards,
        'policy':{'method':'literal_source_segments_v1','generative_reformulation':False,
            'preserve_original_title_and_diagnosis':True, 'interpret_patient_negation_or_temporality':False,
            'inclusion_queries_are_alternatives':True, 'expand_title_conjunctions':False,
            'apply_mortality_or_morbidity_rules':False, 'automatic_recoding':False,
            'automatic_snomed_exclusion_filter':False, 'target_version':request.get('target_version'),
            'snomed_catalog_searched':False,'clinical_validation':False,
            'token_budget_required_before_encoding':True,'implicit_truncation_allowed':False,
            'generative_input_is_data_not_instructions':True},
        'limitations':['No determina que una inclusión esté presente en el paciente.',
            'Conserva el diagnóstico sin resolver negación, temporalidad o contradicciones con el código.',
            'Los registros pendientes o ambiguos mantienen su estado en el contexto completo.',
            'No propone SCTID ni mide la calidad de mapeo a SNOMED.']}
    plan['plan_sha256'] = digest(plan)
    return plan


def check_token_budget(plan, tokenizer, max_tokens, model_spec):
    """Keep every original character; report oversized queries instead of truncating."""
    if type(max_tokens) is not int or max_tokens < 4:
        raise ContextError('Presupuesto de tokens inválido.')
    if plan.get('plan_sha256') != digest({k:v for k,v in plan.items() if k != 'plan_sha256'}):
        raise ContextError('La huella del plan no coincide.')
    plan = deepcopy(plan)
    for query in plan['queries']:
        length = len(tokenizer(query['text'],add_special_tokens=True,truncation=False)['input_ids'])
        query['tokens'] = length
        query['encoding_status'] = 'within_token_budget' if length <= max_tokens else 'needs_supported_shorter_variant'
    plan['token_budget_check'] = {'max_tokens':max_tokens,'model':model_spec,
        'oversized_queries':sum(q['tokens']>max_tokens for q in plan['queries']),
        'texts_truncated':False,'all_queries_fit':all(q['tokens']<=max_tokens for q in plan['queries'])}
    plan.pop('plan_sha256')
    plan['plan_sha256'] = digest(plan)
    return plan


def queries_for_encoding(plan, model_spec, max_tokens):
    """Future executors must not silently omit/truncate an unchecked user query."""
    if plan.get('plan_sha256') != digest({k:v for k,v in plan.items() if k != 'plan_sha256'}):
        raise ContextError('La huella del plan no coincide.')
    check = plan.get('token_budget_check',{})
    if check.get('model') != model_spec or check.get('max_tokens') != max_tokens:
        raise ContextError('La comprobación de tokens corresponde a otro modelo o presupuesto.')
    if not check.get('all_queries_fit') or not all(q['encoding_status']=='within_token_budget' for q in plan['queries']):
        raise ContextError('Falta comprobar tokens o preparar una variante respaldada para las consultas largas.')
    return deepcopy(plan['queries'])


def render_queries(plan):
    lines = ['# Consultas preparadas: '+plan['code'], '',
        'Preparación documental; no se ejecutó búsqueda SNOMED ni selección clínica.', '',
        'El título original y el diagnóstico aportado permanecen íntegros. Cada inclusión es una alternativa, no un diagnóstico afirmado.', '',
        '| Tipo | Consulta literal | Comprobación de tokens |','|---|---|---|']
    for q in plan['queries']:
        text = q['text'].replace('|','\\|').replace('\n',' ⏎ ').replace('\r','')
        lines.append('| '+q['kind']+' | '+text+' | '+q['encoding_status']+' |')
    lines += ['', f"Consultas preparadas: {len(plan['queries'])}; presupuesto máximo: {plan['max_queries']}.",
              f"Inclusiones o variantes retenidas fuera de búsqueda: {len(plan['held_inclusions_or_variants'])}.", '',
              'Las exclusiones, reglas del manual, rutas del índice y anotaciones conservan su texto y procedencia en context.json y audit.json. No se usan como términos positivos ni filtros automáticos de conceptos SNOMED.', '',
              'Los motivos de retención y los segmentos exactos están en queries.json. Una consulta que exceda los tokens requiere una variante respaldada; no se recorta silenciosamente ni se considera que el diagnóstico fue evaluado.', '',
              '## Límites', '']
    lines.extend('- '+x for x in plan['limitations'])
    return '\n'.join(lines)+'\n'

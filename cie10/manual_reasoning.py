"""Volume 2 retrieval and whole-item selection for morbidity explanations.

Sources are fetched completely by the existing snapshot-bound consumer. Selection
is explicit and does not turn book examples or code mentions into patient facts.
"""
import re
from urllib.parse import quote
from .mapping_context import MappingContextClient, ContextError
from .context_readable import Reader
from .explanation_constraints import normalize, unasserted, affirmed

ALLOWED_SCOPES = {'morbidity', 'classification_usage', 'mortality_and_morbidity'}
MAX_ITEMS = 4
MAX_CHARS = 5000


def allowed(scope):
    return scope in ALLOWED_SCOPES


def _section(record):
    value = record.get('section_address') or record.get('section', '')
    return value.get('number', '') if isinstance(value, dict) else value


def _entry(record, reader, role, matches=()):
    reference = reader.reference(record)
    return dict(id='manual-' + record['id'], type='CIE10', volume=2, role=role,
        record_ids=[record['id']], text=reader.text(record.get('text') or record.get('raw_line') or '', record),
        title=record.get('title') or _section(record), section=_section(record),
        scope=record.get('scope'), coding_context=record.get('coding_context'),
        requires_case_context=record.get('requires_case_context', True),
        executable_rule=False, automatic_recoding=False, patient_facts=False,
        contains_worked_examples=record.get('contains_worked_examples', role == 'manual_example'),
        matches=[dict(expression=x['matched_expression'], role=x['role']) for x in matches],
        document_references=[{k:v for k,v in ref.items() if k not in ('target_unit_refs','candidate_unit_refs')}
                             for ref in record.get('manual_references', [])],
        warnings=record.get('warnings', []), provenance=reference['source'],
        detail_urls=[reference['detail_url']])


def build_manual_context(request, tabular_evidence, transport=None, client=None):
    client = client or MappingContextClient(transport=transport, page_size=200)
    audit = client.fetch_evidence(request['code'], 'morbidity')
    snapshot = request['source_snapshot_sha256']
    if audit.get('source_snapshot_sha256') != snapshot:
        raise ContextError('La versión documental cambió al consultar el tomo 2. Repite la búsqueda.')
    if not audit.get('retrieval', {}).get('all_selected_pages_retrieved'):
        raise ContextError('La recuperación del contexto del manual está incompleta.')
    reader = Reader(audit)
    linked = {}
    for link in audit.get('context_links', []):
        linked.setdefault(link['record_id'], []).append(link)
    candidates = []
    rejected_scope = 0
    for identifier, links in linked.items():
        record = audit['records'][identifier]
        if not identifier.startswith('v2-'):
            continue
        if not allowed(record.get('scope')):
            rejected_scope += 1
            continue
        kind = record['kind']
        role = ('manual_example' if kind == 'manual_worked_example' else
                'manual_guidance' if kind == 'manual_chapter_guidance' else 'manual_instruction')
        item = _entry(record, reader, role, links)
        subject = any('subject' in x['role'] or x['role'] == 'chapter_guidance' for x in links)
        priority = 110 if subject and role == 'manual_instruction' else 90 if subject else 40
        if role == 'manual_example':
            priority = 10
        candidates.append((priority, item))

    for identifier in audit.get('supporting_manual_unit_refs', []):
        record = audit['records'].get(identifier)
        if not record or not identifier.startswith('v2-') or not allowed(record.get('scope')):
            continue
        # Dependencies remain contextual and retain their printed-reference issues.
        candidates.append((45, _entry(record, reader, 'manual_support')))

    # Join every physical passage in a convention section before selecting it.
    # No clipped lines, orphaned continuations or missing final exceptions.
    groups = {}
    for identifier in audit.get('general_convention_refs', []):
        if not identifier.startswith('v2-'):
            continue
        record = audit['records'].get(identifier)
        if record is None:
            raise ContextError('Falta el contenido de una convención del tomo 2.')
        if allowed(record.get('scope')):
            groups.setdefault(_section(record), []).append(record)
    anchors = [item for item in tabular_evidence if item.get('role') in ('title','candidate_term') or item['type']=='INPUT']
    anchor_query = ' '.join(item['text'] + str(item.get('code_symbol','')) for item in anchors)
    local = [item for item in tabular_evidence if item.get('inherited') is False and item.get('role') in ('exclusion','instructions')]
    query = anchor_query + ' ' + ' '.join(item['text'] for item in local)
    wanted = {'3.1.2': 70}
    if '†' in anchor_query or '*' in anchor_query or re.search(r'daga|asterisco|etiologia|manifestacion', normalize(anchor_query)):
        wanted['3.1.3'] = 85
    if re.search(r'\b(?:sai|ncop)\b', normalize(query)):
        wanted['3.1.4'] = 80
    # Prefer complete semantic units (e.g. dagger/asterisk system), not an
    # entire section that also contains independent lists and other conventions.
    discovery = (transport or client.transport)('/v1/manual/sections/3?view=evidence')
    covered = set()
    for identifier, heading in discovery.get('records', {}).items():
        address = _section(heading)
        normalized = normalize(address)
        priority = None
        if address.startswith('3.1.2 |'):
            if 'terminos de exclusion' in normalized:
                priority = 70
            elif 'terminos de inclusion' in normalized and any(x.get('role') == 'inclusions' for x in tabular_evidence):
                priority = 65
        elif address.startswith('3.1.3 |') and '3.1.3' in wanted and 'daga y asterisco' in normalized:
            priority = 85
        elif address.startswith('3.1.4 |'):
            if 'sai' in normalized and re.search(r'\bsai\b', normalize(query)):
                priority = 80
            elif 'no clasificado en otra parte' in normalized and 'ncop' in normalize(query):
                priority = 80
            elif 'punto y guion' in normalized and re.search(r'\.-', normalize(query)):
                priority = 75
        if priority is None:
            continue
        data = (transport or client.transport)('/v1/records/' + quote(identifier, safe=''))
        record = data.get('record', {})
        if data.get('source_snapshot_sha256') != snapshot or record.get('id') != identifier:
            raise ContextError('El catálogo cambió al recuperar una convención del manual.')
        if not allowed(record.get('scope')):
            rejected_scope += 1
            continue
        item = _entry(record, Reader({**data, 'records': {identifier: record}}), 'manual_convention')
        item['requires_case_context'] = False
        candidates.append((priority, item))
        covered.add(address.split(' |')[0])

    for section, priority in wanted.items():
        if section in covered:
            continue
        rows = groups.get(section, [])
        if not rows:
            continue
        item = _entry(rows[0], reader, 'manual_convention')
        item.update(id='manual-convention-' + section, section=section, title='Convenciones ' + section,
                    record_ids=[row['id'] for row in rows],
                    text='\n\n'.join(reader.text(row.get('text', ''), row) for row in rows),
                    requires_case_context=False, contains_worked_examples=True,
                    detail_urls=[reader.reference(row)['detail_url'] for row in rows])
        sources = [source for row in rows for source in row.get('sources', [])]
        item['provenance'] = reader.reference(rows[0], sources)['source'] + ' · sección ' + section
        candidates.append((priority, item))

    # Discover general morbidity headings, then fetch their actual content using
    # /records, whose snapshot is checked independently. Discovery is not evidence.
    fetch = transport or client.transport
    discovered = fetch('/v1/manual/sections/4.5?view=evidence')
    diagnostic = normalize(request.get('diagnostic_text') or '')
    globals_wanted = {'4.5.1 | Especificidad y detalle'}
    if any(word in diagnostic for word in ('afeccion principal', 'episodio', 'motivo de atencion')):
        globals_wanted.add('4.5')
    general_count = 0
    for identifier, heading in discovered.get('records', {}).items():
        if _section(heading) not in globals_wanted:
            continue
        data = fetch('/v1/records/' + quote(identifier, safe=''))
        record = data.get('record', {})
        if data.get('source_snapshot_sha256') != snapshot or record.get('id') != identifier:
            raise ContextError('El catálogo cambió al recuperar una orientación general del manual.')
        if not allowed(record.get('scope')):
            rejected_scope += 1
            continue
        item = _entry(record, Reader({**data, 'records': {identifier: record}}), 'manual_guidance')
        candidates.append((60 if _section(record) == '4.5' else 50, item))
        general_count += 1

    unique = {}
    for priority, item in candidates:
        if not item['text'].strip():
            continue
        key = tuple(item['record_ids'])
        if key not in unique or priority > unique[key][0]:
            unique[key] = priority, item
    selected, omitted = [], []
    characters = 0
    for priority, item in sorted(unique.values(), key=lambda pair: (-pair[0], pair[1]['id'])):
        if len(selected) >= MAX_ITEMS or characters + len(item['text']) > MAX_CHARS:
            omitted.append(dict(record_ids=item['record_ids'], reason='whole_item_selection_budget'))
            continue
        selected.append(item)
        characters += len(item['text'])
    return selected, dict(scope='morbidity', linked_context_pages_complete=True,
        linked_context_page_count=audit['retrieval']['page_count'],
        linked_context_total=audit['retrieval']['total_selected_records'],
        available_manual_items=len(unique), selected_manual_items=len(selected),
        selected_characters=characters, max_items=MAX_ITEMS, max_characters=MAX_CHARS,
        omitted_items=omitted, excluded_scope_items=rejected_scope,
        general_guidance_verified=general_count, automatic_recoding=False,
        selection_method='whole_items_by_subject_convention_and_scope_v1',
        coverage='selected_manual_context_not_all_rules_or_patient_applicability')


def manual_constraint(evidence):
    title = next((x for x in evidence if x.get('role') == 'title'), None)
    term = next((x for x in evidence if x.get('role') == 'candidate_term'), None)
    diagnostic = next((x for x in evidence if x['type'] == 'INPUT'), None)
    if not title or not term or not diagnostic:
        return None
    text = normalize(diagnostic['text'])
    for item in evidence:
        if item.get('role') not in ('manual_instruction', 'manual_guidance') or not allowed(item.get('scope')):
            continue
        source = normalize(item['text'])
        history = any(not unasserted(text, match.start()) for match in re.finditer(r'extirpad[oa].{0,35}(?:anterior|pasad|previ)|antecedente.{0,60}tumor', text))
        if 'tumor primario que fue extirpado' in source and history:
            return dict(rule_id='manual_prior_tumor_episode_context', assessment='undetermined',
                justification='El tomo 2 distingue el tumor previo de la afección que motiva la atención actual. La entrada menciona un tumor anterior; debe aclararse la situación del episodio antes de proponer un concepto de tumor actual.',
                additional_detail_needed=['Aclarar enfermedad activa, antecedente y motivo actual de atención.'],
                evidence_refs=[title['id'], term['id'], diagnostic['id'], item['id']])
        if title.get('code', '').endswith('.7') and 'diabet' in normalize(title['text']) and 'sin preferencia por ninguna' in source and affirmed(text, r'\bafeccion principal\b'):
            if not re.search(r'sin (?:preferencia|prioridad)|ninguna (?:predomina|tiene preferencia)', text):
                return dict(rule_id='manual_diabetes_main_condition_priority', assessment='undetermined',
                    justification='El tomo 2 condiciona el uso de complicaciones múltiples como afección principal a que no haya preferencia por una de ellas. La entrada no aclara esa prioridad; el candidato no puede resolver por sí solo la selección del episodio.',
                    additional_detail_needed=['Precisar la complicación principal o confirmar ausencia de preferencia.'],
                    evidence_refs=[title['id'], term['id'], diagnostic['id'], item['id']])
    return None

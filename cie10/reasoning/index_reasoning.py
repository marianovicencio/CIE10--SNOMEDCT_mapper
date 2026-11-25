"""Snapshot-bound Volume 3 context. Navigation is never clinical equivalence."""
import json
import re
from urllib.parse import quote
from cie10.api.mapping_context import MappingContextClient, ContextError, rebase
from cie10.api.context_readable import Reader, without_provenance
from cie10.explanations.explanation_constraints import normalize, unasserted, affirmed

MAX_ITEMS = 3
MAX_CHARS = 5500
TABLES = {'neoplasm_table_row':'neoplasm', 'drug_table_row':'drug',
          'abortion_table_row':'abortion', 'transport_matrix_row':'transport_matrix'}
STOP = {'tumor','maligno','maligna','neoplasia','enfermedad','trastorno','tipo','etapa','estadio',
        'principal','codigo','complicado','complicaciones','otras','otros','especificado',
        'no','del','las','los','con','sin','por','para','una','que','como','paciente'}


def words(text):
    return {word[:6] for word in re.findall(r'[a-z]{3,}', normalize(text)) if word not in STOP}


COLUMN_LABELS = {'malignant_primary':'Maligno primario','malignant_secondary':'Maligno secundario',
'in_situ':'In situ','benign':'Benigno','uncertain_or_unknown_behavior':'Comportamiento incierto o desconocido',
'poisoning_chapter_xix':'Envenenamiento (capítulo XIX)','accidental':'Accidental',
'intentional_self_harm':'Autolesión intencional','undetermined':'Intención no determinada',
'adverse_therapeutic_use':'Efecto adverso en uso terapéutico',
'o03_o06_complete_or_unspecified':'O03–O06 completo o no especificado','o03_o06_incomplete':'O03–O06 incompleto',
'o08_subsequent_complication':'O08 complicación posterior','o07_nonmedical_or_unspecified':'O07 no médico o no especificado',
'o07_medical':'O07 médico','pedestrian_or_animal':'Peatón o animal','pedal_cycle':'Bicicleta',
 'two_or_three_wheeled_motor_vehicle':'Vehículo motorizado de dos o tres ruedas','car_pickup_or_van':'Automóvil, camioneta o furgoneta',
'heavy_transport_or_bus':'Transporte pesado o autobús','other_motor_vehicle':'Otro vehículo motorizado',
'train_or_rail_vehicle':'Tren o vehículo ferroviario','other_nonmotor_vehicle':'Otro vehículo sin motor',
'fixed_or_stationary_object':'Objeto fijo o estacionario','noncollision_accident':'Accidente sin colisión',
'other_or_unspecified_accident':'Otro accidente o no especificado'}


def reading_text(payload):
    lines=[]
    if payload['route']:lines.append(' > '.join(payload['route']))
    if payload['printed_entry']:lines.append(payload['printed_entry'])
    for route,entry in zip(payload.get('alternative_routes',[]),payload.get('alternative_entries',[])):
        lines.append('Ruta alternativa del índice (no implica sinonimia): '+' > '.join(route))
        if entry:lines.append(entry)
    if payload.get('victim_mode'):lines.append('Víctima (fila): '+payload['victim_mode']+'; las columnas indican la contraparte.')
    if payload.get('columns'):
        lines.append('Columnas de la tabla:')
        for name,cell in payload['columns'].items():
            value=cell.get('text','') if isinstance(cell,dict) else cell
            family=cell.get('code_family') if isinstance(cell,dict) else None
            label=COLUMN_LABELS.get(name,name)
            lines.append(label+': '+str(value or 'Sin valor')+(' · familia '+family if family else ''))
        lines.append('Columnas que enlazan con el código consultado: '+', '.join(COLUMN_LABELS.get(x,x) for x in payload.get('matched_columns',[])))
    if payload.get('table_context',{}).get('text'):lines.append(payload['table_context']['text'])
    for note in payload.get('scope_notes',[]):
        if note.get('scope_path'):lines.append('Ámbito de la nota: '+' > '.join(note['scope_path']))
        lines.append(note['text'])
    for edge in payload.get('remissions',[]):
        directive={'see':'Ver','see_also':'Ver también'}.get(edge.get('directive'),edge.get('directive') or 'Remisión')
        lines.append(directive+': '+str(edge.get('printed_target_text') or edge.get('target_text') or ''))
        lines.append('Estado documental: '+str(edge.get('resolution') or 'No especificado')+'. No implica equivalencia clínica.')
        for target in edge.get('target_contexts',[]):
            if target.get('route'):lines.append('Ruta de destino recuperada: '+' > '.join(target['route']))
            elif not target.get('content_retrieved'):lines.append('El contenido de uno de los destinos no fue recuperado.')
    return '\n'.join(lines)


def _target_refs(edge):
    result = []
    for name in ('target_id',):
        if edge.get(name):result.append(edge[name])
    for name in ('target_ids','candidate_ids','duplicate_target_ids'):
        result.extend(edge.get(name, []))
    if edge.get('partial_navigation', {}).get('anchor_id'):
        result.append(edge['partial_navigation']['anchor_id'])
    return list(dict.fromkeys(result))


def _item(record, links, audit, reader):
    kind = record['kind']
    source_record = audit['records'].get(record.get('source_id')) if kind == 'index_remission' else None
    route = [part for part in (source_record or record).get('term_path', []) if part]
    if not route and record.get('scope_path'):
        route = record['scope_path']
    payload = dict(kind=kind, route=route, printed_entry=reader.text(record.get('text') or record.get('raw_term') or '', record),
        matched_expressions=[dict(expression=x['matched_expression'],role=x['role']) for x in links],
        code_references=record.get('code_references', []), usable_as_synonym=False,
        implies_clinical_equivalence=False, patient_facts=False, automatic_recoding=False)
    dependencies = [record] + ([source_record] if source_record else [])
    if source_record and not payload['printed_entry']:
        payload['printed_entry'] = reader.text(source_record.get('text', ''), source_record)
    if kind in TABLES:
        if kind == 'transport_matrix_row':
            payload.update(victim_mode=record.get('victim_mode'), columns=record.get('columns', {}))
        else:
            payload['columns'] = without_provenance(record.get('cells', {}))
        payload['matched_columns'] = list(dict.fromkeys(x['role'].split(':',1)[1] for x in links if x['role'].startswith(('table_column:','transport_collision:'))))
        table = next((x for x in audit['records'].values() if x['kind']=='special_table_metadata'
                      and x.get('table')==TABLES[kind]), None)
        if table is None:
            raise ContextError('Falta el encabezado y contexto de una tabla del tomo 3.')
        payload['table_context'] = dict(table=table['table'], columns=table.get('columns', []),
                                        text='' if kind == 'transport_matrix_row' else reader.table_intro(table),
                                        header_rendering='structured_columns_and_victim_mode' if kind == 'transport_matrix_row' else 'printed_header_and_notes',
                                        warnings=table.get('warnings', []))
        dependencies.append(table)
    notes = []
    for identifier in list(dict.fromkeys(record.get('index_note_refs', []) + (source_record or {}).get('index_note_refs', []))):
        note = audit['records'].get(identifier)
        if note is None:
            raise ContextError('Falta una nota de alcance de la entrada del índice.')
        notes.append(dict(text=reader.text(note.get('text', ''), note),
                          scope_path=note.get('scope_path'),scope_type=note.get('scope_type'),
                          scope_anchor_id=note.get('scope_anchor_id')))
        dependencies.append(note)
    if notes:payload['scope_notes'] = notes
    if kind == 'index_note':
        payload.update(scope_path=record.get('scope_path'),scope_type=record.get('scope_type'),
                       scope_anchor_id=record.get('scope_anchor_id'))
    edges = record.get('remissions', [])
    if kind == 'index_remission':edges = [record]
    navigation = []
    for edge in edges:
        value = {k:without_provenance(v) for k,v in edge.items() if k in (
            'directive','target_text','printed_target_text','target_kind','target_id','target_ids',
            'candidate_ids','duplicate_target_ids','resolution','resolution_issue','requires_case_context',
            'target_code_expressions','table_selector','navigation_selector','partial_navigation',
            'external_document_reference','documentary_matching_method')}
        value.update(implies_clinical_equivalence=False, navigation_only=True)
        targets = []
        for identifier in _target_refs(edge):
            target = audit['records'].get(identifier)
            item = dict(record_id=identifier,content_retrieved=target is not None)
            if target:
                item.update(kind=target['kind'],route=target.get('term_path', []),
                            code_references=target.get('code_references', []),
                            warnings=target.get('warnings', []))
                dependencies.append(target)
            targets.append(item)
        value['target_contexts'] = targets
        navigation.append(value)
    if navigation:payload['remissions'] = navigation
    payload['warnings'] = record.get('warnings', [])
    for name in ('hierarchy_requires_review','source_hierarchy_review','source_ambiguity_preserved'):
        if name in record:payload[name] = without_provenance(record[name])
    role = ('index_table' if kind in TABLES else 'index_remission' if kind=='index_remission' else
            'index_note' if kind=='index_note' else 'index_entry')
    requires_review = bool(record.get('hierarchy_requires_review')) or any(
        isinstance(cell,dict) and (cell.get('valid_shape') is False or cell.get('review_status') == 'source_ambiguity_preserved')
        for cell in record.get('cells', {}).values())
    requires_review = requires_review or any(not str(edge.get('resolution','')).startswith('resolved')
        or any(not target['content_retrieved'] for target in edge.get('target_contexts',[])) for edge in navigation)
    payload['requires_documentary_review'] = requires_review
    references = [reader.reference(x) for x in dependencies]
    return dict(id='index-'+record['id'],type='CIE10',volume=3,role=role,kind=kind,
        text=json.dumps(payload,ensure_ascii=False,separators=(',',':')), reading_text=reading_text(payload), route=route,
        matched_columns=payload.get('matched_columns', []),
        code_references=record.get('code_references', []),
        navigation=payload.get('remissions', []), requires_documentary_review=requires_review, usable_as_synonym=False,
        implies_clinical_equivalence=False, patient_facts=False, automatic_recoding=False, requires_case_context=True,
        record_ids=list(dict.fromkeys(x['id'] for x in dependencies)),
        provenance='; '.join(dict.fromkeys(ref['source'] for ref in references)),
        detail_urls=list(dict.fromkeys(ref['detail_url'] for ref in references)))


def group_identical_table_context(selected):
    """Share headers/cells only when all table conditions match; retain every path."""
    grouped=[]
    keys={}
    for item in selected:
        if item.get('role')!='index_table':
            grouped.append(item);continue
        payload=json.loads(item['text'])
        common={k:v for k,v in payload.items() if k not in ('route','printed_entry')}
        key=json.dumps(common,ensure_ascii=False,sort_keys=True)
        if key not in keys:
            clone=dict(item);clone['routes']=[item['route']]
            keys[key]=len(grouped);grouped.append(clone);continue
        target=grouped[keys[key]];combined=json.loads(target['text'])
        combined.setdefault('alternative_routes',[]).append(item['route'])
        combined.setdefault('alternative_entries',[]).append(payload['printed_entry'])
        target['routes'].append(item['route'])
        target['record_ids']=list(dict.fromkeys(target['record_ids']+item['record_ids']))
        target['detail_urls']=list(dict.fromkeys(target.get('detail_urls',[])+item.get('detail_urls',[])))
        target['provenance']='; '.join(dict.fromkeys(target['provenance'].split('; ')+item['provenance'].split('; ')))
        target['selection_score']=max(target.get('selection_score',0),item.get('selection_score',0))
        target['text']=json.dumps(combined,ensure_ascii=False,separators=(',',':'))
        target['reading_text']=reading_text(combined)
    return grouped


def build_index_context(request, evidence, transport=None, client=None):
    client = client or MappingContextClient(transport=transport,page_size=200)
    audit = client.fetch_evidence(request['code'],'morbidity')
    if audit.get('source_snapshot_sha256') != request['source_snapshot_sha256']:
        raise ContextError('La versión documental cambió al consultar el tomo 3.')
    if not audit.get('retrieval', {}).get('all_selected_pages_retrieved'):
        raise ContextError('La recuperación del contexto del índice está incompleta.')
    links = {}
    for link in audit.get('context_links', []):
        if link['record_id'].startswith('v3-'):links.setdefault(link['record_id'], []).append(link)
    fetch = transport or getattr(client, 'transport', None)
    def add_record(identifier):
        if identifier in audit['records']:
            return
        if fetch is None:
            raise ContextError('Falta el origen de una remisión del índice.')
        data = fetch('/v1/records/' + quote(identifier, safe=''))
        if data.get('source_snapshot_sha256') != request['source_snapshot_sha256'] or data.get('record',{}).get('id') != identifier:
            raise ContextError('El catálogo cambió al recuperar el origen de una remisión.')
        data = rebase(data)
        audit['records'][identifier] = data['record']
        audit['source_locations'].update(data['source_locations'])
        for key,document in data['documents'].items():
            if key in audit['documents'] and audit['documents'][key] != document:
                raise ContextError('La identidad de un documento cambió.')
            audit['documents'][key] = document
    for identifier in links:
        record = audit['records'][identifier]
        if record['kind'] == 'index_remission' and record.get('source_id'):
            add_record(record['source_id'])
            for note in audit['records'][record['source_id']].get('index_note_refs',[]):
                add_record(note)
    reader = Reader(audit)
    query = words(' '.join(x['text'] for x in evidence if x.get('role')=='candidate_term' or x['type']=='INPUT'))
    candidates = []
    for identifier, matches in links.items():
        record = audit['records'][identifier]
        path = ' '.join(record.get('term_path') or record.get('scope_path') or [])
        if record['kind'] == 'transport_matrix_row':
            path = str(record.get('victim_mode') or '')
            path += ' ' + ' '.join(COLUMN_LABELS.get(x['role'].split(':',1)[1], '') for x in matches if x['role'].startswith('transport_collision:'))
        overlap = len(query & words(path))
        priority = overlap * 20 + (10 if record['kind'] in TABLES else 5)
        if record['kind']=='index_note':priority = overlap * 20 - 20
        # Notes keep their own subtree scope and cannot win solely by a broad code range.
        if priority < 0:continue
        item = _item(record,matches,audit,reader)
        item['selection_score'] = priority
        candidates.append(item)
    selected,omitted = [],[]
    has_overlap = any(x['selection_score'] >= 20 for x in candidates)
    characters=0
    for item in sorted(candidates,key=lambda x:(-x['selection_score'],x['id'])):
        if has_overlap and item['selection_score'] < 20:
            omitted.append(dict(record_ids=item['record_ids'],reason='no_candidate_or_input_term_overlap'))
            continue
        if len(selected)>=MAX_ITEMS or characters+len(item['text'])>MAX_CHARS:
            omitted.append(dict(record_ids=item['record_ids'],reason='whole_index_unit_selection_budget'))
            continue
        selected.append(item);characters+=len(item['text'])
    source_entry_count=len(selected)
    selected=group_identical_table_context(selected)
    characters=sum(len(x['text']) for x in selected)
    return selected,dict(source_entries_selected=source_entry_count,scope='morbidity',linked_context_pages_complete=True,
        linked_context_page_count=audit['retrieval']['page_count'],
        available_index_items=len(candidates),selected_index_items=len(selected),
        selected_characters=characters,max_items=MAX_ITEMS,max_characters=MAX_CHARS,
        omitted_items=omitted,usable_as_synonym=False,automatic_recoding=False,
        selection_method='candidate_and_input_terms_over_whole_paths_tables_and_remissions_v1',
        coverage='selected_index_navigation_not_clinical_applicability')


def index_constraint(evidence):
    title = next((x for x in evidence if x.get('role')=='title'),None)
    term = next((x for x in evidence if x.get('role')=='candidate_term'),None)
    diagnostic = next((x for x in evidence if x['type']=='INPUT'),None)
    if not title or not term:return None
    text=normalize(diagnostic['text']) if diagnostic else ''
    for item in evidence:
        if item.get('volume')!=3:continue
        route=normalize(' '.join(item.get('route', [])))
        refs=[title['id'],term['id']]+([diagnostic['id']] if diagnostic else [])+[item['id']]
        if 'embarazo' in route and 'complic' in route and diagnostic:
            explicit=any(not unasserted(text,m.start()) for m in re.finditer(r'complic[a-z]*.{0,45}embarazo|embarazo.{0,45}complic[a-z]*',text))
            if explicit and not re.search(r'\b(?:sin complicaciones|no (?:hay|hubo) complicaciones)\b', text):
                return dict(rule_id='index_pregnancy_route_requires_tabular_review',assessment='undetermined',
                    justification='El índice aporta una ruta para afecciones que complican el embarazo. Esa navegación no demuestra equivalencia entre el tumor y una complicación obstétrica; debe comprobarse la relación clínica y el destino en la lista tabular.',
                    additional_detail_needed=['Confirmar relación con el embarazo y revisar el destino tabular de la ruta.'],evidence_refs=refs)
        paired = any('†' in x for x in item.get('code_references',[])) and any('*' in x for x in item.get('code_references',[]))
        if paired and item.get('route'):
            anchor=words(item['route'][0])
            mentioned=any(affirmed(text,r'\b'+re.escape(word)+r'[a-z]*\b') for word in anchor) if diagnostic else False
            candidate_extra=bool(anchor & words(term['text'])) and not bool(anchor & words(title['text']))
            if mentioned or candidate_extra:
                return dict(rule_id='index_etiology_manifestation_context',assessment='undetermined',
                    justification='La ruta del índice enlaza etiología y manifestación mediante daga y asterisco. El código consultado no se convierte en sinónimo de toda la ruta; debe aclararse qué componentes necesita representar la correspondencia.',
                    additional_detail_needed=['Precisar si se representa la enfermedad de base, la manifestación o ambas.'],evidence_refs=refs)
    return None

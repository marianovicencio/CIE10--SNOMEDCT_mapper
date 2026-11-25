"""Reading projection: official wording once, with compact documentary references.

This is formatting, not a clinical summary. The evidence representation remains
available, including all source coordinates, semantic annotations and raw text.
"""
import re
from urllib.parse import urlencode, quote


START = re.compile(r'^(?:[12]$|[•●▪]|\d+\.\s|\d+(?:\.\d+)+\s|[12]\s+\([a-d]\)|\([a-d]\)|[a-d]\)\s|[A-Z]\d{2}(?:\.\d+)?(?:[–-][A-Z]?\d{2})?\s|(?:Excepción|Nota|Capítulo|Ejemplo)\b)')


def unwrap(text):
    """Join physical lines; keep explicit list/section boundaries.

    Only remove hyphens at physical line endings followed by lower-case text;
    code-family punctuation, ranges and hyphens inside lines remain unchanged.
    """
    text = re.sub(r'([a-záéíóúüñ])[-\u00ad]\s*\n\s*([a-záéíóúüñ])', r'\1\2', text or '')
    paragraphs = []
    for line in text.splitlines():
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if not line:
            if paragraphs and paragraphs[-1] != '': paragraphs.append('')
        elif not paragraphs or not paragraphs[-1] or START.match(line):
            paragraphs.append(line)
        else:
            paragraphs[-1] += ' ' + line
    return '\n'.join(paragraphs).strip()


def without_provenance(value):
    if isinstance(value, dict):
        return {k:without_provenance(v) for k,v in value.items() if k not in ('source','sources','target_sources','raw_lines','raw_note_fragments','raw_spans','source_ref','bbox','source_sha256')}
    if isinstance(value, list): return [without_provenance(v) for v in value]
    return value


class Reader:
    def __init__(self, evidence):
        self.e = evidence
        self.records = evidence['records']
        self.locations = evidence['source_locations']

    def location(self, source):
        return self.locations.get(source.get('source_ref'), source)

    def reference(self, record, sources=None):
        locations = [self.location(s) for s in (sources or record.get('sources') or [record.get('source', {})])]
        pages = sorted({s['pdf_page'] for s in locations if s.get('pdf_page')})
        printed = list(dict.fromkeys(s['printed_page'] for s in locations if s.get('printed_page')))
        doc = next((s.get('document_ref') for s in locations if s.get('document_ref')), None)
        label = []
        if doc: label.append('Volumen ' + str(self.e['documents'][doc]['volume']))
        if pages: label.append('PDF ' + ', '.join(map(str,pages)))
        if printed: label.append('página impresa ' + ', '.join(map(str,printed)))
        result = {'source': ' · '.join(label), 'detail_url': '/v1/records/' + quote(record['id'], safe='')}
        if record['kind']=='manual_document_unit':result['reading_url']='/v1/manual/units/'+quote(record['id'],safe='')
        return result

    def text(self, text, record):
        # Restore only hyphenation actually attested across adjacent source lines.
        fragments = [f for fs in record.get('raw_note_fragments', {}).values() for f in fs]
        for a, b in zip(fragments, fragments[1:]):
            left, right = a.get('text', ''), b.get('text', '')
            ending = re.search(r'([a-záéíóúüñ]+)-$', left)
            beginning = re.match(r'([a-záéíóúüñ]+)', right)
            if ending and beginning:
                text = text.replace(ending[1] + '- ' + beginning[1], ending[1] + beginning[1])
        # The manual already carries one source per physical text line. Use
        # vertical paragraph gaps when alignment is exact, never guess alignment.
        lines = text.splitlines(); sources = record.get('sources', [])
        if len(lines) == len(sources) and len(lines) > 1:
            spaced = []
            previous = None
            for line, source in zip(lines, sources):
                location = self.location(source); box = location.get('bbox')
                if previous and box and previous.get('bbox') and location.get('pdf_page') == previous.get('pdf_page') and box[1] - previous['bbox'][3] > 8:
                    spaced.append('')
                spaced.append(line); previous = location
            text = '\n'.join(spaced)
        return unwrap(text)

    def fragment_groups(self, fragments):
        groups = []; current = []; previous = None
        for f in fragments:
            location = self.location(f.get('source', {})); bbox = location.get('bbox')
            gap = previous and bbox and previous.get('bbox') and location.get('pdf_page') == previous.get('pdf_page') and bbox[1] - previous['bbox'][3] > 8
            boundary = START.match(f.get('text', '')) or gap or (current and f.get('block_id') != current[-1].get('block_id'))
            if boundary and current: groups.append(current); current = []
            current.append(f); previous = location
        if current: groups.append(current)
        return groups

    def numbered(self, record):
        raw = [f for fs in record.get('raw_note_fragments', {}).values() for f in fs]
        output = []
        for note in record.get('numbered_notes', []):
            refs = {s.get('source_ref') for s in note.get('sources', [])}
            lines = [f['text'] for f in raw if f.get('source', {}).get('source_ref') in refs]
            output.append({'number': note['number'], 'text': unwrap('\n'.join(lines)) if lines else self.text(note['text'], record)})
        return output

    def table_intro(self, record):
        # Extraction splits wide headers into left/right fragments, sometimes
        # inside a word. Rejoin only fragments on the same physical baseline.
        rows = []
        fragments = record.get('header_fragments', [])
        header_y = min((self.location(f['source'])['bbox'][1] for f in fragments if f['text'].startswith('Maligno Comportamiento')), default=float('inf'))
        for f in fragments:
            s = self.location(f['source']); box = s.get('bbox')
            if not box or box[1] >= header_y: continue
            row = next((r for r in rows if abs(r[0] - box[1]) < .6), None)
            if row is None: row = [box[1], []]; rows.append(row)
            row[1].append((box, f['text']))
        lines = []
        symbols = []
        for _, parts in sorted(rows):
            if all(re.fullmatch(r'[♢◇\s]+', p[1]) for p in parts):
                symbols.extend(p[1].strip() for p in parts)
                continue
            line = ''; last = None
            for box, text in sorted(parts):
                separator = '' if last is None or box[0] - last[2] < 1 else ' '
                line += separator + text; last = box
            lines.append(line)
        # PDF diamond glyphs sit below the text baseline, in a separate span.
        # Reinsert them only at the two unambiguous marker holes on this header.
        text = unwrap('\n'.join(lines))
        if record.get('table') == 'neoplasm' and symbols:
            text = text.replace('con el signo (', 'con el signo ♢ (').replace('isquion )', 'isquion ♢)')
        return text

    def tabular(self):
        result = {f: [] for f in ('inclusions','exclusions','instructions','notes','general_context')}
        seen = {}; overviews = {}; definition_seen=set()
        for origin in self.e['effective_tabular_notes']:
            record = self.records[origin['origin_record_id']]
            for field, fragments in origin['fields'].items():
                if field == 'definition_blocks':
                    for block in fragments:
                        identifier=(record['id'],block['id'])
                        if identifier in definition_seen:continue
                        definition_seen.add(identifier)
                        item={'kind':'injury_type_definition','title':block['title'],
                            'scope':block['scope'],'declared_code_ranges':block['declared_code_ranges'],
                            'automatic_applicability':False,'reference':self.reference(record,block['sources'])}
                        for name in ('inclusions','exclusions','notes'):
                            if block.get(name):
                                item[name]=[self.text(f['text'],record) for f in block[name]]
                        if block.get('definition_groups'):
                            item['groups']=without_provenance(block['definition_groups'])
                        if block.get('structure_issues'):
                            item['structure_requires_review']=True
                        result['general_context'].append(item)
                    continue
                if field == 'coding_relations': continue  # Annotates wording already shown; audit view preserves it.
                if field == 'descriptive_text' and record.get('numbered_notes'):
                    result['general_context'].append({'title': record.get('description'), 'numbered_notes': self.numbered(record), 'reference': self.reference(record)})
                    continue
                if field not in result: target = 'general_context'
                else: target = field
                groups = self.fragment_groups(fragments) if field in ('instructions','notes') else [[f] for f in fragments]
                for group in groups:
                    text = self.text('\n'.join(f.get('text', '') for f in group), record)
                    if not text: continue
                    # Chapter contents lists accompany instructions in the raw
                    # record. Present them together as classification context.
                    if record['kind']=='context' and field == 'instructions' and (re.match(r'^[A-Z]\d{2}', text) or text.startswith('Tumores malignos,' ) or text.startswith('Tumores malignos del labio,')):
                        overview = overviews.setdefault(record['id'], {'kind':'classification_overview', 'title':record.get('description'), 'text':[], 'reference':self.reference(record)})
                        overview['text'].append(text)
                        continue
                    key = (target, text)
                    reference = self.reference(record, [s for f in group for s in (f.get('sources') or [f.get('source', {})])])
                    if key in seen:
                        if reference not in seen[key]['references']: seen[key]['references'].append(reference)
                        continue
                    item = {'text': text, 'origin': origin.get('origin_code') or record.get('description'), 'inherited': origin['inherited'], 'references': [reference]}
                    for f in group:
                        for name in ('examples','scope_statement','source_ambiguity_preserved'):
                            if name in f:item[name]=without_provenance(f[name])
                    seen[key] = item; result[target].append(item)
        for overview in overviews.values():
            overview['text'] = '\n'.join(overview['text'])
            result['general_context'].append(overview)
        return result

    def manual(self, record, links):
        result = {'kind': record['kind'], 'scope': record.get('scope'), 'section': record.get('section'),
                  'matches': [{'expression': l['matched_expression'], 'role': l['role']} for l in links],
                  'text': self.text(record.get('text') or record.get('raw_line') or '', record),
                  'reference': self.reference(record)}
        # Subject/context determine how to interpret a mention or an outcome.
        for key in ('subject_code_expressions','selection_context','coding_context','relation','code_expression','condition','recode_candidates','requires_case_context','executable_rule','diabetes_code','cause_code_expression','sequence_status','qualifier','sex','hard_exclusion','sex_constraint_type','sex_restriction','priority','priority_order','title','section_address','contains_worked_examples'):
            if key in record: result[key] = record[key]
        if record.get('manual_references'):
            result['document_references']=[{k:v for k,v in ref.items() if k not in ('target_unit_refs','candidate_unit_refs')} for ref in record['manual_references']]
        if 'boundary_end' in record:result['source_segment_complete']=record['boundary_end']=='next_document_heading'
        # The original block wording contains every condition/exception once;
        # no duplicate condition_rows/outcome_mentions or invented paraphrase.
        return result

    def index(self, record, links):
        term = ' > '.join(p for p in record.get('term_path', []) if p)
        is_note = record['kind']=='index_note' or (record.get('text') or term).startswith('Nota:')
        result = {'kind': 'index_note' if is_note else record['kind'],
                  'matches': [{'expression': l['matched_expression'], 'role': l['role']} for l in links],
                  'reference': self.reference(record), 'usable_as_synonym': record.get('usable_as_synonym', False)}
        if is_note: result['text'] = self.text(record.get('text', term), record)
        else:
            result['term'] = self.text(term, record)
            if record.get('cells'):
                result['matched_columns'] = [l['role'].split(':',1)[1] for l in links if ':' in l['role']]
                ambiguous = [c for c in record['cells'].values() if c and c.get('review_status') == 'source_ambiguity_preserved']
                if ambiguous: result['ambiguity_preserved'] = True
                if not links:
                    result['columns'] = {name:without_provenance(cell) if cell else None for name,cell in record['cells'].items()}
            else: result['text'] = self.text(record.get('text', ''), record)
        if record.get('remissions'):
            result['remissions'] = [{k: v for k, v in edge.items() if k in ('directive','target_text','target_kind','target_id','target_ids','printed_target_text','target_code_expressions','candidate_ids','resolution','requires_case_context','implies_clinical_equivalence','table_selector','navigation_selector','partial_navigation','documentary_matching_method','resolution_issue','duplicate_target_ids','external_document_reference','documentary_review')} for edge in record['remissions']]
        if record['kind']=='index_remission':
            for key in ('source_id','directive','target_text','target_kind','target_id','target_ids','printed_target_text','candidate_ids','resolution','requires_case_context','implies_clinical_equivalence','table_selector','navigation_selector','partial_navigation','documentary_matching_method','resolution_issue','duplicate_target_ids','external_document_reference','documentary_review'):
                if key in record: result[key]=record[key]
        for key in ('hierarchy_requires_review','source_hierarchy_review','scope_type','scope_anchor_id'):
            if key in record: result[key]=record[key]
        if record.get('victim_mode'):
            result['victim_mode']=record['victim_mode']
            result['matched_columns']=[l['role'].split(':',1)[1] for l in links if ':' in l['role']]
        return result

    def render(self):
        classification = self.e['classification']
        headings = [self.records[ref] for ref in classification['heading_refs']]
        primary = headings[0]
        hierarchy = [{'code': r.get('code'), 'title': self.text(r.get('description', ''), r)} for ref in classification['hierarchy_refs'] for r in [self.records[ref]] if r.get('description') != 'Notas']
        result = {'api_version': self.e['api_version'], 'view': 'readable', 'code': self.e['code'], 'edition': self.e['edition'],
                  'title': self.text(primary.get('description', ''), primary), 'parent_code': primary.get('code') if classification['representation']=='shared_subdivision' else primary.get('parent_code'),
                  'classification': {'representation': classification['representation'], 'hierarchy': hierarchy, 'reference': self.reference(primary)},
                  'tabular': self.tabular(), 'manual_context': [], 'index_context': [], 'shared_context': [],
                  'pagination': self.e['pagination'], 'quality': {'clinical_validation': 'not_performed', 'automatic_recoding': False, 'case_applicability': 'not_evaluated', 'vol3_visual_review': self.e['quality']['vol3_visual_review']}}
        if self.e.get('source_snapshot_sha256'): result['source_snapshot_sha256']=self.e['source_snapshot_sha256']
        if classification['shared_subdivision_rows']:
            result['classification']['title_scope'] = 'category_heading_with_shared_subdivision'
            result['classification']['subdivisions'] = [{'suffix': row['row']['suffix'], 'text': self.text(row['row']['text'], self.records[row['scheme_ref']])} for rows in classification['shared_subdivision_rows'] for row in rows]
        if primary.get('symbol'): result['classification']['symbol']=primary['symbol']
        for field in ('title_conventions','variants','scope_notes','clinical_input_requirements'):
            if primary.get(field): result['classification'][field]=without_provenance(primary[field])
        if primary.get('coding_relations'):
            result['tabular']['coding_relations']=[{k:v for k,v in without_provenance(relation).items() if k!='text'} for relation in primary['coding_relations']]
        linked = {}
        for link in self.e['context_links']: linked.setdefault(link['record_id'], []).append(link)
        for identifier, links in linked.items():
            record = self.records[identifier]
            target = 'manual_context' if identifier.startswith('v2-') or record['kind'].startswith('manual_') else 'index_context'
            item = self.manual(record, links) if target == 'manual_context' else self.index(record, links)
            if record.get('warnings'): item['warnings'] = record['warnings']
            result[target].append(item)
        # One table context and its conditions, with each anatomical path once.
        # Preserve row references/markers/warnings instead of duplicating the
        # same column, matched code and interpretation for every path.
        groups = {}; remaining = []
        for item in result['index_context']:
            if item['kind'] != 'neoplasm_table_row' or item.get('remissions') or item.get('ambiguity_preserved'):
                remaining.append(item); continue
            key = tuple((m['expression'],m['role']) for m in item['matches'])
            group = groups.setdefault(key, {'kind':'neoplasm_table_entries', 'matches':item['matches'], 'matched_columns':item['matched_columns'], 'usable_as_synonym':False, 'entries':[]})
            entry = {'term':item['term'], **item['reference']}
            if item.get('warnings'): entry['warnings'] = item['warnings']
            group['entries'].append(entry)
        result['index_context'] = remaining + list(groups.values())
        result['retrieved_context_records'] = len(linked)
        tabular_ids = set(classification['heading_refs'] + classification['hierarchy_refs'] + classification['subdivision_scheme_refs'])
        tabular_ids.update(o['origin_record_id'] for o in self.e['effective_tabular_notes'])
        for identifier, record in self.records.items():
            if identifier in linked or identifier in tabular_ids: continue
            if record['kind']=='manual_document_unit':
                item=self.manual(record,[]);item['role']='supporting_documentary_context'
                result['shared_context'].append(item);continue
            if record['kind'] in ('index_entry','index_note','neoplasm_table_row','abortion_table_row','drug_table_row'):
                item=self.index(record,[])
                item['role']='supporting_documentary_context'
                if record.get('warnings'): item['warnings']=record['warnings']
                result['shared_context'].append(item);continue
            item = {'kind': record['kind'], 'reference': self.reference(record)}
            text = self.table_intro(record) if record.get('header_fragments') else self.text(record.get('text', ''), record)
            if text: item['text'] = text
            if record.get('table'): item['table'] = record['table']
            if record.get('warnings'): item['warnings'] = record['warnings']
            result['shared_context'].append(item)
        result['quality']['records_with_pending_review'] = len(self.e['quality']['pending_or_ambiguous_record_refs'])
        refs=[ref for record in self.records.values() for ref in record.get('manual_references',[])]
        result['quality']['manual_reference_resolution']={'resolved':sum(ref['resolution']=='resolved_exact_address' for ref in refs),'unresolved_or_conflicting':sum(ref['resolution']!='resolved_exact_address' for ref in refs)}
        result['quality']['pagination_meaning']='completeness_of_selected_search_results_only'
        query = self.e['pagination']
        result['evidence_url'] = '/v1/codes/' + self.e['code'] + '?' + urlencode({'view':'evidence', **{k:query[k] for k in ('scope','limit','offset')}})
        result['general_conventions'] = {'description': 'Convenciones compartidas de uso de la CIE-10; referencias completas en evidence_url.', 'record_count': len(self.e['general_convention_refs'])}
        return result


def readable_context(evidence):
    return Reader(evidence).render()

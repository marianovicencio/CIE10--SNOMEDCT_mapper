"""Source-linked conventions; no inferred clinical equivalence or generated codes."""
import re

from cie10.common import code_references
from cie10.processing.volume1.tabular_supplements import add_supplementary_tables
from cie10.processing.volume1.tabular_reviewed import locate_site_table, locate_visual_grading_table
from cie10.processing.volume1.tabular_relations_v7 import resolve_verified_relations

RANGE = re.compile(r"\(([A-Z]\d{2})\s*[–—-]\s*([A-Z]\d{2})\)")
DIRECTIVE = re.compile(r"\b(?:ver|véase|para el|para los|utilice|use|codifique)\b", re.I)


def conventions(text, title=False):
    result = []
    for m in re.finditer(r"\(([^()]*)\)", text):
        value = m.group(1)
        refs = code_references(value)
        kind = "code_reference" if refs else "nonessential_modifier"
        result.append(dict(kind=kind, text=value, span=list(m.span()), references=refs))
    for m in re.finditer(r"\[([^\[\]]+)\]", text):
        value = m.group(1)
        result.append(dict(kind="cross_reference" if DIRECTIVE.search(value) else "alternative_or_explanation",
                           text=value, span=list(m.span()), references=code_references(value)))
    if re.search(r"\bNCOP\b|no clasificad[oa]s? en otra parte", text, re.I):
        result.append(dict(kind="not_elsewhere_classified", requires_more_specific_search=True))
    if re.search(r"\bSAI\b", text):
        result.append(dict(kind="unspecified", meaning="sin otra indicación",
                           requires_check_for_available_detail=True, implies_clinical_equivalence=False))
    if title and re.search(r"\by\b", text, re.I):
        result.append(dict(kind="title_conjunction", interpretation="and_or", auto_expand=False))
    return result


def enrich_tabular(records):
    for r in records:
        r['scope_notes']=[]
        kept=[]
        for entry in r['inclusions']:
            if re.match(r'^(?:las afecciones|los siguientes trastornos|esta categoría abarca)',entry['text'],re.I) and not code_references(entry['text']):
                r['scope_notes'].append(dict(entry,text_role='scope_note',applies_to='category_and_subcategories'))
            else: kept.append(entry)
        r['inclusions']=kept
    codes = {r['code']: r for r in records if r.get('code')}
    children_by_category = {}
    for code in codes:
        if '.' in code:
            children_by_category.setdefault(code.split('.')[0], []).append(code)
    # Contexts inherit only through explicit, strictly enclosing category ranges.
    contexts = []
    for r in records:
        match = RANGE.search(r['description']) if r['kind'] == 'context' else None
        if match:
            contexts.append((r, match.group(1), match.group(2)))
    note_blocks = []
    preceding_scope = None
    for r in records:
        if r.get('code'):
            preceding_scope = None
        if any(c['id'] == r['id'] for c, _, _ in contexts):
            preceding_scope = r['id']
        if r['kind'] == 'context' and re.fullmatch(r'Notas?', r['description'], re.I) and preceding_scope:
            r['scope_parent_ref'] = preceding_scope
            r['numbered_notes'] = []
            for index, line in enumerate(r['raw_lines']):
                match = re.match(r'^(\d+)\.\s+(.+)', line)
                source = r['sources'][min(index, len(r['sources'])-1)]
                if match:
                    r['numbered_notes'].append(dict(number=int(match[1]), text=match[2], sources=[source]))
                elif r['numbered_notes']:
                    r['numbered_notes'][-1]['text'] += ' ' + line
                    r['numbered_notes'][-1]['sources'].append(source)
            note_blocks.append(r)
    for r in records:
        code = r.get('code')
        own_range = next(((lo, hi) for c, lo, hi in contexts if c['id'] == r['id']), None)
        ancestors = []
        for c, lo, hi in contexts:
            if c['id'] == r['id'] or (c['sources'][0]['pdf_page'], c['sources'][0].get('line_id', 0)) > (r['sources'][0]['pdf_page'], r['sources'][0].get('line_id', 0)):
                continue
            if (code and lo <= code[:3] <= hi) or (own_range and lo <= own_range[0] and own_range[1] <= hi and own_range != (lo, hi)):
                ancestors.append(c)
        ancestors.sort(key=lambda c: (c['sources'][0]['pdf_page'], c['sources'][0].get('line_id', 0)))
        parent = codes.get(r.get('parent_code'))
        if parent:
            ancestors.append(parent)
        ancestor_ids = {a['id'] for a in ancestors}
        ancestors.extend(n for n in note_blocks if n['scope_parent_ref'] in ancestor_ids and n['id'] != r['id'])
        r['ancestor_refs'] = list(dict.fromkeys(a['id'] for a in ancestors))
        r['applicable_note_refs'] = [dict(record_id=a['id'], fields=[k for k in ('inclusions','exclusions','instructions','notes','unclassified','descriptive_text','scope_notes') if a.get(k)],
                                             scope='subordinate_codes', sources=a['sources'][:1])
                                      for a in ancestors if any(a.get(k) for k in ('inclusions','exclusions','instructions','notes','unclassified','descriptive_text','scope_notes'))]
        # Keep documentary definitions available separately. A type definition
        # never becomes an inclusion/exclusion of every subordinate diagnosis.
        r['applicable_note_refs'].extend(dict(record_id=a['id'],fields=['definition_blocks'],
            scope='documentary_context_only',sources=a['sources'][:1])
            for a in ancestors if a.get('definition_blocks'))
        r['title_conventions'] = conventions(r['description'], title=True)
        r['inclusion_semantics'] = dict(exhaustive=False, equivalent_synonyms=False, requires_heading_context=True)
        r['coding_relations'] = []
        r['semantic_review_issues'] = []

        def relation(text, sources, level):
            refs = code_references(re.sub(r'(?<=\d)\s+([†*])', r'\1', text))
            stars = [ref for ref in refs if ref.endswith('*')]
            daggers = [ref for ref in refs if ref.endswith('†')]
            explicit_daggers = bool(daggers)
            contextual_etiology = bool(code and level=='inclusions' and len(stars)==1 and not daggers and r.get('symbol') not in ('*','†') and '†' not in text)
            if contextual_etiology:
                daggers=[code]
            if code and not daggers and (r.get('symbol')=='†' or ('†' in text and stars)):
                daggers = [code+'†']
            if code and (stars or explicit_daggers or (level == 'heading' and r.get('symbol') in ('†','*'))):
                r['coding_relations'].append(dict(kind='etiology_manifestation', scope=level,
                    etiology_codes=daggers or ([code + '†'] if r.get('symbol') == '†' else []),
                    manifestation_codes=stars or ([code + '*'] if r.get('symbol') == '*' else []),
                    manifestation_must_not_be_used_alone=True,
                    sequencing='depends_on_morbidity_or_mortality_rules', sources=sources,
                    etiology_basis='inclusion_context' if contextual_etiology else 'explicit_symbol_or_reference',
                    resolution='inclusion_context_pair' if contextual_etiology else ('explicit_pair' if ((daggers or r.get('symbol') == '†') and (stars or r.get('symbol') == '*')) else 'requires_term_specific_pair')))
            if re.search(r'\bcódigo adicional\b', text, re.I):
                usage_note = bool(re.search(r'esta categoría puede usarse como código adicional', text, re.I))
                optional = bool(re.search(r'si (?:(?:se|lo) )?desea', text, re.I))
                conditional = bool(refs and re.search(r'^(?:Use|Utilice) código adicional para identificar la presencia de', text, re.I))
                r['coding_relations'].append(dict(kind='additional_code', scope=level, text=text,
                    optional=optional,
                    requirement='category_usage_note' if usage_note else ('optional' if optional else ('conditional_on_documented_condition' if conditional else 'requires_instruction_review')),
                    target_references=refs, sources=sources, executable=False))
            if re.search(r'\b(?:ver|véase)\b', text,re.I) or (refs and re.match(r'^(?:Las|Los|Todas las|Todos los) (?:afecciones|enfermedades|trastornos|estados) (?:listad|enumerad|clasificad)',text,re.I)):
                targets = [codes[ref]['id'] for ref in refs if ref in codes]
                for ref in refs:
                    compact = re.sub(r'\s+','',ref)
                    for ctx,lo,hi in contexts:
                        if compact in (lo+'–'+hi,lo+'-'+hi,lo+'—'+hi):
                            targets.append(ctx['id'])
                    wildcard = re.fullmatch(r'([A-Z]\d{2})\.[–—-]',compact)
                    if wildcard and wildcard[1] in codes:
                        targets.append(codes[wildcard[1]]['id'])
                    bounds = re.fullmatch(r'([A-Z]\d{2}(?:\.\d+)?)\s*[–—-]\s*([A-Z]\d{2}(?:\.\d+)?)',compact)
                    if bounds and not any(compact in (lo+'–'+hi,lo+'-'+hi,lo+'—'+hi) for _,lo,hi in contexts):
                        targets.extend(item['id'] for key,item in codes.items() if bounds[1]<=key<=bounds[2] and len(key)==len(bounds[1]))
                targets = list(dict.fromkeys(targets))
                subdivision = bool(re.search(r'carácter|subdivisiones|subclasificaciones|código de sitio', text, re.I))
                before = bool(re.search(r'antes de', text, re.I))
                r['coding_relations'].append(dict(kind='shared_subdivisions' if subdivision else 'cross_reference',
                    text=text, target_references=refs, target_record_refs=targets, sources=sources,
                    resolution='anchor_located_table_unresolved' if subdivision and targets else
                               ('target_located' if targets and not before else 'unresolved'),
                    target_location='before_category' if before else 'referenced_location',
                    executable=False))
                note_number = re.search(r'\bnota\s+(\d+)\b', text, re.I)
                if note_number:
                    candidates = [(n, item) for n in note_blocks if n['id'] in r['ancestor_refs']
                                  for item in n['numbered_notes'] if item['number'] == int(note_number[1])]
                    if len(candidates) == 1:
                        block, item = candidates[0]
                        r['coding_relations'][-1].update(resolution='numbered_note_located',
                            target_record_refs=[block['id']], target_note_number=item['number'], target_sources=item['sources'])
        relation(r['description'], r['sources'][:1], 'heading')
        for field in ('inclusions','exclusions','notes','instructions','unclassified','descriptive_text'):
            for entry in r.get(field,[]):
                entry['conventions'] = conventions(entry['text'])
                # Exclusion codes are destinations, never dual-coding instructions for this code.
                if field not in ('exclusions','instructions','notes'):
                    relation(entry['text'], entry.get('sources', [entry['source']]), field)
        # Instructions may wrap across physical lines: interpret each explicit block once.
        blocks = {}
        for field in ('instructions','notes'):
            for entry in r[field]:
                blocks.setdefault((field,entry.get('block_id')), []).append(entry)
        for (field,_),entries in blocks.items():
            text = ' '.join(e['text'] for e in entries)
            relation(text,[s for e in entries for s in e.get('sources',[e['source']])],field)
        if any(x.get('resolution')=='explicit_pair' and x.get('scope')=='inclusions' for x in r['coding_relations']):
            for x in r['coding_relations']:
                if x.get('resolution')=='requires_term_specific_pair' and x.get('scope')=='heading' and r.get('symbol') in ('†','*'):
                    x['resolution']='term_pairs_located'
        for rel in r['coding_relations']:
            if rel.get('resolution') in ('unresolved','anchor_located_table_unresolved','requires_term_specific_pair') or rel.get('requirement') == 'requires_instruction_review':
                r['semantic_review_issues'].append(dict(kind=rel['kind'], reason=rel.get('resolution', rel.get('requirement')), sources=rel['sources']))
        if r['semantic_review_issues']:
            r['warnings'].append('semantic_relation_requires_review')
        if code:
            children = sorted(children_by_category.get(code, []))
            r['code_structure'] = dict(observed_children=children, has_observed_subcategories=bool(children),
                final_code_status='requires_subcategory' if children else 'not_verified',
                supplementary_characters_validated=False)
    # Shared tables remain separate from the preceding diagnosis. Only explicit
    # category references in their preamble define applicability.
    for scheme in records:
        if scheme['kind'] != 'shared_subdivision_scheme':
            continue
        rows, preamble = [], []
        for index, text in enumerate(scheme['raw_lines']):
            match = re.match(r'^\.(\d{1,2})([†*]?)\s+(.+)', text)
            source = scheme['sources'][min(index, len(scheme['sources']) - 1)]
            if 'subdivision_heading_line_refs' in scheme and source not in scheme['subdivision_heading_line_refs']:
                match = None
            if match:
                rows.append(dict(suffix='.' + match.group(1), symbol=match.group(2), text=match.group(3), sources=[source]))
            elif rows:
                rows[-1]['text'] += ' ' + text
                rows[-1]['sources'].append(source)
            else:
                preamble.append(text)
        header = ' '.join(preamble)
        targets = set()
        for ref in code_references(header):
            bounds = re.fullmatch(r'([A-Z]\d{2})\s*[–—-]\s*([A-Z]\d{2})', ref)
            if bounds:
                targets.update(c for c in codes if len(c) == 3 and bounds[1] <= c <= bounds[2])
            elif ref in codes and len(ref) == 3:
                targets.add(ref)
        fourth = bool(re.search(r'cuarto carácter', header, re.I))
        for row in rows:
            row['manifestation_references']=[ref for ref in code_references(row['text']) if ref.endswith('*')]
            if row['symbol']=='†':
                row['etiology_scope']={'category_references':sorted(targets),'suffix':row['suffix'], 'symbol':'†'}
        scheme['subdivision_table'] = dict(preamble=header, rows=rows, target_categories=sorted(targets),
            resolution='explicit_fourth_character_table' if fourth and targets and rows else 'requires_review',
            generates_final_codes=False)
        if fourth and targets and rows:
            for c in targets:
                target = codes[c]
                target.setdefault('subdivision_scheme_refs', []).append(scheme['id'])
                target['code_structure']['final_code_status'] = 'requires_subcategory'
                target['code_structure']['shared_suffixes'] = [row['suffix'] for row in rows]
                for rel in target['coding_relations']:
                    if rel['kind'] == 'shared_subdivisions':
                        rel['table_record_refs'] = [scheme['id']]
                        rel['resolution'] = 'explicit_table_located'
                target['semantic_review_issues'] = [i for i in target['semantic_review_issues'] if i['kind'] != 'shared_subdivisions']
        else:
            scheme['semantic_review_issues'].append(dict(kind='subdivision_table', reason='scope_or_rows_unresolved', sources=scheme['sources'][:1]))
            scheme['warnings'].append('semantic_relation_requires_review')
    for r in records:
        if not r['semantic_review_issues']:
            r['warnings'] = [w for w in r['warnings'] if w != 'semantic_relation_requires_review']
    add_supplementary_tables(records)
    locate_site_table(records)
    locate_visual_grading_table(records)
    resolve_verified_relations(records)
    for r in records:
        r['clinical_input_requirements']=[]
        for rel in r['coding_relations']:
            if rel.get('resolution') not in ('requires_term_specific_pair','inclusion_context_pair'):
                continue
            if r.get('code') and (not rel.get('etiology_codes') or rel.get('etiology_basis') == 'inclusion_context') and rel.get('manifestation_codes'):
                counterparts=[codes.get(ref.rstrip('*†')) for ref in rel['manifestation_codes']]
                if counterparts and all(c and r['code']+'†' in c.get('code_references',[]) for c in counterparts):
                    rel['etiology_codes']=[r['code']+'†']
                    rel['resolution']='reciprocal_pair_confirmed'
                    rel['reciprocal_record_refs']=[c['id'] for c in counterparts]
                    continue
            if rel.get('scope')=='heading' and r.get('symbol')=='*' and re.search(r'clasificad[oa]s? en (?:otra|otras) parte',r['description'],re.I):
                rel['resolution']='patient_etiology_required'
                r['clinical_input_requirements'].append({'kind':'etiology_code','reason':'manifestation_code_cannot_stand_alone'})
            elif rel.get('scope')=='heading' and r.get('symbol') in ('†','*') and r.get('code_structure',{}).get('has_observed_subcategories'):
                rel['resolution']='select_subcategory_then_pair'
                r['clinical_input_requirements'].append({'kind':'subcategory_selection','reason':'pair_depends_on_subcategory_and_term'})
        # Clinical input required by an explicitly generic heading is not a PDF parsing failure.
        r['semantic_review_issues']=[issue for issue in r['semantic_review_issues'] if not (
            issue['reason']=='requires_term_specific_pair' and any(rel.get('resolution') in ('patient_etiology_required','select_subcategory_then_pair','reciprocal_pair_confirmed') and rel['sources']==issue['sources'] for rel in r['coding_relations']))]
        if not r['semantic_review_issues']:
            r['warnings']=[w for w in r['warnings'] if w!='semantic_relation_requires_review']
        if r['unclassified']:
            r['warnings'].append('unclassified_text_requires_review')
        if r.get('note_structure_issues'):
            r['warnings'].append('structural_issue_requires_review')
        r['warnings']=list(dict.fromkeys(r['warnings']))
        r['automatic_validation']={
            'text_classification_complete':not bool(r['unclassified']),
            'note_structure_resolved':not bool(r.get('note_structure_issues')),
            'semantic_relations_resolved':not bool(r['semantic_review_issues']),
            'clinical_validation':'not_performed'}
    return records

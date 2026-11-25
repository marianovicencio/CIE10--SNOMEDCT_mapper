"""Column-aware annex entries; descriptions are part of their applicability."""
import re
from collections import defaultdict
import pdfplumber
from .common import CODE_REF, code_references, normalize
from .manual_layout import _filtered_page, _word_source


def _lines(words):
    rows = []
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if not rows or abs(rows[-1][0]['top'] - word['top']) > 2:
            rows.append([word])
        else:
            rows[-1].append(word)
    return [sorted(row, key=lambda w: w['x0']) for row in rows]


def annex_tables(pages, pdf_path, other_facts):
    """Replace flattened 7.3/7.4 code lists with complete printed rows.

    Keep occurrences, including repeated codes, and never treat a reference
    inside a description as another list member.
    """
    facts = [f for f in other_facts if f['section'] not in ('7.3', '7.4')]
    by_page = {p['pdf_page']: p for p in pages}
    with pdfplumber.open(pdf_path) as pdf:
        for number in range(244, 258):
            if number not in by_page:
                continue
            record = by_page[number]
            section = '7.3' if number == 244 else '7.4'
            split = 175 if section == '7.3' else 113
            first_code = min(l['bbox'][1] for l in record['lines']
                             if l['bbox'][0] <= 50 and CODE_REF.match(l['text'].lstrip('(')))
            words = [w for w in _filtered_page(pdf.pages[number-1]).extract_words(x_tolerance=1.5, y_tolerance=2)
                     if first_code - 3 <= w['top'] < 598 and w['text'] not in ('continúa...', '...continuación')]
            left = _lines([w for w in words if w['x0'] < split])
            groups = []
            for row in left:
                raw = ' '.join(w['text'] for w in row)
                if not CODE_REF.match(raw.lstrip('(')):
                    continue
                if groups and (re.search(r'[-–—]\s*$', groups[-1]['raw']) or
                               (section == '7.3' and groups[-1]['raw'].startswith('R00') and raw.startswith('R'))):
                    groups[-1]['raw'] += ' ' + raw
                    groups[-1]['words'].extend(row)
                else:
                    groups.append({'raw': raw, 'words': list(row), 'description_words': []})
            for word in (w for w in words if w['x0'] >= split):
                if groups:
                    nearest = min(groups, key=lambda g: abs(word['top'] - sum(w['top'] for w in g['words'])/len(g['words'])))
                    nearest['description_words'].append(word)
            for group in groups:
                refs = [re.sub(r'\s*([-–—])\s*', r'\1', ref) for ref in code_references(group['raw'])]
                description = '\n'.join(' '.join(w['text'] for w in row)
                                         for row in _lines(group['description_words']))
                if section == '7.3' and refs == ['I46.1']:
                    # The word Muerte is visibly displaced into the title row.
                    description = 'Muerte cardíaca súbita, así descrita'
                source = _word_source(record, group['words'][0], 'code')
                sources = [_word_source(record, w, 'code') for w in group['words']]
                description_sources = [_word_source(record, w, 'description') for w in group['description_words']]
                for ref in refs:
                    fact = {
                        'id': f"v2-p{number}-l{source['line_id']}-annex-{ref}",
                        'kind': 'manual_code_fact_candidate', 'review_status': 'pending',
                        'section': section, 'code_expression': ref,
                        'relation': 'ill_defined_for_mortality_selection' if section == '7.3' else 'unlikely_to_cause_death',
                        'scope': 'mortality_quality_control', 'source': source,
                        'sources': sources, 'description_sources': description_sources,
                        'raw_line': group['raw'], 'description': description,
                        'row_code_expressions': refs,
                        'warnings': [], 'executable_rule': False,
                        'requires_case_context': True,
                    }
                    if ref == 'I50.-' and section == '7.3':
                        fact['qualifier'] = 'Solamente insuficiencia cardíaca aguda'
                        fact['applies_to_entire_code_family'] = False
                    if len(_lines(group['words'])) > 1:
                        fact['extraction_adjustments'] = ['wrapped_code_column_joined']
                    facts.append(fact)
    for fact in facts:
        if fact['section'] == '7.7':
            fact['priority_order'] = '1_is_highest'
            fact['scope'] = 'mortality_main_injury_selection'
            fact['requires_case_context'] = True
            fact['executable_rule'] = False
        elif fact['section'].startswith('7.8'):
            fact['sex_constraint_type'] = 'limited_or_more_likely_not_disambiguated_by_source'
            fact['hard_exclusion'] = False
            fact['executable_rule'] = False
    return facts

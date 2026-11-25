"""Corrections checked against the exact 2018 PDF; never overwrite raw evidence."""
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import json
from cie10.common import code_references

SOURCE_SHA = 'efa4c93e31d97b2b54dcc2e325537e66ff27667e266d4d311e72df4bd189d62c'

@lru_cache(maxsize=1)
def local_note_rules():
    return json.loads(Path(__file__).with_name('reviewed_note_blocks_v7.json').read_text(encoding='utf-8'))


def reviewed_page_layout(page):
    if page.get('source_sha256') != SOURCE_SHA or page.get('pdf_page') != 491:
        return page
    result = deepcopy(page)
    lines = {line['id']:line for line in result['lines']}
    if lines.get(41,{}).get('text') == 'J10.1' and lines.get(40,{}).get('text','').startswith('Influenza con otras'):
        lines[40]['text'] = 'J10.1 '+lines[40]['text']
        lines[40]['merged_line_ids'] = [40,41]
        result['lines'] = [line for line in result['lines'] if line['id']!=41]
    if lines.get(57,{}).get('text','').startswith('J10.8 ') and lines.get(55,{}).get('text','').startswith('Influenza, con otras'):
        lines[55]['text'] = 'J10.8 '+lines[55]['text']
        lines[55]['merged_line_ids'] = [55,57]
        lines[57]['text'] = lines[57]['text'][6:]
    if lines.get(37,{}).get('text') == '⎭' and 36 in lines:
        result['lines'].remove(lines[37])
        result['lines'].insert(result['lines'].index(lines[36]),lines[37])
    if not any('Miocarditis (aguda)' in line['text'] for line in result['lines']):
        # The original crop excludes a real final term by less than one point.
        # Re-read the visible PDF margin, not a clinically inferred term.
        import pdfplumber
        from cie10.common import ROOT
        from cie10.processing.extract import is_visible, is_watermark, make_line
        with pdfplumber.open(ROOT/'data/raw/CIE-10_2018_VOL1.pdf') as pdf:
            p=pdf.pages[490]
            box=p.cropbox or p.bbox
            visible=p.filter(lambda o:o['object_type']!='char' or (is_visible(o,box) and not is_watermark(o)))
            for raw in visible.extract_text_lines(x_tolerance=1.5,y_tolerance=2,return_chars=True):
                if raw['text']=='Miocarditis (aguda)' and 635 < raw['top'] < 637:
                    term=make_line(raw,None,66)
                    term['glyphs']=[{k:c[k] for k in ('text','x0','x1','top','bottom')} for c in raw['chars']]
                    term['recovered_from_pdf_margin']=True
                    result['lines'].append(term)
    # Original PDF layout remains in the cached page's layout_lines; expose the
    # local adjustment through provenance on the affected heading.
    return result


def apply_reviewed_layout(record):
    source = next(iter(record.get('sources', [])), {})
    if source.get('source_sha256') != SOURCE_SHA:
        return
    for rule in local_note_rules().get(record.get('code',record['id']),[]):
        fragments=record[rule['field']]
        if [[f['source']['pdf_page'],f['source']['line_id'],f['text']] for f in fragments] != rule['expected']:
            continue
        sources=[f['source'] for f in fragments]
        record[rule['field']]=[dict(item,source=sources[0],sources=sources,
            block_id=fragments[0].get('block_id'),composition='visually_reviewed_layout')
            for item in rule['entries']]
        record.setdefault('reviewed_corrections',[]).append(dict(kind=rule['reason'],
            basis='pdf_visual_review',sources=sources,review_version='v7'))
        if any(item.get('source_ambiguity_preserved') for item in rule['entries']):
            record['warnings'].append('source_compound_line_preserved')
    if record.get('code') == 'A88' and source['pdf_page'] == 142:
        orphan = [f for f in record['unclassified'] if f['source']['line_id'] == 11 and f['text'] == '⎫']
        if len(orphan) == 1 and record['exclusions']:
            record['unclassified'] = [f for f in record['unclassified'] if f not in orphan]
            record['exclusions'] = [dict(orphan[0], block_id=record['exclusions'][0]['block_id'])] + record['exclusions']
            record.setdefault('reviewed_corrections', []).append(dict(
                kind='brace_block_boundary', source=orphan[0]['source'], basis='pdf_visual_review'))
    if record.get('code') == 'N11.1' and source['pdf_page'] == 643:
        fragments = record['unclassified']
        raw = ' '.join(f['text'] for f in fragments)
        left = ('anomalía', 'estrechez', 'obstrucción', 'torsión')
        right = ('unión pelviureteral', 'unión pieloureteral', 'uréter')
        prefix = 'Pielonefritis (crónica) asociada con:'
        if fragments and fragments[0]['text'] == prefix and all(t in raw for t in left+right):
            sources = [f['source'] for f in fragments]
            record['unclassified'] = [fragments[0]] + [dict(
                text='• '+a+' de '+b, source=fragments[1]['source'], sources=sources,
                block_id=fragments[0].get('block_id'), composition='reviewed_brace_cartesian_product')
                for a in left for b in right]
            record.setdefault('reviewed_corrections', []).append(dict(
                kind='two_brace_lists', sources=sources, basis='pdf_visual_review', combinations=12))
    if record.get('code')=='N18.5' and source['pdf_page']==648:
        record['unclassified']=deepcopy(record['unclassified'])
        for fragment in record['unclassified']:
            if fragment['source']['line_id']==9 and fragment['text']=='• Apoplejía† (I68.8*) ':
                fragment['starts_independent_brace_group']=True
                record.setdefault('reviewed_corrections',[]).append(dict(
                    kind='independent_brace_group',source=fragment['source'],basis='pdf_visual_review'))
    # The printed list and text layer flatten these nested bullets. Explicit hints
    # avoid accidentally nesting later siblings (e.g. tuberculosis under syphilis).
    children = {'E74.4': (292, {30, 31}), 'G05.0': (379, {19, 20}),
                'I46.1': (467, {18, 19}), 'J18': (495, {7, 8, 9})}
    spec = children.get(record.get('code'))
    if spec:
        page, lines = spec
        for field in ('inclusions', 'exclusions', 'unclassified'):
            record[field] = deepcopy(record[field])
            for fragment in record[field]:
                s = fragment['source']
                if s['pdf_page'] == page and s['line_id'] in lines:
                    fragment['layout_x'] = s['bbox'][0] + 10
                    record.setdefault('reviewed_corrections', []).append(dict(
                        kind='nested_bullet_layout', source=s, basis='pdf_visual_review'))
    corrections = {'F02.0': ('G3l.0†', 'G31.0†', 7),
                   'F02.2': ('Gl0†', 'G10†', 19)}
    spec = corrections.get(record.get('code'))
    if spec and source['pdf_page'] == 306 and source['line_id'] == spec[2]:
        old, new, _ = spec
        if old in record['description']:
            record['description'] = record['description'].replace(old, new)
            record['raw_code_references'] = record.get('code_references',code_references('\n'.join(record['raw_lines'])))
            record['code_references'] = code_references('\n'.join(record['raw_lines']).replace(old,new))
            record['warnings'] = [w for w in record['warnings'] if w!='suspected_code_glyph_error_not_corrected']
            record['warnings'].append('source_reference_glyph_corrected')
            record.setdefault('reviewed_corrections', []).append(dict(
                kind='reference_glyph', original=old, corrected=new,
                source=source, basis='pdf_visual_review'))


def locate_site_table(records):
    """Locate the actual table, preserving its raw rows and optional usage note.

    This resolves navigation, not the clinical choice of site or local encoding.
    The two-dimensional cells are deliberately not turned into final codes.
    """
    candidates = [r for r in records if r['description'] == 'Sitio del compromiso osteomuscular'
                  and r['sources'][0].get('source_sha256') == SOURCE_SHA]
    if len(candidates) != 1:
        return
    table = candidates[0]
    table['site_table'] = dict(raw_lines=table['raw_lines'][1:], sources=table['sources'][1:],
        resolution='source_located', optional=True, generates_final_codes=False,
        cell_structure_validated=False)
    for record in records:
        resolved_sources = []
        for rel in record['coding_relations']:
            if (rel['kind'] in ('shared_subdivisions', 'cross_reference')
                    and rel.get('target_location') == 'before_category'
                    and any(ref in ('M00–M25', 'M00-M25', 'M00—M25') for ref in rel.get('target_references', []))):
                rel.update(resolution='table_source_located', table_record_refs=[table['id']],
                           target_sources=table['sources'], table_cells_validated=False,
                           executable=False)
                resolved_sources.append(rel['sources'])
        record['semantic_review_issues'] = [i for i in record['semantic_review_issues']
            if not (i['kind'] in ('shared_subdivisions', 'cross_reference') and i['sources'] in resolved_sources)]


def locate_visual_grading_table(records):
    candidates = [r for r in records if r.get('code') == 'H54.9'
                  and r['sources'][0].get('source_sha256') == SOURCE_SHA
                  and any(t.startswith('Cuadro 1. Revisión propuesta de grados') for t in r['raw_lines'])]
    if len(candidates) != 1:
        return
    table = candidates[0]
    for record in records:
        if record.get('code') != 'H54':
            continue
        for rel in record['coding_relations']:
            if rel['kind']=='cross_reference' and 'tabla' in rel['text'] and 'H54' in rel['target_references']:
                rel.update(resolution='table_source_located', table_record_refs=[table['id']],
                           target_sources=table['sources'], table_cells_validated=False, executable=False)

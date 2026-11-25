"""Resolve verified destinations without selecting a patient's final code."""
import re
from cie10.processing.volume1.tabular_reviewed import SOURCE_SHA


def verified(record):
    return bool(record.get('sources')) and record['sources'][0].get('source_sha256') == SOURCE_SHA


def unique(records, predicate):
    found=[r for r in records if verified(r) and predicate(r)]
    return found[0] if len(found)==1 else None


def resolve(record, relation, **values):
    old_reason=relation.get('resolution',relation.get('requirement'))
    relation.update(values)
    record['semantic_review_issues']=[i for i in record['semantic_review_issues'] if not (
        i['kind']==relation['kind'] and i['sources']==relation['sources'] and i['reason']==old_reason)]


def extract_rows(record, pattern, start):
    """Retain row details as raw lines: braces inside cells are not expanded."""
    rows=[]
    for i in range(start,len(record['raw_lines'])):
        text=record['raw_lines'][i]
        source=record['sources'][i]
        match=re.match(pattern,text)
        if match:
            rows.append(dict(value=match[1],text=match[2],source=source,
                raw_lines=[text],sources=[source]))
        elif rows:
            rows[-1]['raw_lines'].append(text)
            rows[-1]['sources'].append(source)
    return rows if [r['value'] for r in rows]==[str(i) for i in range(10)] else []


def add_table(record, start, pattern, **metadata):
    # One source per physical line is required for exact row provenance.
    if len(record['raw_lines'])!=len(record['sources']):
        return None
    rows=extract_rows(record,pattern,start)
    if not rows:
        return None
    first=next(i for i in range(start,len(record['raw_lines'])) if re.match(pattern,record['raw_lines'][i]))
    table=dict(preamble=' '.join(record['raw_lines'][start:first]),
        preamble_sources=record['sources'][start:first],rows=rows,
        row_headers_validated=True,row_details_validated=False,
        generates_final_codes=False,**metadata)
    record['referenced_table']=table
    return table


def resolve_verified_relations(records):
    dorsal=unique(records,lambda r:r['description']=='Dorsopatías (M40–M54)')
    renal=unique(records,lambda r:r['description']=='Enfermedades glomerulares (N00–N08)')
    location=unique(records,lambda r:r['description']=='Código del lugar de ocurrencia')
    dorsal_table=None
    renal_table=None
    if dorsal and any('excepto en M50 y M51' in t for t in dorsal['raw_lines']):
        start=next((i for i,t in enumerate(dorsal['raw_lines']) if t.startswith('La siguiente subclasificación suplementaria')),None)
        if start is not None:
            dorsal_table=add_table(dorsal,start,r'^(\d)\s+(.+)',
                kind='optional_site_subclassification',optional=True,excluded_categories=['M50','M51'])
    if renal:
        start=next((i for i,t in enumerate(renal['raw_lines']) if t.startswith('Las subdivisiones de cuarto carácter')),None)
        if start is not None and any('categorías N00–N07' in t for t in renal['raw_lines']):
            renal_table=add_table(renal,start,r'^\.(\d)\s+(.+)',
                kind='fourth_character_subdivision',target_categories=['N0'+str(i) for i in range(8)],
                selection_requires_morphological_evidence=True)
            if renal_table:
                # The table follows an exclusion but is not itself an exclusion.
                # Preserve the original fragments while giving it its own field.
                table_positions={(s['pdf_page'],s['line_id']) for s in renal['sources'][start:]}
                renal['exclusions']=[e for e in renal['exclusions'] if not any(
                    (s['pdf_page'],s['line_id']) in table_positions for s in e.get('sources',[e['source']]))]
    location_table=None
    if location and any('separadas además' in t for t in location['raw_lines']):
        location_table=add_table(location,1,r'^\.(\d)\s+(.+)',
            kind='place_of_occurrence',encoding='separate_variable',applicable_range='W00–Y34')
        if location_table:
            # Inclusions/exclusions within each row belong to that place value,
            # not to the complete table. Their verbatim lines remain in the rows.
            location['inclusions']=[]
            location['exclusions']=[]
            location['descriptive_text']=[]
    note_targets={}
    for code,desc in [('D37','(D37–D48)'),('Y10','(Y10–Y34)')]:
        target=unique(records,lambda r:r['kind']=='context' and r['description'].endswith(desc) and bool(r['notes']))
        if target:
            note_targets[code]=target
    for record in records:
        if not verified(record):
            continue
        for rel in record['coding_relations']:
            text=rel.get('text','')
            if (rel['kind']=='shared_subdivisions' and dorsal_table
                    and 'M40–M54' in rel.get('target_references',[]) and 'código de sitio' in text
                    and record.get('code') not in ('M50','M51')):
                resolve(record,rel,resolution='verified_table_located',table_record_refs=[dorsal['id']],
                    target_sources=dorsal['sources'],row_headers_validated=True,row_details_validated=False,executable=False)
            elif (rel['kind']=='shared_subdivisions' and renal_table and 'N00' in rel.get('target_references',[])
                    and record.get('code') in renal_table['target_categories'] and 'cuarto carácter' in text):
                resolve(record,rel,resolution='verified_table_located',table_record_refs=[renal['id']],
                    target_sources=renal['sources'],row_headers_validated=True,row_details_validated=False,
                    selection_requires_morphological_evidence=True,executable=False)
                record.setdefault('subdivision_scheme_refs',[]).append(renal['id'])
                record['code_structure'].update(shared_suffixes=['.'+str(i) for i in range(10)],final_code_status='requires_subcategory')
            elif (rel['kind']=='cross_reference' and location_table
                    and re.fullmatch(r'\[Ver nota al inicio de este capítulo sobre lugar de ocurrencia\]',text,re.I)):
                resolve(record,rel,resolution='verified_note_and_table_located',
                    target_record_refs=[location['id']],table_record_refs=[location['id']],
                    target_note_text=location_table['preamble'],target_sources=location_table['preamble_sources'],
                    encoding='separate_variable',row_details_validated=False,executable=False)
            elif rel['kind']=='cross_reference':
                match=re.search(r'ver (?:la )?nota antes de ([A-Z]\d{2})',text,re.I)
                if match and match[1] in note_targets:
                    target=note_targets[match[1]]
                    resolve(record,rel,resolution='verified_preceding_note_located',
                        raw_target_references=rel.get('target_references',[]),target_references=[match[1]],
                        resolved_reference_text=match[0],target_record_refs=[target['id']],
                        target_note_text=' '.join(e['text'] for e in target['notes']),
                        target_sources=[s for e in target['notes'] for s in e.get('sources',[e['source']])],executable=False)
            elif (rel['kind']=='additional_code' and record.get('code')=='Z37'
                    and text.startswith('Esta categoría es sugerida como código adicional')
                    and 'historia clínica de la madre' in text):
                resolve(record,rel,requirement='category_usage_note',usage_modality='suggested',
                    applies_to='maternal_record',relates_to='current_category',executable=False)
        if record.get('code')=='S32':
            for table in record.get('supplementary_tables',[]):
                rows=table['rows']
                if len(rows)!=2 or [(x['raw_suffix'],x['text']) for x in rows]!=[('0','cerrada'),('l','abierta')]:
                    continue
                source=rows[1]['sources'][0]
                if (source['pdf_page'],source['line_id'])!=(857,42):
                    continue
                rows[1].update(suffix='1',correction_basis='pdf_visual_review')
                table['resolution']='explicit_supplementary_table'
                record.setdefault('reviewed_corrections',[]).append(dict(kind='supplementary_suffix_glyph',
                    original='l',corrected='1',source=source,basis='pdf_visual_review'))
                record['semantic_review_issues']=[i for i in record['semantic_review_issues']
                    if not (i['kind']=='supplementary_table' and i['reason']=='ambiguous_suffix_glyph')]

"""Preserve source defects separately from documentary formatting interpretations."""
from .common import code_references

CELL_REVIEWS = {
 ('v3-p563-table-y1509','uncertain_or_unknown_behavior'):('D37.0.','D37.0','trailing_punctuation'),
 ('v3-p579-table-y4380','malignant_primary'):('.C67.5','C67.5','leading_punctuation'),
 ('v3-p735-l6','undetermined'):('y14.-','Y14.-','lowercase_letter'),
 ('v3-p749-l12','poisoning_chapter_xix'):('T50.9–','T50.9','extra_dash_after_complete_code'),
}
AMBIGUOUS = {
 ('v3-p669-l18','accidental'):'X48.',
 ('v3-p685-l11','undetermined'):'Y14.',
 ('v3-p755-l28','undetermined'):'Y18.–Y14.–',
}


def review_cells(records):
    for r in records:
        cells=r.get('cells')
        if cells is None and 'codes_by_context' in r:
            cells={k:({'text':v,'sources':r['sources'], 'valid_shape':not any(w=='invalid_cell_'+k for w in r['warnings'])}
                      if v else None) for k,v in r['codes_by_context'].items()}
            r['cells']=cells
        if not cells: continue
        for k,c in cells.items():
            if not c: continue
            spec=CELL_REVIEWS.get((r['id'],k)); ambiguous=AMBIGUOUS.get((r['id'],k))
            if spec and c['text']==spec[0]:
                c['documentary_interpretation']={'code_expression':spec[1],'basis':spec[2],
                    'method':'original_pdf_visual_comparison','source_text_preserved':True,
                    'clinical_validation':'not_performed'}
                c['review_status']='source_format_defect_preserved'
                r['warnings']=[w for w in r['warnings'] if w!='invalid_cell_'+k]
                r['warnings'].append('source_format_defect_preserved_'+k)
            elif ambiguous and c['text']==ambiguous:
                c['review_status']='source_ambiguity_preserved'
                c['candidate_code_expressions']=code_references(ambiguous)
                c['candidate_is_authoritative']=False
                r['warnings']=[w for w in r['warnings'] if w!='invalid_cell_'+k]
                r['warnings'].append('source_ambiguity_preserved_'+k)
    return records

"""Edition-bound documentary decisions for the final 140 index directions.

The ledger is a source review, never a clinical mapping or an approximate search.
Absent headings remain unresolved. Alternative addresses require case context.
"""
import json
from functools import lru_cache
from pathlib import Path
from cie10.processing.volume3.index_structure import SOURCE_SHA256


@lru_cache(maxsize=1)
def decisions():
    data=json.loads(Path(__file__).with_name('volume3_remission_review.json').read_text(encoding='utf-8'))
    if data['source_sha256']!=SOURCE_SHA256:
        raise ValueError('Incompatible volume 3 documentary review')
    return {(identifier,spec['printed_target_text']):spec
            for spec in data['decisions'] for identifier in spec['source_ids']}


def reviewed_remission(edge, record, targets):
    spec=decisions().get((record['id'],edge['target_text']))
    if not spec or not record.get('sources') or any(s.get('source_sha256')!=SOURCE_SHA256 for s in record['sources']):
        return
    for identifier,label in spec['expected_destinations'].items():
        r=targets.get(identifier)
        if (not r or not r.get('sources') or any(s.get('source_sha256')!=SOURCE_SHA256 for s in r['sources'])
            or r.get('term_fragment',r.get('title',r.get('text','')))!=label
            or r.get('term_path',[])!=spec['expected_paths'][identifier]
            or r['kind']!=spec['expected_kinds'][identifier]
            or r.get('code_references',[])!=spec['expected_code_references'][identifier]):
            return  # A changed parser/source must trigger a new review.
    unresolved=spec['mode']=='unresolved'
    review={'status':'source_reference_reviewed_unresolved' if unresolved else 'visually_verified_documentary_route',
            'review_complete':True,'review_case':spec['n'],'source_sha256':SOURCE_SHA256,
            'finding':spec['finding'],'source_literal_preserved':True,'no_code_inherited':True,
            'no_destination_invented':True,'proof_ids':spec.get('proof_ids',[])}
    if spec.get('source_scope_conflict'):review['source_scope_conflict']=True
    edge['documentary_review']=review
    if unresolved:
        return
    ids=spec['target_ids']
    edge.update(target_id=ids[0] if len(ids)==1 else None,target_ids=ids[:],candidate_ids=[],
                documentary_matching_method='source_specific_documentary_review',requires_case_context=False)
    edge.pop('resolution_issue',None);edge.pop('partial_navigation',None)
    edge.pop('navigation_selector',None);edge.pop('table_selector',None)
    if spec['mode'] in ('navigation','prefix'):
        edge.update(resolution='resolved_contextual_navigation',target_kind='contextual_lookup',requires_case_context=True)
        selector={'instruction_literal':edge['printed_target_text'],
                  'case_selector':spec.get('selector',edge['target_text']),
                  'missing_patient_selector':True,'anchor_is_navigation_only':spec.get('anchor_only',len(ids)==1),
                  'option_refs':ids[:] if len(ids)>1 or spec.get('anchor_only') is False else [],'automatic_code_selection':False}
        if spec.get('prefix'):
            selector.update(matching_prefix=spec['prefix'],complete_term_required=True,
                            option_refs_are_examples=spec['mode']=='prefix',options_are_exhaustive=False)
        edge['navigation_selector']=selector
    elif spec['mode']=='table':
        from cie10.processing.volume3.volume3_special import NEOPLASM_COLUMNS
        columns=spec.get('columns') or list(targets[ids[0]].get('cells',{})) or list(NEOPLASM_COLUMNS)
        metadata=targets[ids[0]]['kind']=='special_table_metadata'
        # A table address locates rows and columns; it does not choose a code.
        edge.update(resolution='resolved_table_instruction',target_kind='table_lookup',requires_case_context=True,
                    table_selector={'candidate_columns':columns,'column_required_from_case_context':len(columns)>1,
                                    'anatomic_site_or_substance_required':metadata or bool(spec.get('selector')),
                                    'case_selector':spec.get('selector'),
                                    'row_option_refs':ids[:] if len(ids)>1 else [],
                                    'row_selection_required':len(ids)>1,
                                    'blank_cells_are_preserved':True,'automatic_code_selection':False})
    else:
        edge.update(resolution='resolved_exact',target_kind='index_term')

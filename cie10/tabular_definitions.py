"""Keep printed injury-type definitions outside inherited tabular rules."""
import json
from functools import lru_cache
from pathlib import Path

from .tabular_notes import logical_notes, unique_sources
from .tabular_reviewed import SOURCE_SHA


@lru_cache(maxsize=1)
def reviewed_definitions():
    return json.loads(Path(__file__).with_name('reviewed_definitions_v7.json').read_text(encoding='utf-8'))


def normalize_definitions(record):
    for block in record.get('definition_blocks', []):
        block['raw_note_fragments']={k:list(block[k]) for k in ('inclusions','exclusions','notes')}
        rule=reviewed_definitions().get(block['id'])
        original=block['inclusions']
        exact=([ [f['source']['pdf_page'], f['source']['line_id'], f['text']] for f in original])
        verified=(rule and block['sources'][0].get('source_sha256')==SOURCE_SHA
                  and exact==rule['expected'])
        if verified:
            sources=unique_sources([f['source'] for f in original])
            # Groups express the printed brace/prefix relationship once, not
            # every permutation, and do not declare clinical equivalence.
            block['definition_groups']=[dict(g,sources=sources) for g in rule['groups']]
            block['inclusions']=[dict(text=t,source=sources[0],sources=sources,
                basis='pdf_visual_review',composition='reviewed_definition_term')
                for t in rule.get('standalone_terms',[])]
            block['reviewed_corrections']={'version':'v7','basis':'pdf_visual_review',
                'source_sha256':SOURCE_SHA,'exact_fragment_sequence_checked':True}
        issues=[]
        for field,polarity in (('inclusions','inclusion'),('exclusions','exclusion')):
            block[field],found=logical_notes(block[field],polarity,
                {'definition_title':block['title']},'implicit_under_code_heading')
            issues.extend(found)
        block['structure_issues']=issues
        block['code_references']=[]
        for field in ('inclusions','exclusions'):
            for entry in block[field]:
                entry['scope']='injury_type_definition'
                entry['automatic_applicability']=False
                block['code_references'].extend(ref['raw'] for ref in entry['references'])
        block['code_references']=list(dict.fromkeys(block['code_references']))

"""Visually verified, exact-fragment repairs for the remaining v5 review set.

Rules are not transferable medical heuristics: both the PDF hash and the full
fragment sequence must match. Raw evidence is retained before this pass.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from cie10.processing.volume1.tabular_reviewed import SOURCE_SHA


@lru_cache(maxsize=1)
def rules():
    return json.loads(Path(__file__).with_name('reviewed_blocks_v6.json').read_text(encoding='utf-8'))


def apply_reviewed_blocks(record):
    if not record.get('sources') or record['sources'][0].get('source_sha256') != SOURCE_SHA:
        return
    key=record.get('code',record['id'])
    for rule in rules().get(key,[]):
        field=rule['field']
        fragments=record[field]
        if [(f['source']['pdf_page'],f['source']['line_id'],f['text']) for f in fragments] != [tuple(x) for x in rule['expected']]:
            continue
        sources=[f['source'] for f in fragments]
        if rule.get('preserve_editorial_prefix'):
            record['instructions']=record['instructions']+[dict(fragments[0],
                text_role='editorial_reference',block_id=record['id']+'-review-v6-editorial')]
        destination=rule.get('destination',field)
        entries=[]
        for item in rule['entries']:
            entry=dict(text=item['text'],source=sources[item.get('source_index',0)],sources=sources,
                       block_id=record['id']+'-review-v6',composition='visually_reviewed_layout')
            for name in ('examples','scope_statement'):
                if name in item:entry[name]=item[name]
            entries.append(entry)
        record[field]=[]
        if destination==field:
            record[field]=entries
        else:
            record[destination]=record[destination]+entries
        if rule.get('scope_statement'):
            record['notes']=record['notes']+[dict(text=rule['scope_statement'],source=sources[0],sources=sources,
                block_id=record['id']+'-review-v6-scope',text_role='extension_of_referenced_condition')]
        record.setdefault('reviewed_corrections',[]).append(dict(kind=rule['reason'],field=field,
            basis='pdf_visual_review',sources=sources,review_version='v6'))


def join_detached_bullets(page):
    """A large dot beside a following term is a bullet, not a section heading."""
    if page.get('volume')!=1:
        return page
    result=deepcopy(page)
    lines=result['lines']
    out=[]
    index=0
    while index<len(lines):
        line=lines[index]
        if line['text']=='.' and index+1<len(lines):
            following=lines[index+1]
            a,b=line['bbox'],following['bbox']
            if (not following['start_bold'] and 0<=b[0]-a[2]<=16 and abs(b[1]-a[1])<=10):
                joined=dict(following,text='• '+following['text'],merged_line_ids=[line['id'],following['id']])
                out.append(joined)
                index+=2
                continue
        out.append(line)
        index+=1
    result['lines']=out
    return result

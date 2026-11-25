"""Supplementary character tables explicitly printed inside a category."""
import re

def add_supplementary_tables(records):
    codes={r['code']:r for r in records if r.get('code')}
    for record in records:
        if not record.get('code'):
            continue
        starts=[i for i,t in enumerate(record['raw_lines']) if t.startswith('Las siguientes subdivisiones se ofrecen')]
        for start in starts:
            preamble,rows=[],[]
            for i in range(start,len(record['raw_lines'])):
                text=record['raw_lines'][i]
                match=re.match(r'^([0-9l])\s+(.+)',text)
                source=record['sources'][min(i,len(record['sources'])-1)]
                if match:
                    rows.append(dict(suffix=match[1] if match[1].isdigit() else None,raw_suffix=match[1],text=match[2],sources=[source]))
                elif rows:
                    break
                else:
                    preamble.append(text)
            header=' '.join(preamble)
            if 'suplementario' not in header:
                continue
            complete=bool(rows) and all(row['suffix'] is not None for row in rows)
            table=dict(preamble=header,rows=rows,optional='opcional' in header,
                       scope_code=record['code'],position='supplementary_character',
                       resolution='explicit_supplementary_table' if complete else 'requires_glyph_review',
                       generates_final_codes=False)
            record.setdefault('supplementary_tables',[]).append(table)
            record['code_structure']['supplementary_table_available']=True
            if not complete:
                record['semantic_review_issues'].append(dict(kind='supplementary_table',reason='ambiguous_suffix_glyph',sources=record['sources'][start:start+1]))
                record['warnings'].append('semantic_relation_requires_review')
        if record.get('supplementary_tables'):
            for code,child in codes.items():
                if code.startswith(record['code']+'.'):
                    child.setdefault('supplementary_table_refs',[]).append(record['id'])
    return records

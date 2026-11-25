"""Classify prose and editorial references without turning them into synonyms."""
import re
from .common import normalize
from .tabular_notes import is_implicit_term_list, logical_notes

def classify_prose(record):
    record['descriptive_text'] = []
    original = record['unclassified']
    if not original:
        return
    # Editorial cross-references can precede an ordinary term list in the same record.
    remaining, i = [], 0
    while i < len(original):
        f=original[i]
        if re.match(r'^\[(?:Ver|Véase|Para)\b',f['text'],re.I):
            chunk=[f]
            while ']' not in chunk[-1]['text'] and i+1<len(original):
                i+=1
                chunk.append(original[i])
            if ']' in chunk[-1]['text']:
                record['instructions'].append(dict(text=normalize(' '.join(x['text'] for x in chunk)),
                    source=f['source'],sources=[x['source'] for x in chunk],text_role='editorial_reference',
                    block_id=record['id']+'-editorial-'+str(i),raw_fragments=chunk))
            else: remaining.extend(chunk)
        elif re.match(r'^\d+El \d+ de ',f['text']):
            chunk=original[i:]
            record['descriptive_text'].append(dict(text=normalize(' '.join(x['text'] for x in chunk)),
                source=f['source'],sources=[x['source'] for x in chunk],text_role='footnote',raw_fragments=chunk))
            break
        else: remaining.append(f)
        i+=1
    record['unclassified']=remaining
    original=remaining
    if not original:
        return
    probe=[]
    for f in original:
        if (probe and f['source']['pdf_page']==probe[-1]['source']['pdf_page']
                and f['source']['bbox'][0]>probe[-1]['source']['bbox'][0]+2
                and -2<=f['source']['bbox'][1]-probe[-1]['source']['bbox'][3]<=14
                and probe[-1]['source']['bbox'][2]-probe[-1]['source']['bbox'][0]>200
                and not probe[-1]['text'].endswith(':')):
            probe[-1]['text'] += ' '+f['text'].rstrip('.')
        else:
            probe.append(dict(f,text=f['text'].rstrip('.')))
    if record['kind']=='code' and is_implicit_term_list(probe):
        entries,issues=logical_notes(original,'inclusion',{'code':record.get('code'),'description':record['description']},'implicit_under_code_heading')
        record['inclusions'].extend(entries)
        record['note_structure_issues'].extend(issues)
        record['unclassified']=[]
        return
    joined = normalize(' '.join(f['text'] for f in original))
    role = None
    destination = 'descriptive_text'
    if re.match(r'^(?:Las|Los|Todas las|Todos los) (?:afecciones|enfermedades|trastornos|estados|tipos)',joined,re.I) and re.search(r'\b[A-Z]\d{2}',joined):
        role, destination = 'referenced_condition_set', 'instructions'
    elif joined.startswith('[') and joined.endswith(']') and re.search(r'\b(?:ver|véase|para)\b',joined,re.I):
        role, destination = 'editorial_reference', 'instructions'
    elif record['kind'] == 'context':
        role = 'classification_context'
    elif record['kind'] == 'shared_subdivision_scheme':
        role = 'subdivision_explanation'
    elif record.get('code','').startswith('F') and len(joined)>100:
        role = 'glossary_description'
    elif re.search(r'\bcuyo peso al nacer\b',joined,re.I) and re.search(r'\d',joined):
        role = 'quantitative_definition'
    elif re.match(r'^La siguiente (?:clasificación|subclasificación)',joined,re.I):
        role, destination = 'supplementary_scheme_preamble', 'notes'
    elif re.search(r'\b(?:se caracteriza|caracterizado|caracterizada|se define|se refiere|síndrome|trastorno|afección|cualquier|incluye|incluyen|consiste|sin manifestaciones|con manifestaciones|cuyo|cuyos|cuya|cuyas|es una|son|signos clínicos|causadas|causados|tales como)\b',joined,re.I) and (len(original)>2 or len(joined)>100):
        role = 'diagnostic_description'
    elif len(joined)>70 and re.search(r'\b(?:que|cuyo|cuyos|con|no se|después|al nacer|probabilidad)\b',joined,re.I):
        role = 'diagnostic_description'
    if role:
        record[destination].append(dict(text=joined,source=original[0]['source'],
            sources=[f['source'] for f in original], text_role=role,
            classification_basis='wording_and_record_context', block_id=record['id']+'-prose',
            raw_fragments=original))
        record['unclassified']=[]


def strip_geometry(value):
    if isinstance(value,dict):
        value.pop('glyphs',None)
        for child in value.values(): strip_geometry(child)
    elif isinstance(value,list):
        for child in value: strip_geometry(child)

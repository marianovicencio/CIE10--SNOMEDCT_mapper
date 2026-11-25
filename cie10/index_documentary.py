"""Conservative repairs of visually verified typography in this exact edition."""
import re
from copy import deepcopy
from .common import normalize, CODE_REF, code_references

# These terms are printed together on a single baseline. Their separate bold
# labels were checked on the original PDF, including Meroceles on PDF 368.
JOINED = {
 'v3-p75-l111':['Antecedente', 'Anteflexión', 'Anteversión'],
 'v3-p368-l75':['Merocele', 'Merzbacher–Pelizaeus, enfermedad de'],
 'v3-p368-l77':['Mesaortitis','Mesarteritis','Mesencefalitis'],
 'v3-p376-l7':['Mortalidad','Mortificación','Mortinato NCOP'],
 'v3-p398-l10':['Oligemia','Oligergasia','Oligoastrocitoma, mixto'],
 'v3-p587-l31':['Uterovesical','Uveal'],
 'v3-p239-l88':['Eunuquismo','Evaluación'],
 'v3-p612-l56':['Avalancha, víctima de','Aviadores, enfermedad de los'],
}


def term_label(text):
    """A lookup directive is not part of the indexed disease name."""
    text=re.split(r'\s*[–—-]\s*\b(?:ver|véase|codifique)\b|\(\s*(?:ver|véase)\b',text, maxsplit=1,flags=re.I)[0]
    return normalize(CODE_REF.sub('',text)).strip(' ,;')


def repair_joined_entries(records):
    result=[]; replacements={}; reference_replacements={}
    for index,r in enumerate(records):
        if r.pop('_joined_consumed',False): continue
        if (r['id']=='v3-p239-l89' and r['text']=='– ver Examen Eventración K43.9'
            and result and result[-1]['id']=='v3-p239-l88-split2' and result[-1]['text']=='Evaluación'):
            previous=result[-1]
            previous['text']+=' – ver Examen'
            previous['sources']+=r['sources']
            previous['has_cross_reference']=True
            previous['warnings'].append('cross_reference_not_resolved')
            old_label=r['term_fragment']
            row=deepcopy(r)
            row.update(id=r['id']+'-split2',text='Eventración K43.9',term_fragment='Eventración',
                ancestors=[],depth=0,term_path=['Eventración'],ancestor_entry_refs=[],
                has_cross_reference=False,code_references=['K43.9'],
                documentary_segmentation={'source_id':r['id'],
                  'source_text':r['text'],'method':'separate_bold_main_terms_visually_verified'})
            row['warnings']=[w for w in row['warnings'] if w!='cross_reference_not_resolved']
            replacements[old_label]='Eventración'
            reference_replacements[r['id']]=row['id']
            result.append(row)
            continue
        if (r['id']=='v3-p368-l75' and r['text']=='Merocele – ver Hernia, femoral Merzbacher–'
            and index+1<len(records) and records[index+1]['text']=='Pelizaeus, enfermedad de E75.2'):
            following=records[index+1]
            r['text']+=''+following['text'];r['sources']+=following['sources']
            following['_joined_consumed']=True
            reference_replacements[following['id']]=r['id']+'-split2'
            JOINED[r['id']]=['Merocele','Merzbacher–Pelizaeus, enfermedad de']
        terms=JOINED.get(r['id'])
        # A changed source/parser must not trigger an approximate textual repair.
        positions=[r['text'].find(t) for t in terms] if terms else []
        if terms and positions[0]==0 and all(a<b for a,b in zip(positions,positions[1:])):
            replacements[r['term_fragment']]=terms[-1]
            reference_replacements[r['id']]=r['id']+f'-split{len(terms)}'
            for i,(term,pos) in enumerate(zip(terms,positions)):
                row=deepcopy(r);row['id']=r['id']+f'-split{i+1}'
                row['text']=r['text'][pos:positions[i+1] if i+1<len(terms) else None].strip()
                row['term_fragment']=term_label(row['text']);row['ancestors']=[];row['depth']=0
                row['term_path']=[row['term_fragment']];row['code_references']=code_references(row['text'])
                row['has_cross_reference']=bool(re.search(r'\b(?:ver|véase)\b',row['text'],re.I))
                row['warnings']=[w for w in row['warnings'] if w!='cross_reference_not_resolved']
                row['documentary_segmentation']={'source_id':r['id'],'source_text':r['text'],
                  'method':'separate_bold_main_terms_visually_verified','sources_cover_original_joined_lines':True}
                result.append(row)
        else:
            if replacements:
                r['ancestors']=[replacements.get(p,p) for p in r['ancestors']]
                r['term_path']=[replacements.get(p,p) for p in r['term_path']]
            result.append(r)
    for r in result:
        if 'ancestor_entry_refs' in r:
            r['ancestor_entry_refs']=[reference_replacements.get(i,i) for i in r['ancestor_entry_refs']]
        for field in ('continuation_of','scope_anchor_id'):
            if r.get(field) in reference_replacements:r[field]=reference_replacements[r[field]]
    return result

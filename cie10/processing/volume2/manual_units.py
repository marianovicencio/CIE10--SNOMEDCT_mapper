"""Complete documentary sections, subheadings and explicit manual references.

No size/page-based cuts, no clinical applicability inferred from a code mention.
The source paragraphs and their physical line provenance are preserved verbatim.
"""
import re
import unicodedata
from cie10.common import code_references, provenance
from cie10.processing.volume2.manual_semantics import manual_scope

VERSION = '1'
STRUCTURED = ('4.2.5','4.3.7','4.5.4','7.3','7.4','7.6','7.7','7.8')
NUMBER = re.compile(r'^([1-7](?:\.\d+){0,4})\.?\s+(.+)')
REF = re.compile(r'\b(?:(?:[Ss]ecci[oó]n(?:es)?|[Aa]nexo(?:s)?)\s+([1-7](?:\.\d+)+)|[Pp]aso\s+(SP\d+|M\d+))')


def document_units(pages):
    records=[];current=None;section=None;upper=None;root=None;parent=None;last_page=None
    def finish(boundary):
        nonlocal current
        if current:
            current['text']='\n'.join(current.pop('_lines'))
            current['code_references']=code_references(current['text'])
            current['contains_worked_examples']=bool(re.search(r'\bEjemplo\s+\d+',current['text']))
            current['source_line_count']=len(current['sources'])
            current['boundary_end']=boundary
            current.pop('_header_font',None);current.pop('_header_size',None);current.pop('_header_open',None)
            if boundary=='source_page_gap':current['warnings'].append('incomplete_unit_source_page_gap')
            records.append(current);current=None
    def start(page,line,kind,address,ancestors):
        nonlocal current
        finish('next_document_heading')
        current={'id':f"v2-p{page['pdf_page']}-l{line['id']}-unit",'kind':'manual_document_unit',
                 'section':{'number':section,'title':line['text']},'section_address':address,
                 'title':line['text'],'heading_type':kind,'ancestor_unit_refs':list(dict.fromkeys(a for a in ancestors if a)),
                 'scope':manual_scope({'number':section or ''}),'review_status':'pending','warnings':[],
                 'requires_case_context':bool(section and section.startswith('4')),'executable_rule':False,
                 'sources':[],'_lines':[],'_header_font':line.get('start_font'),'_header_size':line.get('start_size'),
                 '_header_open':kind!='unassigned'}
    for page in pages:
        if last_page is not None and page['pdf_page']!=last_page+1:
            finish('source_page_gap');section=upper=root=parent=None
        last_page=page['pdf_page']
        for line in page['lines']:
            text=line['text'];font=line.get('start_font','');size=line.get('start_size',0);x=line['bbox'][0]
            numbered=NUMBER.match(text)
            numbered=numbered if numbered and size>=10.8 and any(f in font for f in ('Arial','Helvetica')) else None
            upper_heading=re.match(r'^([A-Z])\.\s+(.+)',text) if size>=10.8 and x<40 and any(f in font for f in ('Arial','Helvetica')) else None
            lower_heading=re.match(r'^([a-z])\)\s+\S',text) if x<40 else None
            step=re.match(r'^Paso\s+(SP\d+|M\d+)\b',text) if size>=10.8 and x<40 else None
            wrapped=current and current['_header_open'] and font==current['_header_font'] and size==current['_header_size'] and not (numbered or upper_heading or lower_heading or step)
            named=size>=10.8 and x<40 and any(f in font for f in ('Arial','Helvetica')) and ('Italic' in font or 'Oblique' in font) and not wrapped
            if numbered:
                number,title=numbered.groups();letter=re.match(r'^([A-Z])\.\s+',title)
                if number!=section:upper=root=parent=None
                section=number
                if letter:
                    upper=letter[1];start(page,line,'letter_section',number+' '+upper,[root]);parent=current['id']
                else:
                    upper=None;start(page,line,'numbered_section',number,[]);root=parent=current['id']
            elif upper_heading and section:
                upper=upper_heading[1];start(page,line,'letter_section',section+' '+upper,[root]);parent=current['id']
            elif lower_heading and section:
                address=' '.join(v for v in [section,upper,lower_heading[1]] if v)
                start(page,line,'letter_item',address,[root,parent])
            elif step and section:
                start(page,line,'named_step',step[1],[root]);parent=current['id']
            elif named and section:
                # Unnumbered headings are retained as addressable subtopics.
                start(page,line,'named_heading',section+' | '+text,[root,parent])
            elif current is None:
                start(page,line,'unassigned',section or 'unassigned',[root,parent])
            elif wrapped:
                current['title']+=' '+text;current['section']['title']=current['title']
            else:current['_header_open']=False
            current['_lines'].append(text);current['sources'].append(provenance(page,line))
    finish('end_of_extracted_document')
    byid={r['id']:r for r in records}
    for r in records:
        r['context_code_expressions']=list(dict.fromkeys(expr for ref in r['ancestor_unit_refs'] for expr in byid[ref]['code_references']))
    return records


def normalized(text):
    return re.sub(r'\W+',' ',''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))).strip()


def manual_references(record,units):
    text=re.sub(r'\s+',' ',record.get('text') or record.get('raw_line') or '')
    refs=[];seen=set()
    matches=[]
    for match in REF.finditer(text):
        number,step=match.groups();matches.append((match.start(),match.end(),number,step))
        if number:
            # "secciones 5.4 y 5.5" / "4.3.5 A y 4.3.5 B" share a prefix.
            tail=text[match.end():match.end()+90]
            continuation=re.match(r'(?:\s+[A-G](?:\s+[a-z])?)?(?:\s*[,;]?\s*(?:y|o|a)\s+([1-7](?:\.\d+)+)(?:\s+[A-G])?)',tail)
            if continuation:
                offset=match.end()+continuation.start(1)
                matches.append((offset,offset+len(continuation[1]),continuation[1],None))
    for start,end,number,step in sorted(matches):
        tail=text[end:end+200];address=number or step
        if number:
            letter=re.match(r'[.,]?\s*([A-G])(?=\s|[.(,])',tail)
            if letter:
                address+=' '+letter[1]
                lower=re.search(r'\binciso\s+([a-z])\)',tail[:140])
                if lower:address+=' '+lower[1]
        if address in seen:continue
        seen.add(address)
        exact=[u for u in units if u['section_address']==address]
        descendants=[u for u in units if u['section_address'].startswith(address+' ') or u['section_address'].startswith(address+' | ') or (re.fullmatch(r'[1-7](?:\.\d+)*',address) and u['section_address'].startswith(address+'.'))]
        targets=exact+descendants
        expected=None
        if number:
            # An explicit title inside a "ver en la sección ..., TITLE)" citation
            # must agree with the printed numeric target; never hide a conflict.
            prefix=text[max(0,start-20):start]
            title=re.match(r',\s*([^)]{15,160})\)',tail) if re.search(r'\bver(?:\s+en)?\s+la\s*$',prefix,re.I) else None
            if title:expected=title[1]
        conflict=expected and not any(normalized(expected) in normalized(u['title']) or normalized(u['title']) in normalized(expected) for u in exact)
        candidates=[]
        if conflict:
            candidates=[u for u in units if normalized(expected) in normalized(u['title']) or normalized(u['title']) in normalized(expected)]
            targets=[]
        # A qualified item must not fall back to a less precise parent section.
        resolution='printed_number_title_conflict' if conflict else 'resolved_exact_address' if targets else 'unresolved_address'
        ref={'printed_reference':address,'resolution':resolution,'target_unit_refs':[u['id'] for u in targets],
             'source_role':'documentary_reference','implies_clinical_equivalence':False}
        if expected:ref['printed_title']=expected
        if candidates:
            ref['candidate_unit_refs']=[u['id'] for u in candidates]
            ref['candidate_targets']=[{'section_address':u['section_address'],'title':u['title'],'detail_url':'/v1/records/'+u['id'],'reading_url':'/v1/manual/units/'+u['id']} for u in candidates]
        if targets:
            if len(targets)==1:
                ref['detail_url']='/v1/records/'+targets[0]['id']
                ref['reading_url']='/v1/manual/units/'+targets[0]['id']
            elif number:ref['section_url']='/v1/manual/sections/'+address.replace(' ','%20')
            else:ref['section_url']='/v1/manual/sections/'+address
        refs.append(ref)
    return refs

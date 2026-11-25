"""Documentary blocks in 4.3.7 and 4.5.4; instructions remain conditional text."""
import re
from cie10.common import code_references, provenance, ROOT

VERSION = '1'
SECTION = re.compile(r'^([1-7](?:\.\d+){0,4})\.?\s+(.+)')
CHAPTERS = {'I':'A00-B99','II':'C00-D48','III':'D50-D89','IV':'E00-E90',
            'V':'F00-F99','VI':'G00-G99','VII':'H00-H59','VIII':'H60-H95',
            'IX':'I00-I99','XV':'O00-O99','XVIII':'R00-R99','XIX':'S00-T98','XX':'V01-Y98'}


def specific_notes(pages):
    records=[]; section=None; chapter=None; current=None; owner=None
    def finish():
        nonlocal current
        if current:
            current['text']='\n'.join(current.pop('_lines'))
            current['code_references']=code_references(current['text'])
            current['section_references']=list(dict.fromkeys(re.findall(r'\b[347]\.\d+(?:\.\d+)*\b',current['text'])))
            records.append(current); current=None
    def start(page,line,kind,subjects=(),title=None):
        nonlocal current,owner
        finish()
        current={'id':f"v2-p{page['pdf_page']}-l{line['id']}-specific",'kind':kind,
                 'section':section,'scope':'mortality' if section=='4.3.7' else 'morbidity',
                 'chapter':chapter,'title':title or line['text'],'subject_code_expressions':list(subjects),
                 'context_ref':owner if kind=='manual_worked_example' else None,
                 'requires_case_context':True,'executable_rule':False,'review_status':'pending',
                 'coding_context':'multiple_causes_of_death' if section=='4.3.7' else 'main_condition_in_episode_of_care',
                 'warnings':[],'sources':[],'_lines':[]}
        if kind!='manual_worked_example': owner=current['id']
    for page in pages:
        for line in page['lines']:
            text=line['text']; heading=SECTION.match(text)
            if heading and line['start_size']>=10.8 and any(f in line['start_font'] for f in ('Arial','Helvetica')):
                finish();section=heading.group(1);chapter=None;owner=None
                if section in ('4.3.7','4.5.4'): start(page,line,'manual_section_context')
            if section not in ('4.3.7','4.5.4'): continue
            ch=re.match(r'^Capítulo\s+([IVX]+):',text)
            letter=re.match(r'^([A-G])\.\s+',text) if section=='4.3.7' else None
            example=re.match(r'^Ejemplo\s+(\d+):',text)
            code_header=(section=='4.5.4' and line['bbox'][0]<30 and
                         re.match(r'^(?:[A-Z]\d{2}(?:\.[\d–—-]+)?|1(?:15|69)\.[–-])(?:[–-][A-Z]\d{2})?\s',text)
                         and (line['start_bold'] or line['start_size']>=10.8))
            if ch:
                chapter=ch.group(1);start(page,line,'manual_chapter_guidance',[CHAPTERS[chapter]])
            elif letter:
                start(page,line,'manual_specific_instruction',code_references(text))
            elif example:
                start(page,line,'manual_worked_example');current['example_number']=int(example.group(1))
            elif page['pdf_page']==189 and line['id']==6:
                # The example across pages 188–189 ends before this general HIV guidance.
                start(page,line,'manual_specific_instruction',['B20-B24'], 'Uso de subcategorías y códigos adicionales para VIH')
            elif code_header:
                expressions=code_references(text)
                printed_typo=text.startswith(('115.', '169.'))
                if printed_typo: expressions=['I15.–' if text.startswith('115.') else 'I69.–']
                if current and current['kind']=='manual_specific_instruction' and all(l for l in current['_lines']) and current.get('_headers_only'):
                    current['subject_code_expressions']+=expressions
                    current['title']+=' / '+text
                else:
                    start(page,line,'manual_specific_instruction',expressions)
                current['_headers_only']=True
                if printed_typo:
                    current['warnings'].append('printed_heading_typo_preserved')
                    current['heading_code_interpretation']={'printed':text.split()[0], 'linked_expression':expressions[0],
                       'basis':'body_explicitly_names_I15_or_I69_and_visual_source_comparison'}
            elif current:
                # Wrapped chapter and instruction headings carry their scope on later lines.
                if (letter is None and section=='4.3.7' and line['start_size']>=10.8
                        and current['kind']=='manual_specific_instruction'):
                    current['subject_code_expressions']+=code_references(text)
                if current.get('_headers_only') and not (line['start_bold'] or line['start_size']>=10.8):
                    current['_headers_only']=False
            if current:
                current['_lines'].append(text);current['sources'].append(provenance(page,line))
    finish()
    for r in records:
        r.pop('_headers_only',None)
        r['subject_code_expressions']=list(dict.fromkeys(r['subject_code_expressions']))
    return records


def write_specific_review(records,mode):
    lines=['# Revisión documental de 4.3.7 y 4.5.4','',
           '4.3.7: mortalidad, PDF 161–164. 4.5.4: morbilidad, PDF 187–199.',
           'Se conservaron condiciones, excepciones, ejemplos y continuaciones entre páginas. '
           'La revisión de la fuente no convierte estas instrucciones en decisiones clínicas ejecutables.','']
    for r in records:
        pages=sorted({s['pdf_page'] for s in r['sources']})
        lines += ['## '+r['title'],'', f"{r['id']} · {r['scope']} · {r['kind']} · PDF {', '.join(map(str,pages))}",'',
                  'Vinculación por encabezado: '+(', '.join(r['subject_code_expressions']) or 'Contexto / ejemplo; las menciones no implican aplicación universal.'),'',r['text'],'']
    path=ROOT/'data/reports'/mode/'vol2_notas_especificas_revision.md'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(lines),encoding='utf-8')

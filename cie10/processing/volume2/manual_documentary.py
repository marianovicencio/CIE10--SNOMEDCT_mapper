"""Persist a source review without approving executable clinical decisions.

The reviewed snapshot is an exact-content ledger. A parser/source change
invalidates the review; being on a reviewed page is not sufficient.
"""
import hashlib
import json
from cie10.common import ROOT, read_json, provenance

LEDGER = ROOT/'config/vol2_documentary_review.json'
RESOLVED_WARNINGS = {
    'bold_outcome_requires_visual_review', 'bold_outcome_not_detected',
    'outcome_condition_pairing_requires_review', 'subject_group_requires_visual_review',
    'fourth_character_result_requires_review', 'alternative_condition_group_requires_review',
    'explicit_destination_not_bold_in_source',
}


def review_digest(record):
    def stripped(value):
        if isinstance(value, dict):
            return {k: stripped(v) for k,v in value.items()
                    if k not in ('review_status','documentary_review','warnings')}
        if isinstance(value, list):
            return [stripped(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(stripped(record),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def attach_documentary_review(records, dataset, ledger=None):
    if ledger is None:
        ledger = read_json(LEDGER) if LEDGER.exists() else {'entries':{}}
    for record in records:
        entry = ledger['entries'].get(dataset+'|'+record['id'])
        if not entry:
            continue
        source = record.get('source') or record.get('sources',[{}])[0]
        if entry['digest'] != review_digest(record) or source.get('source_sha256') != ledger['source_sha256']:
            record['review_status'] = 'pending'
            record.pop('documentary_review', None)
            for row in record.get('condition_rows', []):
                row['review_status'] = 'pending'
            record['warnings'].append('documentary_review_outdated')
            continue
        ambiguous = entry['status']=='source_ambiguity_preserved'
        record['review_status'] = 'source_ambiguity_preserved' if ambiguous else 'source_verified'
        record['documentary_review'] = {
            'status':entry['status'], 'reviewed_at':entry.get('reviewed_at',ledger['reviewed_at']),
            'method':'page_by_page_pdf_visual_and_structural_comparison',
            'clinical_validation':'not_performed', 'digest':entry['digest'],
        }
        record['warnings'] = [w for w in record['warnings'] if w not in RESOLVED_WARNINGS]
        for row in record.get('condition_rows',[]):
            row['review_status']='source_verified'
            row['warnings']=[('conditional_qualifier_requires_case_context' if w=='conditional_qualifier_requires_review' else w)
                             for w in row['warnings'] if w not in RESOLVED_WARNINGS]
    return records


def manual_reference_contexts(pages):
    by_page={p['pdf_page']:p for p in pages}
    # Bounds are the visually verified source headers, not inferred from code
    # mentions. They remain separately retrievable by every dependent rule.
    specs=[
        ('4.2.5',83,1,15,{'step':'M1','subject_role':'provisional_underlying_cause','outcome_role':'new_provisional_underlying_cause'}),
        ('4.2.5-summary',119,1,7,{'default_if_no_indicated_code':'R99','asterisk_codes_not_for_underlying_cause':True}),
        ('7.3',244,17,19,{'step':'SP7','usage':'ill_defined_conditions'}),
        ('7.6',258,24,25,{'usage':'accepted_diabetes_due_to_causal_sequences'}),
        ('7.7',260,15,16,{'priority_order':'1_is_highest','usage':'mortality_main_injury_selection'}),
        ('7.8',266,1,4,{'usage':'sex_quality_control','hard_exclusion':False,'limited_or_more_likely_not_disambiguated_by_source':True}),
    ]
    result=[]
    for section,number,start,end,semantics in specs:
        if number not in by_page:
            continue
        page=by_page[number]
        lines=[l for l in page['lines'] if start<=l['id']<=end]
        result.append({
            'id':f'v2-p{number}-{section}-context','kind':'manual_reference_context',
            'section':section,'scope':'mortality','text':'\n'.join(l['text'] for l in lines),
            'sources':[provenance(page,l) for l in lines], 'semantics':semantics,
            'review_status':'pending','warnings':[],'executable_rule':False,
        })
    return result


def write_readable_review(blocks, annex, diabetes, restrictions, contexts, mode):
    folder=ROOT/'data/reports'/mode
    folder.mkdir(parents=True,exist_ok=True)
    def clean(text):
        import re
        text=re.sub(r'(?<=[a-záéíóúñ])-\n(?=[a-záéíóúñ])','',text)
        return text.replace('\n',' ').replace('|','\\|')
    md=[
        '# Revisión documental completa de 4.2.5', '',
        'Fuente: CIE-10 OPS/OMS 2018, volumen 2, páginas PDF 83–121 (impresas 72–110).', '',
        'Ámbito: codificación de mortalidad, selección de la causa básica provisional en el paso M1. '
        '«Con mención de» permite la otra afección en cualquier parte del certificado; '
        '«Cuando se informa como la causa de» exige que la causa provisional figure como causa de la otra afección '
        'en una relación causal correcta o que esta se indique como debida a aquella.', '',
        'La comprobación documental verifica transcripción, agrupación y asociación impresa. '
        'Las decisiones requieren el certificado, los calificadores y las demás reglas aplicables. '
        'No se han aprobado decisiones clínicas automáticas.', '',
        f'{len(blocks)} bloques; {sum(len(b["condition_rows"]) for b in blocks)} filas de contenido. '
        f'{len(restrictions)} entradas del resumen final. La procedencia completa está en los JSONL; aquí se resume por bloque.', '',
    ]
    labels={'with_mention_of':'Con mención de','reported_as_cause_of':'Informada como causa de',
            'antecedent_cause_of':'Causa antecedente originaria','direct_instruction':'Instrucción directa'}
    for b in blocks:
        pages=sorted({s['pdf_page'] for s in b['sources']})
        md.extend([f"## {', '.join(b['subject_code_expressions'])}", '',
                   f"PDF {', '.join(map(str,pages))} · {b['id']} · {b['review_status']}", ''])
        if any(r['row_type'] in ('condition','exception','combination') for r in b['condition_rows']):
            for subject in b.get('subject_entries',[]):
                md.extend([clean(subject['text']), ''])
        for r in b['condition_rows']:
            conditions=', '.join(r['condition_code_expressions']) or 'Condición descrita en el texto'
            if r.get('condition_fourth_character'): conditions='Cuarto carácter '+r['condition_fourth_character']
            outcomes=', '.join(dict.fromkeys(o['code_expression'] for o in r['outcome_mentions']))
            if r.get('fourth_character_literal'): outcomes+=' con cuarto carácter '+r['fourth_character_literal']
            if r.get('fourth_character_selection'): outcomes+=' con el cuarto carácter de la etapa más avanzada'
            if r['row_type'] in ('condition','exception','combination'):
                suffix='; sujeto con cuarto carácter '+r['subject_fourth_character'] if r.get('subject_fourth_character') else ''
                md.extend([f"**{labels.get(r['trigger_type'],r['trigger_type'])}{suffix}: {conditions} → {outcomes}.**", ''])
            md.extend([clean(r['text']), ''])
    md.extend(['## Resumen de restricciones', '',
               'El resumen conserva las alternativas impresas y sus condiciones. Una lista de destinos no es una sustitución incondicional.', '',
               '| Código o rango | Condición | Destinos impresos | Respaldo | PDF |',
               '|---|---|---|---|---|'])
    for r in restrictions:
        md.append(f"| {r['code_expression']} | {r['condition']} | {', '.join(r['recode_candidates'])} | {r.get('fallback_if_no_indicated_code','')} | {r['source']['pdf_page']} |")
    (folder/'vol2_4_2_5_revision_legible.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    md=['# Anexos 7.3, 7.4, 7.6, 7.7 y 7.8: revisión documental', '',
        '7.3 conserva el calificador de insuficiencia cardíaca aguda. '
        '7.4 conserva descripciones y excepciones. 7.6 expresa secuencias aceptadas de mortalidad. '
        '7.7 usa 1 como prioridad más alta. 7.8 no permite distinguir individualmente '
        'entre restricción por sexo y mayor frecuencia: hard_exclusion permanece false.', '',
        'La impresión Y46.2Y52.5 en E13 (PDF 259) queda dividida en dos candidatos y marcada como ambigüedad de la fuente.', '']
    for section in ('7.3','7.4','7.7','7.8.1','7.8.2'):
        md.extend([f'## {section}', '', '| Código o rango | Descripción / prioridad / sexo | PDF |', '|---|---|---|'])
        for r in annex:
            if r['section']==section:
                detail=clean(r.get('description') or (f"Prioridad {r['priority']}" if 'priority' in r else r['sex']))
                md.append(f"| {r['code_expression']} | {detail} | {r['source']['pdf_page']} |")
        md.append('')
    md.extend(['## 7.6', '', '| Diabetes | Debido a | Calificador | PDF / columna |', '|---|---|---|---|'])
    for r in diabetes:
        md.append(f"| {r['diabetes_code']} | {r['cause_code_expression']} | {r.get('qualifier') or ''} | {r['source']['pdf_page']} / {r['source']['column']} |")
    (folder/'vol2_anexos_revision_legible.md').write_text('\n'.join(md)+'\n',encoding='utf-8')

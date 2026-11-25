import copy
import json
import unittest
from types import SimpleNamespace
from cie10.index_reasoning import build_index_context, index_constraint
from cie10.mapping_context import ContextError
from cie10.candidate_explanation import explain_candidate
from cie10.explanation_budget import fit_model_evidence

HASH='a'*64
ID='123456789'


def record(identifier, kind='index_entry', **fields):
    return dict(id=identifier,kind=kind,sources=[dict(source_ref='row')],text='Entrada impresa',term_path=['Tumor','renal'],code_references=['C64'],**fields)


def audit(records, links):
    return dict(source_snapshot_sha256=HASH,records={x['id']:x for x in records},
        documents={'d3':dict(volume=3)},source_locations={
            'row':dict(document_ref='d3',pdf_page=567,printed_page='563',bbox=[0,50,100,60]),
            'header':dict(document_ref='d3',pdf_page=544,printed_page='540',bbox=[0,10,100,20])},
        context_links=links,retrieval=dict(all_selected_pages_retrieved=True,page_count=2))


def link(identifier,role='index_explicit_reference'):
    return dict(record_id=identifier,matched_expression='C64',role=role)


def base(text=None):
    items=[dict(id='cie-title',type='CIE10',role='title',text='Tumor maligno del riñón'),
           dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id=ID,text='Neoplasia renal')]
    if text:items.append(dict(id='input-diagnostic',type='INPUT',text=text))
    return items



def attributed(value):
    """Build the model fixture with citations attached to its statement."""
    refs=list(value.get('cie_evidence_refs',[]))+list(value.get('snomed_evidence_refs',[]))
    if value.get('diagnostic_evidence_ref'):refs.append(value['diagnostic_evidence_ref'])
    return {key:value[key] for key in ('concept_id','assessment','additional_detail_needed')} | {
        'claims':[{'text':value['justification'] if 'CIE-10' in value['justification'] and 'SNOMED' in value['justification'] else 'Comparación CIE-10 y SNOMED: '+value['justification'],'evidence_refs':refs}]}

class IndexProjectionTests(unittest.TestCase):
    def build(self,data,evidence=None):
        client=SimpleNamespace(fetch_evidence=lambda code,scope:data)
        return build_index_context(dict(code='C64',source_snapshot_sha256=HASH),evidence or base(),client=client)

    def test_path_and_original_codes_remain_navigation_not_patient_facts(self):
        row=record('v3-path');row['term_path']=['Embarazo','complicado por','afecciones en'];row['code_references']=['C00-D48','O99.8']
        items,coverage=self.build(audit([row],[link(row['id'])]))
        payload=json.loads(items[0]['text'])
        self.assertEqual(payload['route'],row['term_path'])
        self.assertFalse(payload['patient_facts'])
        self.assertFalse(payload['implies_clinical_equivalence'])
        self.assertEqual(coverage['linked_context_page_count'],2)

    def test_table_row_keeps_all_columns_matched_role_and_complete_header(self):
        row=record('v3-table',kind='neoplasm_table_row',cells={
            'malignant_primary':dict(text='C64',valid_shape=True),
            'malignant_secondary':dict(text='C79.0',valid_shape=True),
            'benign':dict(text='D30.0',valid_shape=True)})
        header=record('v3-meta',kind='special_table_metadata',table='neoplasm',columns=list(row['cells']),header_fragments=[dict(text='El comportamiento determina la columna. Conserve esta condición.',source=dict(source_ref='header'))])
        items,_=self.build(audit([row,header],[link(row['id'],'table_column:malignant_primary')]))
        payload=json.loads(items[0]['text'])
        self.assertEqual(set(payload['columns']),set(row['cells']))
        self.assertEqual(payload['matched_columns'],['malignant_primary'])
        self.assertIn('Conserve esta condición.',payload['table_context']['text'])
        self.assertIn('v3-meta',items[0]['record_ids'])
        self.assertIn('Maligno secundario: C79.0',items[0]['reading_text'])

    def test_missing_table_header_fails_closed(self):
        row=record('v3-table',kind='drug_table_row',cells={'poisoning_chapter_xix':dict(text='T50.9')})
        with self.assertRaises(ContextError):self.build(audit([row],[link(row['id'],'table_column:poisoning_chapter_xix')]))

    def test_victim_and_counterparty_direction_is_not_reversed(self):
        row=record('v3-transport',kind='transport_matrix_row',victim_mode='Peatón',columns={'car_pickup_or_van':'V03.-'})
        header=record('v3-meta',kind='special_table_metadata',table='transport_matrix',columns=['car_pickup_or_van'])
        items,_=self.build(audit([row,header],[link(row['id'],'transport_collision:car_pickup_or_van')]))
        text=items[0]['reading_text']
        self.assertEqual(items[0]['matched_columns'],['car_pickup_or_van'])
        self.assertIn('Víctima (fila): Peatón',text)
        self.assertIn('Automóvil, camioneta o furgoneta: V03.-',text)

    def test_partial_remission_preserves_candidates_and_unretrieved_status(self):
        row=record('v3-reference',kind='index_remission',directive='see_also',target_text='Otro término',resolution='partial_navigation',candidate_ids=['v3-missing'],implies_clinical_equivalence=False)
        items,_=self.build(audit([row],[link(row['id'])]))
        edge=items[0]['navigation'][0]
        self.assertEqual(edge['resolution'],'partial_navigation')
        self.assertEqual(edge['candidate_ids'],['v3-missing'])
        self.assertFalse(edge['target_contexts'][0]['content_retrieved'])
        self.assertTrue(items[0]['requires_documentary_review'])

    def test_note_scope_is_attached_to_the_entry_and_not_a_global_rule(self):
        row=record('v3-entry',index_note_refs=['v3-note'])
        note=record('v3-note',kind='index_note',scope_path=['Tumor'],scope_type='index_entry_subtree')
        items,_=self.build(audit([row,note],[link(row['id'])]))
        self.assertEqual(json.loads(items[0]['text'])['scope_notes'][0]['scope_path'],['Tumor'])
        self.assertIn('v3-note',items[0]['record_ids'])

    def test_snapshot_or_missing_page_prevents_using_the_index(self):
        for data in [dict(audit([],[]),source_snapshot_sha256='b'*64),dict(audit([],[]),retrieval=dict(all_selected_pages_retrieved=False))]:
            with self.assertRaises(ContextError):self.build(data)

    def test_oversized_entry_is_omitted_whole_without_clipping_its_exception(self):
        row=record('v3-long');row['text']='Texto oficial. '*1000+'Excepción final.'
        items,coverage=self.build(audit([row],[link(row['id'])]))
        self.assertEqual(items,[])
        self.assertEqual(coverage['omitted_items'][0]['record_ids'],['v3-long'])

    def test_remission_origin_path_is_distinct_from_its_target(self):
        source=record('v3-origin');source['term_path']=['Aborto','anormal']
        target=record('v3-target');target['term_path']=['Malformación']
        row=record('v3-ref',kind='index_remission',source_id='v3-origin',directive='see',target_text='Malformación',target_id='v3-target',resolution='resolved_exact');row['term_path']=[]
        items,_=self.build(audit([source,target,row],[link(row['id'])]))
        self.assertEqual(items[0]['route'],['Aborto','anormal'])
        self.assertEqual(items[0]['navigation'][0]['target_contexts'][0]['route'],['Malformación'])
        self.assertNotIn('v3-origin',[x['record_id'] for x in items[0]['navigation'][0]['target_contexts']])

    def test_missing_remission_origin_is_fetched_with_snapshot_validation(self):
        source=record('v3-origin');source['term_path']=['Aborto','actual']
        row=record('v3-ref',kind='index_remission',source_id='v3-origin',directive='see',target_text='Categoría',resolution='code_expression_preserved');row['term_path']=[]
        data=audit([row],[link(row['id'])])
        def transport(path):
            self.assertEqual(path,'/v1/records/v3-origin')
            return dict(record=source,source_snapshot_sha256=HASH,documents=data['documents'],source_locations=data['source_locations'])
        client=SimpleNamespace(fetch_evidence=lambda *_:data,transport=transport)
        items,_=build_index_context(dict(code='C64',source_snapshot_sha256=HASH),base(),client=client)
        self.assertEqual(items[0]['route'],['Aborto','actual'])
        self.assertIn('v3-origin',items[0]['record_ids'])

    def test_changed_remission_origin_snapshot_is_rejected(self):
        row=record('v3-ref',kind='index_remission',source_id='v3-origin',directive='see',resolution='code_expression_preserved')
        data=audit([row],[link(row['id'])])
        client=SimpleNamespace(fetch_evidence=lambda *_:data,transport=lambda _:dict(record=record('v3-origin'),source_snapshot_sha256='b'*64))
        with self.assertRaises(ContextError):
            build_index_context(dict(code='C64',source_snapshot_sha256=HASH),base(),client=client)


class IndexReasoningTests(unittest.TestCase):
    def pregnancy(self,text):
        items=base(text);items.append(dict(id='index-route',type='CIE10',volume=3,role='index_entry',route=['Embarazo','complicado por','afecciones en'],text='Ruta C00-D48 hacia O99.8',code_references=['C00-D48','O99.8']))
        return items

    def test_pregnancy_route_requires_relationship_review_without_changing_code(self):
        text='Tumor maligno con complicaciones en el embarazo.'
        result=explain_candidate(ID,text,self.pregnancy(text),transport=lambda _:self.fail('Model called'))
        self.assertEqual(result['generation_method'],'index_documentary_constraint')
        self.assertEqual(result['analysis']['assessment'],'undetermined')
        self.assertEqual(result['analysis']['concept_id'],ID)
        self.assertIn('index-route',result['analysis']['evidence_refs'])

    def test_code_mention_alone_or_negated_complication_is_not_pregnancy_evidence(self):
        for text in [None,'Embarazo sin complicaciones.','No hay complicaciones en el embarazo.']:
            self.assertIsNone(index_constraint(self.pregnancy(text)))

    def test_dagger_pair_does_not_make_renal_disease_a_dementia_synonym(self):
        text='Demencia urémica.'
        items=base(text);items[0]['text']='Enfermedad renal crónica etapa 5';items[1]['text']='Enfermedad renal crónica estadio 5'
        items.append(dict(id='index-pair',type='CIE10',volume=3,role='index_entry',route=['Demencia','urémica'],text='N18.5† F02.8*',code_references=['N18.5†','F02.8*']))
        result=explain_candidate(ID,text,items,transport=lambda _:self.fail('Model called'))
        self.assertEqual(result['constraint_id'],'index_etiology_manifestation_context')
        self.assertEqual(result['analysis']['selection'],'abstained')
        items=items[:2]+items[3:]
        self.assertIsNone(index_constraint(items))

    def test_ambiguous_navigation_cannot_justify_a_definitive_mapping(self):
        items=base()+[dict(id='index-ambiguous',type='CIE10',volume=3,role='index_remission',requires_documentary_review=True,text='Ver destino ambiguo.')]
        raw=dict(concept_id=ID,assessment='compatible',selection='not_requested',justification='Las fuentes coinciden.',additional_detail_needed=[],cie_evidence_refs=['cie-title','index-ambiguous'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)
        self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['status'],'explanation_rejected')

    def test_index_claim_requires_index_citation(self):
        items=base()+[dict(id='index-path',type='CIE10',volume=3,role='index_entry',text='Ruta del índice.')]
        raw=dict(concept_id=ID,assessment='compatible',selection='not_requested',justification='El índice alfabético respalda la comparación.',additional_detail_needed=[],cie_evidence_refs=['cie-title'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)
        self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['status'],'explanation_rejected')

    def test_budget_preserves_last_complete_source_from_both_volumes(self):
        items=base()+[dict(id='manual',type='CIE10',volume=2,role='manual_convention',text='Regla completa.'),dict(id='index',type='CIE10',volume=3,role='index_entry',text='Ruta completa.'),dict(id='extra',type='CIE10',volume=3,role='index_entry',text='Ruta adicional.')]
        selected,report=fit_model_evidence(ID,None,items,'unused',lambda text:8000 if '"id": "extra"' in text else 4500)
        self.assertEqual({x.get('volume') for x in selected if x.get('volume')},{2,3})
        self.assertFalse(report['truncated_text'])


if __name__=='__main__':unittest.main()

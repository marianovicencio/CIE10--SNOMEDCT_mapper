import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from cie10.reasoning.manual_reasoning import build_manual_context, manual_constraint
from cie10.api.mapping_context import ContextError
from cie10.explanations.candidate_explanation import explain_candidate

HASH = 'a' * 64
ID = '188250002'


def record(identifier, text, scope='morbidity', kind='manual_specific_instruction', section='4.5.4'):
    return dict(id=identifier, kind=kind, scope=scope, section=section, text=text,
                requires_case_context=True, executable_rule=False, sources=[dict(source_ref='s')])


def audit(records, conventions=()):
    return dict(records={x['id']:x for x in records}, source_snapshot_sha256=HASH,
        documents={'d2':dict(volume=2)}, source_locations={'s':dict(document_ref='d2',pdf_page=192,printed_page='181')},
        context_links=[dict(record_id=x['id'],matched_expression='E10-E14',role='instruction_subject') for x in records if x['id'] not in conventions],
        general_convention_refs=list(conventions), supporting_manual_unit_refs=[],
        retrieval=dict(all_selected_pages_retrieved=True,page_count=2,total_selected_records=len(records)))


def base(text=None, code='C64'):
    result=[dict(id='cie-title',type='CIE10',role='title',code=code,text='Tumor maligno del riñón'),
            dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id=ID,text='Neoplasia maligna de parénquima renal')]
    if text:result.append(dict(id='input-diagnostic',type='INPUT',text=text))
    return result



def attributed(value):
    """Build the model fixture with citations attached to its statement."""
    refs=list(value.get('cie_evidence_refs',[]))+list(value.get('snomed_evidence_refs',[]))
    if value.get('diagnostic_evidence_ref'):refs.append(value['diagnostic_evidence_ref'])
    return {key:value[key] for key in ('concept_id','assessment','additional_detail_needed')} | {
        'claims':[{'text':value['justification'] if 'CIE-10' in value['justification'] and 'SNOMED' in value['justification'] else 'Comparación CIE-10 y SNOMED: '+value['justification'],'evidence_refs':refs}]}

class ManualRetrievalTests(unittest.TestCase):
    def build(self, data, transport=None):
        client=SimpleNamespace(fetch_evidence=lambda code,scope:data,transport=transport or (lambda path:{'records':{}}))
        return build_manual_context(dict(code='E10.7',source_snapshot_sha256=HASH),base(),client=client)

    def test_complete_pages_and_roles_are_retained_without_volume3_or_mortality(self):
        rows=[record('v2-rule','Si hay condiciones adicionales, revise el episodio.'),
              record('v2-example','Ejemplo: paciente con gangrena.',kind='manual_worked_example'),
              record('v2-death','Codifique una causa básica.',scope='mortality'),
              record('v3-term','Término del índice.',scope='classification_usage')]
        selected,coverage=self.build(audit(rows))
        self.assertEqual({x['role'] for x in selected},{'manual_instruction','manual_example'})
        self.assertTrue(coverage['linked_context_pages_complete'])
        self.assertEqual(coverage['linked_context_page_count'],2)
        self.assertEqual(coverage['excluded_scope_items'],1)
        for item in selected:
            self.assertFalse(item['patient_facts'])
            self.assertFalse(item['automatic_recoding'])
            self.assertIn('Volumen 2',item['provenance'])

    def test_snapshot_mismatch_and_incomplete_pages_fail_closed(self):
        for field,value in [('source_snapshot_sha256','b'*64),('retrieval',dict(all_selected_pages_retrieved=False))]:
            data=audit([]);data[field]=value
            with self.assertRaises(ContextError):self.build(data)

    def test_convention_continuations_and_final_exception_are_kept_together(self):
        rows=[record('v2-first','Introducción y términos de inclusión.',scope='classification_usage',kind='manual_passage',section={'number':'3.1.2'}),
              record('v2-continuation','No todos los términos son sinónimos. Excepción: conserve la condición.',scope='classification_usage',kind='manual_passage',section={'number':'3.1.2'})]
        selected,_=self.build(audit(rows,[x['id'] for x in rows]))
        self.assertEqual(len(selected),1)
        self.assertIn('Excepción: conserve la condición.',selected[0]['text'])
        self.assertEqual(len(selected[0]['record_ids']),2)
        self.assertEqual(len(selected[0]['detail_urls']),2)

    def test_large_items_are_omitted_whole_and_reported(self):
        row=record('v2-large','Condición y excepción. '*1000)
        selected,coverage=self.build(audit([row]))
        self.assertEqual(selected,[])
        self.assertEqual(coverage['omitted_items'][0]['record_ids'],['v2-large'])

    def test_global_heading_discovery_is_not_used_without_snapshot_bound_content(self):
        heading=record('v2-global','Texto',section='4.5.1 | Especificidad y detalle')
        def transport(path):
            if 'sections' in path:return {'records':{'v2-global':heading}}
            return {'record':heading,'source_snapshot_sha256':'b'*64}
        with self.assertRaises(ContextError):self.build(audit([]),transport)


class ManualReasoningTests(unittest.TestCase):
    def test_service_does_not_claim_volume2_when_no_manual_passage_is_available(self):
        from cie10.explanations.explanation_service import run_explanation
        from cie10.explanations.candidate_explanation import ExplanationError
        with patch('cie10.explanations.explanation_service.prepare_evidence', return_value=base()), patch('cie10.explanations.explanation_service.build_manual_context', return_value=([], {})), patch('cie10.explanations.explanation_service.model_server') as model, patch('cie10.explanations.explanation_service.build_index_context', return_value=([], {})):
            with self.assertRaises(ExplanationError):
                run_explanation(dict(concept_id=ID))
            model.assert_not_called()

    def test_history_requires_episode_clarification_with_manual_citation(self):
        text='Tumor renal extirpado anteriormente. Motivo actual: control.'
        items=base(text)+[dict(id='manual-rule',type='CIE10',role='manual_guidance',volume=2,scope='morbidity',text='Cuando se menciona un tumor primario que fue extirpado antes, revise el episodio actual.')]
        result=explain_candidate(ID,text,items,transport=lambda _:self.fail('Model called'))
        self.assertEqual(result['generation_method'],'manual_documentary_constraint')
        self.assertEqual(result['analysis']['assessment'],'undetermined')
        self.assertEqual(result['analysis']['selection'],'abstained')
        self.assertIn('manual-rule',result['analysis']['evidence_refs'])

    def test_book_example_does_not_supply_history_or_patient_facts(self):
        items=base('Tumor renal actual.')+[dict(id='example',type='CIE10',role='manual_example',volume=2,scope='morbidity',text='Ejemplo: tumor primario que fue extirpado anteriormente.')]
        self.assertIsNone(manual_constraint(items))
        raw=dict(concept_id=ID,assessment='compatible',selection='proposed',justification='El ejemplo confirma los antecedentes del paciente.',additional_detail_needed=[],cie_evidence_refs=['cie-title','example'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref='input-diagnostic')
        result=explain_candidate(ID,'Tumor renal actual.',items,transport=lambda _:dict(content=json.dumps(attributed(raw))))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_negated_history_does_not_activate_the_history_condition(self):
        items=base('No fue extirpado anteriormente.')+[dict(id='rule',type='CIE10',role='manual_guidance',volume=2,scope='morbidity',text='tumor primario que fue extirpado en una ocasión anterior')]
        self.assertIsNone(manual_constraint(items))

    def test_priority_is_required_only_for_asserted_main_condition(self):
        source=dict(id='rule',type='CIE10',role='manual_instruction',volume=2,scope='morbidity',text='La subcategoría .7 se utiliza sin preferencia por ninguna complicación.')
        for text,expected in [('Afección principal: diabetes con varias complicaciones.',True),
                              ('No es afección principal. Diabetes con varias complicaciones.',False),
                              ('Afección principal: diabetes con varias complicaciones sin preferencia.',False)]:
            items=base(text,code='E11.7');items[0]['text']='Diabetes mellitus tipo 2 con complicaciones múltiples';items.append(source)
            self.assertEqual(manual_constraint(items) is not None,expected)

    def test_mortality_citation_cannot_justify_morbidity(self):
        items=base()+[dict(id='death',type='CIE10',role='manual_instruction',volume=2,scope='mortality',text='Paso M1: causa básica.')]
        raw=dict(concept_id=ID,assessment='compatible',selection='not_requested',justification='La clasificación concuerda con el término.',additional_detail_needed=[],cie_evidence_refs=['cie-title','death'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)
        self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['status'],'explanation_rejected')


class ManualGenerationGuards(unittest.TestCase):
    def raw(self, text):
        return dict(concept_id=ID,assessment='compatible',selection='not_requested',justification=text,
                    additional_detail_needed=[],cie_evidence_refs=['cie-title'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)

    def test_book_convention_does_not_establish_manifestation_in_the_patient(self):
        items=base()+[dict(id='manual-pair',type='CIE10',volume=2,role='manual_convention',scope='classification_usage',text='Daga para etiología, asterisco para manifestación.')]
        value=self.raw('Se utiliza el sistema de daga y asterisco para indicar la manifestación de la enfermedad en el riñón.')
        result=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(value))))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_claiming_manual_support_requires_a_volume2_citation(self):
        items=base()+[dict(id='manual-guidance',type='CIE10',volume=2,role='manual_guidance',scope='morbidity',text='Guía de especificidad.')]
        value=self.raw('La guía del manual respalda esta comparación con SNOMED.')
        result=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(value))))
        self.assertEqual(result['status'],'explanation_rejected')
        value['cie_evidence_refs'].append('manual-guidance')
        result=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(value))))
        self.assertEqual(result['status'],'explanation_available')


if __name__=='__main__':unittest.main()

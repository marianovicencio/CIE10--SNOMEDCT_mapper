import copy
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from cie10.explanation_constraints import documentary_constraint
from cie10.explanation_focus import focus_evidence
from cie10.index_reasoning import group_identical_table_context, reading_text
from cie10.candidate_explanation import explain_candidate, generation_setup, model_evidence_view, readable_justification
from cie10.explanation_service import prepare_evidence, VERSION
from cie10.manual_reasoning import build_manual_context

ID='123456789'


def base():
    return [dict(id='cie-title',type='CIE10',role='title',text='Enfermedad renal crónica etapa 5'),
            dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id=ID,text='Enfermedad renal crónica estadio 5')]


def raw(text):
    return dict(concept_id=ID,assessment='compatible',selection='not_requested',justification=text,
                additional_detail_needed=[],cie_evidence_refs=['cie-title'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)



def attributed(value):
    """Build the model fixture with citations attached to its statement."""
    refs=list(value.get('cie_evidence_refs',[]))+list(value.get('snomed_evidence_refs',[]))
    if value.get('diagnostic_evidence_ref'):refs.append(value['diagnostic_evidence_ref'])
    return {key:value[key] for key in ('concept_id','assessment','additional_detail_needed')} | {
        'claims':[{'text':value['justification'] if 'CIE-10' in value['justification'] and 'SNOMED' in value['justification'] else 'Comparación CIE-10 y SNOMED: '+value['justification'],'evidence_refs':refs}]}

class ComparisonFocusTests(unittest.TestCase):
    def test_exclusions_instructions_and_input_stay_even_without_lexical_overlap(self):
        items=base()+[dict(id='exclusion',type='CIE10',role='exclusion',text='Otras condiciones, salvo excepción.',inherited=True),
                      dict(id='instruction',type='CIE10',role='instructions',text='Utilice código adicional si corresponde.'),
                      dict(id='input',type='INPUT',text='Sin mayor precisión.')]
        selected,report=focus_evidence(items)
        self.assertEqual(selected,items)
        self.assertEqual(report['omitted_items'],[])

    def test_unrelated_inclusions_do_not_become_facts_but_remain_in_original_data(self):
        items=base()+[dict(id='retinitis',type='CIE10',role='inclusions',text='Retinitis renal'),
                      dict(id='stage',type='CIE10',role='inclusions',text='Enfermedad renal crónica estadio 5')]
        before=copy.deepcopy(items);selected,report=focus_evidence(items)
        self.assertNotIn('retinitis',{x['id'] for x in selected})
        self.assertIn('stage',{x['id'] for x in selected})
        self.assertEqual(items,before)
        self.assertIn('retinitis',{x['id'] for x in report['omitted_items']})

    def test_episode_rules_and_worked_examples_do_not_fill_an_ordinary_comparison(self):
        items=base()+[dict(id='episode',type='CIE10',volume=2,role='manual_guidance',coding_context='main_condition_in_episode_of_care',text='Afección principal del episodio.'),
                      dict(id='example',type='CIE10',volume=2,role='manual_example',text='Ejemplo clínico.'),
                      dict(id='convention',type='CIE10',volume=2,role='manual_convention',text='Convención de exclusiones.')]
        selected,_=focus_evidence(items)
        self.assertEqual({x['id'] for x in selected},{'cie-title','snomed-term','convention'})
        selected,_=focus_evidence(items+[dict(id='input',type='INPUT',text='Afección principal del episodio: enfermedad renal.')])
        self.assertIn('episode',{x['id'] for x in selected})

    def test_unrelated_index_branch_is_available_for_review_but_not_padded_into_prompt(self):
        items=base()+[dict(id='pregnancy',type='CIE10',volume=3,role='index_entry',selection_score=5,text='Embarazo > complicado por')]
        selected,report=focus_evidence(items)
        self.assertNotIn('pregnancy',{x['id'] for x in selected})
        self.assertEqual(report['omitted_items'][0]['reason'],'index_route_without_candidate_or_input_overlap')


class GroupingAndProjectionTests(unittest.TestCase):
    def table(self,identifier,path,condition='Condición completa. Excepción final.'):
        payload=dict(kind='neoplasm_table_row',route=path,printed_entry='Entrada '+path[-1],
                     columns={'malignant_primary':{'text':'C64'},'benign':{'text':'D30.0'}},
                     matched_columns=['malignant_primary'],table_context={'text':condition})
        return dict(id=identifier,type='CIE10',volume=3,role='index_table',route=path,
                    text=json.dumps(payload),reading_text=reading_text(payload),record_ids=[identifier,'header'],
                    provenance='Volumen 3',detail_urls=['/v1/records/'+identifier],selection_score=40)

    def test_same_cells_and_conditions_share_header_without_losing_paths_or_sources(self):
        items=[self.table('one',['Tumor','parénquima renal']),self.table('two',['Tumor','riñón (parénquima)'])]
        result=group_identical_table_context(items)
        self.assertEqual(len(result),1)
        self.assertEqual(len(result[0]['routes']),2)
        self.assertIn('two',result[0]['record_ids'])
        self.assertEqual(result[0]['reading_text'].count('Condición completa. Excepción final.'),1)
        self.assertIn('Ruta alternativa del índice (no implica sinonimia)',result[0]['reading_text'])

    def test_different_conditions_or_columns_are_never_grouped(self):
        a=self.table('a',['Tumor','sitio A']);b=self.table('b',['Tumor','sitio B'],'Otra excepción.')
        self.assertEqual(len(group_identical_table_context([a,b])),2)
        b=self.table('b',['Tumor','sitio B']);payload=json.loads(b['text']);payload['columns']['benign']['text']='D30.1';b['text']=json.dumps(payload)
        self.assertEqual(len(group_identical_table_context([a,b])),2)

    def test_model_sees_semantics_once_and_audit_still_has_provenance(self):
        item=dict(id='manual',type='CIE10',volume=2,role='manual_instruction',text='Si ocurre X, conserve la excepción Y.',
                  provenance='Documento y página',record_ids=['original'],detail_urls=['/v1/records/original'],
                  scope='morbidity',requires_case_context=True,document_references=[{'resolution':'printed_number_title_conflict'}])
        projected=model_evidence_view(item)
        self.assertNotIn('provenance',projected)
        self.assertNotIn('record_ids',projected)
        self.assertEqual(projected['text'],item['text'])
        self.assertEqual(projected['document_references'],item['document_references'])
        self.assertIn('provenance',item)
        schema,prompt=generation_setup(ID,None,base())
        self.assertEqual(schema['properties']['concept_id']['enum'],[ID])
        self.assertIn('ESQUEMA DE RESPUESTA',prompt)
        self.assertIn('"enum"',prompt)

    def test_numbered_note_keeps_its_intro_and_final_condition_as_one_item(self):
        doc=dict(source_snapshot_sha256='a'*64,title='Descripción',classification={},tabular={
            'general_context':[dict(title='Notas',text='Aplicar bajo esta condición.',numbered_notes=[
                dict(number=1,text='Primera nota. Excepción completa.'),dict(number=2,text='Segunda nota completa.')])]})
        lookup=dict(parameter=[dict(name='version',valueString=VERSION),dict(name='display',valueString='Concepto clínico')])
        with patch('cie10.explanation_service.get_json',return_value=doc),patch('cie10.explanation_service.SnowstormFHIR') as fhir:
            fhir.return_value.get.return_value=lookup
            result=prepare_evidence(dict(code='N18.5',concept_id=ID,source_snapshot_sha256='a'*64,target_version=VERSION))
        notes=[x for x in result if x.get('role')=='general_context']
        self.assertEqual(len(notes),2)
        self.assertTrue(all('Aplicar bajo esta condición.' in x['text'] for x in notes))
        self.assertIn('Excepción completa.',notes[0]['text'])


class ExplanationQualityTests(unittest.TestCase):
    def test_compatibility_cannot_cite_only_a_parent_instead_of_the_candidate(self):
        items=base()+[dict(id='parent',type='SNOMED',role='parent',concept_id=ID,text='Enfermedad renal')]
        answer=raw('La enfermedad renal crónica en estadio 5 coincide entre CIE-10 y SNOMED.');answer['snomed_evidence_refs']=['parent']
        result=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(answer))))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_boilerplate_and_clinical_confirmation_are_rejected_without_weakening_guards(self):
        for text in ['Se incluyen referencias para contextualizar la clasificación.','La correspondencia confirma la presencia de enfermedad renal.']:
            answer=raw(text)
            self.assertEqual(explain_candidate(ID,None,base(),transport=lambda _:dict(content=json.dumps(attributed(answer))))['status'],'explanation_rejected')

    def test_known_numeric_identity_annotation_is_removed_without_changing_assertion(self):
        items=base()+[dict(id='snomed-116676008-123456789',type='SNOMED',concept_id=ID,text='Morfología asociada neoplasia maligna')]
        sources={x['id']:x for x in items}
        self.assertEqual(readable_justification('El término (116676008-123456789) conserva el sitio.',ID,sources,['cie-title','snomed-term']),
                         'El término conserva el sitio.')
        self.assertEqual(readable_justification('Dato desconocido (999999999-888888888).',ID,sources,['cie-title','snomed-term']),
                         'Dato desconocido (999999999-888888888).')

    def test_documentary_comparison_with_clinical_caution_remains_valid(self):
        answer=raw('CIE-10 y SNOMED describen enfermedad renal crónica en estadio 5. Esta comparación no confirma la presencia de enfermedad en el paciente.')
        result=explain_candidate(ID,None,base(),transport=lambda _:dict(content=json.dumps(attributed(answer))))
        self.assertEqual(result['status'],'explanation_available')


class HistologySpecificityTests(unittest.TestCase):
    def evidence(self, diagnostic=None, with_morphology=True):
        items=[dict(id='cie-title',type='CIE10',role='title',text='Tumor maligno de la pelvis renal'),
               dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id=ID,text='Neoplasia epitelial maligna de pelvis renal')]
        if with_morphology:
            items.append(dict(id='morphology',type='SNOMED',role='116676008',concept_id=ID,text='Morfología asociada neoplasia epitelial maligna'))
        if diagnostic:items.append(dict(id='input',type='INPUT',text=diagnostic))
        return items

    def test_missing_negated_historical_or_suspected_lineage_cannot_be_added(self):
        for diagnostic in [None,'Tumor maligno de pelvis renal.','No se confirma origen epitelial.',
                           'Antecedente de tumor epitelial.','Sospecha de neoplasia epitelial.']:
            with self.subTest(diagnostic=diagnostic):
                rule=documentary_constraint(self.evidence(diagnostic))
                self.assertEqual(rule['assessment'],'undetermined')
                self.assertIn('morphology',rule['evidence_refs'])

    def test_explicit_local_exclusion_outranks_missing_histology(self):
        items=self.evidence('Tumor maligno del parénquima renal.')
        items[0]['text']='Tumor maligno del riñón, excepto de la pelvis renal'
        items.extend([dict(id='exclude',type='CIE10',role='exclusion',text='Pelvis renal (C65)',inherited=False),
                      dict(id='site',type='SNOMED',role='finding_site',concept_id=ID,text='Pelvis renal')])
        result=explain_candidate(ID,'Tumor maligno del parénquima renal.',items)
        self.assertEqual(result['analysis']['assessment'],'incompatible')
        self.assertEqual(result['generation_method'],'explicit_local_anatomical_exclusion')

    def test_explicit_epithelial_diagnostic_removes_the_missing_detail_constraint(self):
        self.assertIsNone(documentary_constraint(self.evidence('Neoplasia epitelial maligna de pelvis renal.')))

    def test_guard_requires_typed_morphology_and_does_not_assume_a_histology(self):
        self.assertIsNone(documentary_constraint(self.evidence(with_morphology=False)))
        items=self.evidence();items[0]['text']='Neoplasia epitelial maligna de pelvis renal'
        self.assertIsNone(documentary_constraint(items))


if __name__=='__main__':unittest.main()

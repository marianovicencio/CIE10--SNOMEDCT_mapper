import copy
import json
import unittest
from unittest.mock import patch
from cie10.candidate_explanation import ExplanationError, explain_candidate, validate_explanation, anatomical_exclusion
from cie10.explanation_constraints import documentary_constraint, renal_stage, diabetes_control, scope_notes
from cie10.explanation_service import run_explanation


MANUAL_STUB = dict(id='manual-test',type='CIE10',volume=2,role='manual_convention',section='3.1.2',title='Convención',scope='classification_usage',requires_case_context=False,contains_worked_examples=False,text='Convención documental.',provenance='Volumen 2',record_ids=['v2-test'])


ID = '123456789'


def evidence(title, term, diagnostic=None):
    items = [dict(id='cie-title', type='CIE10', role='title', text=title),
             dict(id='snomed-term', type='SNOMED', role='candidate_term', concept_id=ID, text=term)]
    if diagnostic:
        items.append(dict(id='input-diagnostic', type='INPUT', text=diagnostic))
    return items



def attributed(value):
    """Build the model fixture with citations attached to its statement."""
    refs=list(value.get('cie_evidence_refs',[]))+list(value.get('snomed_evidence_refs',[]))
    if value.get('diagnostic_evidence_ref'):refs.append(value['diagnostic_evidence_ref'])
    return {key:value[key] for key in ('concept_id','assessment','additional_detail_needed')} | {
        'claims':[{'text':value['justification'] if 'CIE-10' in value['justification'] and 'SNOMED' in value['justification'] else 'Comparación CIE-10 y SNOMED: '+value['justification'],'evidence_refs':refs}]}

class DocumentaryConstraintTests(unittest.TestCase):
    def test_renal_stage_variants_are_compared_within_the_disease_family(self):
        for left, right in [('5', '4'), ('IV', 'III'), ('3A', '3B')]:
            with self.subTest(left=left, right=right):
                items = evidence('Enfermedad renal crónica, etapa ' + left,
                                 'Enfermedad renal crónica, estadio ' + right)
                result = explain_candidate(ID, None, items, transport=lambda _: self.fail('Model called'))
                self.assertEqual(result['analysis']['assessment'], 'incompatible')
                self.assertEqual(result['generation_method'], 'documentary_constraint')
        self.assertIsNone(renal_stage('Tratamiento etapa 4 durante 5 días.'))
        self.assertIsNone(renal_stage('Enfermedad renal crónica sin estadio 4 confirmado.'))

    def test_input_stage_conflict_cannot_be_overruled_by_matching_code_and_candidate(self):
        text = 'Enfermedad renal crónica, etapa 2.'
        items = evidence('Enfermedad renal crónica, etapa 3', 'Enfermedad renal crónica, estadio 3', text)
        result = explain_candidate(ID, text, items, transport=lambda _: self.fail('Model called'))
        self.assertEqual(result['analysis']['selection'], 'abstained')
        self.assertEqual(result['constraint_id'], 'diagnostic_renal_stage_conflict')

    def test_matching_stages_do_not_manufacture_a_positive_mapping(self):
        items = evidence('Enfermedad renal crónica, etapa 4', 'Enfermedad renal crónica, estadio IV')
        self.assertIsNone(documentary_constraint(items))

    def test_substage_missing_and_omitted_are_not_false_conflicts(self):
        for left, right in [('3', '3A'), ('3B', '3')]:
            result = documentary_constraint(evidence('Enfermedad renal crónica, etapa '+left,
                                                   'Enfermedad renal crónica, estadio '+right))
            self.assertEqual(result['assessment'], 'undetermined')
            self.assertTrue(result['additional_detail_needed'])

    def test_negated_or_ambiguous_stage_requires_clarification(self):
        for text in ['Enfermedad renal crónica sin estadio 5 confirmado.',
                     'Enfermedad renal crónica, estadio 4 o estadio 5.']:
            result = documentary_constraint(evidence('Enfermedad renal crónica etapa 5', 'Enfermedad renal crónica estadio 5', text))
            self.assertEqual(result['assessment'], 'undetermined')

    def test_control_conflict_works_both_directions(self):
        for incoming, target in [('bien controlada', 'no controlada'), ('mal controlada', 'bien controlada')]:
            text = 'Diabetes mellitus tipo 2 ' + incoming
            result = documentary_constraint(evidence('Diabetes mellitus tipo 2', 'Diabetes mellitus tipo 2 '+target, text))
            self.assertEqual(result['assessment'], 'incompatible')
        self.assertIsNone(diabetes_control('Diabetes mellitus sin mal control documentado'))
        self.assertIsNone(diabetes_control('Diabetes mellitus, no está bien controlada'))

    def test_missing_control_is_not_inferred_from_complications(self):
        items = evidence('Diabetes mellitus tipo 2 con complicaciones múltiples', 'Diabetes mellitus tipo 2 no controlada')
        result = documentary_constraint(items)
        self.assertEqual(result['assessment'], 'undetermined')
        self.assertIn('control', result['additional_detail_needed'][0])

    def test_control_does_not_replace_multiple_complications(self):
        text = 'Diabetes mellitus tipo 2 no controlada'
        result = documentary_constraint(evidence('Diabetes mellitus tipo 2 con complicaciones múltiples', 'Diabetes mellitus tipo 2 no controlada', text))
        self.assertEqual(result['rule_id'], 'diabetes_complications_not_control')

    def test_anatomical_wildcard_typography_preserves_local_exclusion(self):
        for suffix in ['C74.-', 'C74.–', 'C74.−']:
            items = evidence('Neoplasia maligna de glándulas endocrinas', 'Neoplasia de glándula suprarrenal')
            items += [dict(id='exclude', type='CIE10', role='exclusion', inherited=False, text='Glándula suprarrenal ('+suffix+')'),
                      dict(id='site', type='SNOMED', concept_id=ID, role='finding_site', text='Estructura de la glándula suprarrenal')]
            self.assertEqual(anatomical_exclusion(items), 'exclude')
            items[-2]['inherited'] = True
            self.assertIsNone(anatomical_exclusion(items))

    def test_conditional_drug_exclusion_requires_explicit_conditions(self):
        def sources(text=None):
            items = evidence('Otras drogas', 'Alergia a medicamento', text)
            items.extend([dict(id='block', type='CIE10', role='hierarchy', text='Envenenamiento por drogas y medicamentos'),
                          dict(id='adverse', type='CIE10', role='exclusion', inherited=True,
                               text='efectos adversos de sustancias administradas apropiadamente')])
            return items
        text = 'Reacción alérgica con dosis correcta. No hubo sobredosis ni error.'
        self.assertEqual(documentary_constraint(sources(text))['assessment'], 'incompatible')
        for text in [None, 'Reacción alérgica.', 'Reacción alérgica, no dosis correcta. No hubo sobredosis ni error.']:
            self.assertEqual(documentary_constraint(sources(text))['assessment'], 'undetermined')
        items = sources();items[-1]['role'] = 'inclusions'
        self.assertIsNone(documentary_constraint(items))

    def test_missing_tissue_produces_scope_guidance_without_forcing_compatibility(self):
        items = evidence('Tumor maligno de la extremidad inferior', 'Neoplasia maligna de miembro inferior',
                         'Tumor maligno del miembro inferior sin tejido de origen especificado.')
        self.assertTrue(scope_notes(items))
        self.assertIsNone(documentary_constraint(items))

    def test_documentary_conflict_is_checked_in_final_validator(self):
        items = evidence('Enfermedad renal crónica etapa 2', 'Enfermedad renal crónica estadio 4')
        answer = dict(concept_id=ID, assessment='compatible', justification='Ambas fuentes coinciden.',
                      selection='not_requested', additional_detail_needed=[], evidence_refs=[x['id'] for x in items],
                      quotes=[dict(evidence_id=x['id'],text=x['text']) for x in items])
        with self.assertRaises(ExplanationError):
            validate_explanation(answer, ID, None, items)

    def test_service_skips_gpu_for_documentary_constraints(self):
        items = evidence('Enfermedad renal crónica etapa 5', 'Enfermedad renal crónica estadio 4')
        with patch('cie10.explanation_service.prepare_evidence', return_value=items), patch('cie10.explanation_service.model_server') as model, patch('cie10.explanation_service.build_manual_context', return_value=([MANUAL_STUB], {})), patch('cie10.explanation_service.build_index_context', return_value=([], {})):
            result = run_explanation(dict(concept_id=ID, diagnostic_text='', source_snapshot_sha256='a'*64))
            model.assert_not_called()
            self.assertIsNone(result['analysis'])
            self.assertEqual(result['documentary_constraint']['assessment'], 'incompatible')
            self.assertEqual(result['status'], 'explanation_unavailable')


class CitationAndProseTests(unittest.TestCase):
    def test_multiple_citations_are_copied_with_their_original_roles(self):
        items = evidence('Descripción oficial', 'Concepto clínico')
        items.append(dict(id='note', type='CIE10', role='notes', text='Nota de contexto'))
        raw = dict(concept_id=ID, assessment='compatible', justification='El concepto concuerda con la descripción y la nota.', selection='not_requested', additional_detail_needed=[], cie_evidence_refs=['cie-title','note'], snomed_evidence_refs=['snomed-term'], diagnostic_evidence_ref=None)
        result = explain_candidate(ID, None, items, transport=lambda _: dict(content=json.dumps(attributed(raw))))
        self.assertEqual(len(result['analysis']['quotes']), 3)

    def test_real_citations_do_not_validate_exclusion_as_confirmation(self):
        items = evidence('Descripción oficial', 'Concepto clínico')
        raw = dict(concept_id=ID, assessment='compatible', justification='La exclusión confirma la correspondencia.', selection='not_requested', additional_detail_needed=[], cie_evidence_refs=['cie-title'], snomed_evidence_refs=['snomed-term'], diagnostic_evidence_ref=None)
        result = explain_candidate(ID, None, items, transport=lambda _: dict(content=json.dumps(attributed(raw))))
        self.assertEqual(result['status'], 'explanation_rejected')

    def test_scope_confusion_cannot_pass_with_real_citations(self):
        text='Tumor de miembro inferior sin tejido de origen especificado.'
        items=evidence('Tumor maligno de miembro inferior','Neoplasia maligna de miembro inferior',text)
        raw=dict(concept_id=ID,assessment='incompatible',justification='La falta de tejido de origen implica sitio no especificado e incompatibilidad.',selection='abstained',additional_detail_needed=[],cie_evidence_refs=['cie-title'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref='input-diagnostic')
        result=explain_candidate(ID,text,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_internal_identifiers_do_not_leak_into_generated_prose(self):
        items=evidence('Descripción oficial','Concepto clínico')
        raw=dict(concept_id=ID,assessment='compatible',justification='El CIE-10 '+ID+' coincide.',selection='not_requested',additional_detail_needed=[],cie_evidence_refs=['cie-title'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)
        self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['status'],'explanation_rejected')


class PresentationReferenceTests(unittest.TestCase):
    def raw(self, text):
        return dict(concept_id=ID,assessment='compatible',justification=text,selection='not_requested',additional_detail_needed=[],cie_evidence_refs=['cie-title'],snomed_evidence_refs=['snomed-term'],diagnostic_evidence_ref=None)

    def test_redundant_parenthetical_sctid_is_removed_without_changing_the_claim(self):
        items=evidence('Descripción oficial','Concepto clínico')
        value=self.raw('El concepto SNOMED ('+ID+') concuerda con la descripción CIE-10.')
        result=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(value))))
        self.assertEqual(result['analysis']['justification'],'El concepto SNOMED concuerda con la descripción CIE-10.')

    def test_misattributed_sctid_is_not_hidden_by_presentation_cleanup(self):
        items=evidence('Descripción oficial','Concepto clínico')
        value=self.raw('El CIE-10 ('+ID+') concuerda.')
        result=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(value))))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_prose_reference_must_be_present_in_citations(self):
        items=evidence('Descripción oficial','Concepto clínico')
        items.append(dict(id='cie-notes-0',type='CIE10',role='notes',text='Nota'))
        for ref in ['cie-notes-0','cie-invented-1']:
            value=self.raw('La evidencia '+ref+' respalda el análisis.')
            self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(value))))['status'],'explanation_rejected')


class ProseRegressionTests(unittest.TestCase):
    def test_plural_exclusions_cannot_confirm_mapping(self):
        items=evidence('Descripción oficial','Concepto clínico')
        raw=PresentationReferenceTests().raw('Las exclusiones confirman la compatibilidad.')
        self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['status'],'explanation_rejected')

    def test_correctly_labelled_sctid_is_redundant_presentation(self):
        items=evidence('Descripción oficial','Concepto clínico')
        raw=PresentationReferenceTests().raw('El término SNOMED '+ID+' coincide con el título CIE-10.')
        answer=explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['analysis']
        self.assertEqual(answer['justification'],'El término SNOMED coincide con el título CIE-10.')


class ScopeAndCodePunctuationTests(unittest.TestCase):
    def test_icd_decimal_points_cannot_bypass_polarity_check(self):
        items=evidence('Descripción oficial','Concepto clínico')
        raw=PresentationReferenceTests().raw('La jerarquía y las exclusiones (C80.-, C81-C96) confirman la compatibilidad.')
        self.assertEqual(explain_candidate(ID,None,items,transport=lambda _:dict(content=json.dumps(attributed(raw))))['status'],'explanation_rejected')

    def test_known_region_does_not_become_unknown_site_for_missing_tissue(self):
        text='Tumor maligno de miembro inferior, sin tejido de origen especificado.'
        items=evidence('Tumor maligno del miembro inferior','Neoplasia maligna de extremidad inferior',text)
        items.append(dict(id='exclude',type='CIE10',role='exclusion',inherited=True,text='tumor maligno de sitio no especificado (C80.-)'))
        answer=explain_candidate(ID,text,items,transport=lambda _:self.fail('Model called'))['analysis']
        self.assertEqual(answer['assessment'],'undetermined')
        self.assertEqual(answer['selection'],'abstained')
        self.assertTrue(answer['additional_detail_needed'])
        self.assertIn('exclude',answer['evidence_refs'])


if __name__ == '__main__':
    unittest.main()

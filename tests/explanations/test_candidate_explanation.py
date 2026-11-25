import copy
import json
import unittest

from cie10.explanations.candidate_explanation import ExplanationError, explain_candidate, validate_explanation

ID = '188250002'
TEXT = 'Tumor maligno del parénquima renal.'
EVIDENCE = [
    {'id': 'cie', 'type': 'CIE10', 'text': 'Cálices renal(es) (C65)'},
    {'id': 'sct', 'type': 'SNOMED', 'concept_id': ID, 'text': 'neoplasia maligna de parénquima renal'},
    {'id': 'input', 'type': 'INPUT', 'text': TEXT}
]


def answer():
    return {
        'concept_id': ID, 'assessment': 'compatible', 'selection': 'proposed',
        'justification': 'El diagnóstico especifica parénquima renal.',
        'evidence_refs': ['cie', 'sct', 'input'],
        'quotes': [{'evidence_id': item['id'], 'text': item['text']} for item in EVIDENCE],
        'additional_detail_needed': []
    }


def generated(value):
    return {key: value[key] for key in
            ('concept_id', 'assessment', 'justification', 'selection', 'additional_detail_needed')} | {
                'cie_evidence_refs': ['cie'], 'snomed_evidence_refs': ['sct'],
                'diagnostic_evidence_ref': 'input'
            }



def attributed(value):
    """Build the model fixture with citations attached to its statement."""
    refs=list(value.get('cie_evidence_refs',[]))+list(value.get('snomed_evidence_refs',[]))
    if value.get('diagnostic_evidence_ref'):refs.append(value['diagnostic_evidence_ref'])
    return {key:value[key] for key in ('concept_id','assessment','additional_detail_needed')} | {
        'claims':[{'text':value['justification'] if 'CIE-10' in value['justification'] and 'SNOMED' in value['justification'] else 'Comparación CIE-10 y SNOMED: '+value['justification'],'evidence_refs':refs}]}

class ExplanationTests(unittest.TestCase):
    def test_rejects_incompatible_selection_even_with_real_citations(self):
        value = answer()
        value['assessment'] = 'incompatible'
        with self.assertRaises(ExplanationError):
            validate_explanation(value, ID, TEXT, EVIDENCE)

    def test_code_only_requires_not_requested(self):
        value = answer()
        with self.assertRaises(ExplanationError):
            validate_explanation(value, ID, None, EVIDENCE[:2])
        value['selection'] = 'not_requested'
        value['evidence_refs'] = ['cie', 'sct']
        value['quotes'] = value['quotes'][:2]
        self.assertEqual(validate_explanation(value, ID, None, EVIDENCE[:2]), value)

    def test_rejects_unknown_citation_and_false_literal_quote(self):
        for change in ('unknown', 'quote'):
            value = answer()
            if change == 'unknown':
                value['evidence_refs'][0] = 'inventada'
            else:
                value['quotes'][0]['text'] = 'Cálculos renales'
            with self.assertRaises(ExplanationError):
                validate_explanation(value, ID, TEXT, EVIDENCE)

    def test_calyx_calculus_regression(self):
        value = answer()
        value['justification'] = 'El código excluye cálculos renales.'
        with self.assertRaises(ExplanationError):
            validate_explanation(value, ID, TEXT, EVIDENCE)

    def test_selection_rejects_missing_detail_and_missing_input_citation(self):
        value = answer()
        value['additional_detail_needed'] = ['Especificar el sitio']
        with self.assertRaises(ExplanationError):
            validate_explanation(value, ID, TEXT, EVIDENCE)
        value = answer()
        value['evidence_refs'] = ['cie', 'sct']
        value['quotes'] = value['quotes'][:2]
        with self.assertRaises(ExplanationError):
            validate_explanation(value, ID, TEXT, EVIDENCE)

    def test_rejects_wrong_concept_evidence_before_calling_model(self):
        evidence = copy.deepcopy(EVIDENCE)
        evidence[1]['concept_id'] = '448215006'
        with self.assertRaises(ExplanationError):
            explain_candidate(ID, TEXT, evidence, transport=lambda _: self.fail('Model was called'))

    def test_repair_and_final_rejection(self):
        bad = answer()
        bad['justification'] = 'El código excluye cálculos renales.'
        replies = iter([bad, answer()])
        calls = []
        def transport(body):
            calls.append(body)
            value = next(replies)
            return {'content': json.dumps(attributed(generated(value))), 'stop_type': 'eos'}
        result = explain_candidate(ID, TEXT, EVIDENCE, transport=transport)
        self.assertEqual(result['status'], 'explanation_available')
        self.assertEqual(result['attempts'], 2)
        self.assertIn('Corrige esta validación', calls[1]['prompt'])
        self.assertIn('INTENTO ANTERIOR', calls[1]['prompt'])
        self.assertEqual(calls[0]['json_schema']['properties']['concept_id']['enum'], [ID])
        self.assertFalse(calls[0]['cache_prompt'])
        result = explain_candidate(ID, TEXT, EVIDENCE,
            transport=lambda _: {'content': json.dumps(attributed(generated(bad))), 'stop_type': 'eos'})
        self.assertEqual(result['status'], 'explanation_rejected')
        self.assertIsNone(result['analysis'])

    def test_generated_references_are_typed_and_quotes_are_copied(self):
        result = explain_candidate(ID, TEXT, EVIDENCE,
            transport=lambda _: {'content': json.dumps(attributed(generated(answer()))), 'stop_type': 'eos'})
        self.assertEqual(result['analysis']['quotes'], [
            {'evidence_id': item['id'], 'text': item['text']} for item in EVIDENCE
        ])
        bad = generated(answer())
        bad['cie_evidence_refs'] = ['sct']
        result = explain_candidate(ID, TEXT, EVIDENCE,
            transport=lambda _: {'content': json.dumps(attributed(bad)), 'stop_type': 'eos'})
        self.assertEqual(result['status'], 'explanation_rejected')

    def test_local_anatomical_exclusion_cannot_be_declared_compatible(self):
        evidence = copy.deepcopy(EVIDENCE)
        evidence[0].update(text='Pelvis renal(es) (C65)', role='exclusion', inherited=False)
        evidence[1].update(text='sitio del hallazgo estructura de la pelvis renal', role='finding_site')
        value = answer()
        value['quotes'] = [{'evidence_id': item['id'], 'text': item['text']} for item in evidence]
        with self.assertRaises(ExplanationError):
            validate_explanation(value, ID, TEXT, evidence)

    def test_anatomical_guard_does_not_expand_inherited_or_conditional_exclusions(self):
        from cie10.explanations.candidate_explanation import anatomical_exclusion
        evidence = copy.deepcopy(EVIDENCE)
        evidence[0].update(text='Pelvis renal(es) (C65)', role='exclusion', inherited=True)
        evidence[1].update(text='sitio del hallazgo estructura de la pelvis renal', role='finding_site')
        self.assertIsNone(anatomical_exclusion(evidence))
        evidence[0].update(text='Pelvis renal si se indica origen primario (C65)', inherited=False)
        self.assertIsNone(anatomical_exclusion(evidence))
        evidence[0]['text'] = 'Pelvis renal(es) (C65)'
        evidence[1]['text'] = 'sitio del hallazgo estructura de parénquima de riñón'
        self.assertIsNone(anatomical_exclusion(evidence))

    def test_exact_anatomical_exclusion_uses_sources_without_generation(self):
        evidence = copy.deepcopy(EVIDENCE)
        evidence[0].update(text='Pelvis renal(es) (C65)', role='exclusion', inherited=False)
        evidence[1].update(text='sitio del hallazgo estructura de la pelvis renal', role='finding_site')
        for diagnostic in (None, TEXT):
            sources = evidence if diagnostic else evidence[:2]
            result = explain_candidate(ID, diagnostic, sources,
                transport=lambda _: self.fail('Model must not be called'))
            self.assertEqual(result['generation_method'], 'explicit_local_anatomical_exclusion')
            self.assertEqual(result['analysis']['assessment'], 'incompatible')
            self.assertEqual(result['analysis']['selection'], 'abstained' if diagnostic else 'not_requested')
            self.assertIn('Pelvis renal(es) (C65)', result['analysis']['justification'])
            self.assertNotIn('cáliz', result['analysis']['justification'])

    def test_truncated_result_and_non_json_are_never_presented(self):
        for response in ({'content': json.dumps(answer()), 'stop_type': 'limit'},
                         {'content': 'Respuesta sin estructura', 'stop_type': 'eos'}):
            result = explain_candidate(ID, TEXT, EVIDENCE, transport=lambda _: response)
            self.assertEqual(result['status'], 'explanation_rejected')

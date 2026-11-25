import unittest
from cie10.explanations.explanation_budget import fit_model_evidence
from cie10.explanations.candidate_explanation import ExplanationError


class ContextBudgetTests(unittest.TestCase):
    def base(self):
        return [dict(id='cie-title',type='CIE10',role='title',text='Título'),
                dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id='123456789',text='Término'),
                dict(id='local-exclusion',type='CIE10',role='exclusion',text='Exclusión obligatoria'),
                dict(id='manual-rule',type='CIE10',volume=2,role='manual_convention',scope='classification_usage',text='Convención completa con excepción final.')]

    def test_drops_complete_optional_context_without_losing_core_or_last_manual_item(self):
        items=self.base()+[dict(id='overview',type='CIE10',role='general_context',text='Resumen contextual largo con excepción.')]
        def tokenizer(prompt):return 8000 if '"id": "overview"' in prompt else 4500
        selected,report=fit_model_evidence('123456789',None,items,'unused',tokenizer)
        self.assertEqual({x['id'] for x in selected},{'cie-title','snomed-term','local-exclusion','manual-rule'})
        self.assertFalse(report['truncated_text'])
        self.assertEqual(report['omitted_items'][0]['id'],'overview')
        self.assertEqual(selected[-1]['text'],items[-2]['text'])

    def test_cannot_silently_remove_mandatory_exclusion_or_last_manual_source(self):
        with self.assertRaises(ExplanationError):
            fit_model_evidence('123456789',None,self.base(),'unused',lambda _:9000)

    def test_fits_without_omitting_any_source_when_budget_allows(self):
        selected,report=fit_model_evidence('123456789',None,self.base(),'unused',lambda _:1000)
        self.assertEqual(selected,self.base())
        self.assertEqual(report['omitted_items'],[])
        self.assertLessEqual(report['input_tokens']+report['max_new_tokens'],report['context_limit'])


if __name__=='__main__':unittest.main()

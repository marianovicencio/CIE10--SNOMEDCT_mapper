"""Expanded generated prose keeps per-paragraph attribution and bounded budgets."""
import json
import unittest
from cie10.candidate_explanation import explain_candidate
from cie10.explanation_contract import response_schema
from cie10.explanation_prompt import generation_setup
from cie10.explanation_budget import fit_model_evidence
from cie10.explanation_limits import MAX_CLAIMS, LOCAL_MAX_NEW_TOKENS, LOCAL_REPAIR_RESERVE_TOKENS

CID = '109844006'

def evidence():
    return [dict(id='cie-title',type='CIE10',role='title',text='Angiosarcoma del hígado'),
            dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id=CID,text='angiosarcoma de hígado')]

PARAGRAPHS = [
    'El título CIE-10 y el término SNOMED coinciden en angiosarcoma y en su localización en el hígado. La diferencia entre del hígado y de hígado corresponde a la formulación gramatical y conserva los mismos términos de la afección y del órgano.',
    'En esta comparación, el candidato SNOMED conserva el tipo de tumor nombrado por CIE-10 y no cambia el sitio por otro órgano. La correspondencia documental se apoya en esas dos coincidencias específicas, que deben considerarse conjuntamente al revisar el alcance de los términos.'
]

class ExpandedExplanationTests(unittest.TestCase):
    def run_generated(self, paragraphs, references=None):
        raw=dict(concept_id=CID,assessment='compatible',additional_detail_needed=[],claims=[dict(text=p,evidence_refs=(references[i] if references else ['cie_title','snomed_term'])) for i,p in enumerate(paragraphs)])
        calls=[]
        def transport(body):
            calls.append(body)
            return dict(content=json.dumps(raw))
        return explain_candidate(CID,None,evidence(),transport=transport),calls

    def test_longer_mult_paragraph_generation_retains_own_sources(self):
        result,calls=self.run_generated(PARAGRAPHS)
        self.assertEqual(result['status'],'explanation_available')
        self.assertGreater(len(result['analysis']['justification'].split()),70)
        self.assertEqual(len(result['attributed_claims']),2)
        self.assertTrue(all(c['evidence_refs']==['cie-title','snomed-term'] for c in result['attributed_claims']))
        self.assertEqual(calls[0]['n_predict'],LOCAL_MAX_NEW_TOKENS)
        self.assertEqual(len(calls),1)
        self.assertEqual([q['text'] for q in result['analysis']['quotes']],[x['text'] for x in evidence()])

    def test_single_short_comparison_remains_valid(self):
        result,_=self.run_generated(['CIE-10 y SNOMED coinciden en angiosarcoma de hígado.'])
        self.assertEqual(result['status'],'explanation_available')

    def test_second_paragraph_cannot_omit_its_base_sources(self):
        result,_=self.run_generated(PARAGRAPHS,[['cie_title','snomed_term'],['snomed_term']])
        self.assertEqual(result['status'],'explanation_rejected')
        self.assertIsNone(result['analysis'])
        self.assertTrue(any('fuentes de base' in e for e in result['errors']))

    def test_repeated_paragraph_is_rejected(self):
        result,_=self.run_generated([PARAGRAPHS[0],PARAGRAPHS[0]])
        self.assertEqual(result['status'],'explanation_rejected')
        self.assertTrue(any('repetir' in e for e in result['errors']))

    def test_word_limit_per_paragraph_is_preserved(self):
        result,_=self.run_generated(['CIE-10 y SNOMED coinciden. '+'a '*221])
        self.assertEqual(result['status'],'explanation_rejected')
        self.assertTrue(any('220' in e for e in result['errors']))

    def test_total_word_limit_is_enforced_across_paragraphs(self):
        paragraphs=['CIE-10 y SNOMED coinciden en esta comparación '+('texto '*70)+ending for ending in ['primera','segunda','tercera']]
        result,_=self.run_generated(paragraphs)
        self.assertEqual(result['status'],'explanation_rejected')
        self.assertTrue(any('220' in e for e in result['errors']))

    def test_too_many_paragraphs_are_rejected(self):
        result,_=self.run_generated([f'CIE-10 y SNOMED coinciden en el término {i}.' for i in range(5)])
        self.assertEqual(result['status'],'explanation_rejected')

    def test_schema_and_instruction_allow_detail_without_minimum_padding(self):
        schema,prompt=generation_setup(CID,None,evidence())
        self.assertEqual(schema['properties']['claims']['maxItems'],MAX_CLAIMS)
        self.assertEqual(schema['properties']['claims']['minItems'],1)
        self.assertIn('100–180',prompt)
        self.assertNotIn('45 palabras',prompt)
        self.assertIn('una coincidencia sencilla puede explicarse con menos',prompt)

    def test_local_profile_bounds_prose_and_preserves_base_citations(self):
        schema,prompt=generation_setup(CID,None,evidence(),profile="local")
        claims=schema["properties"]["claims"]
        self.assertEqual(claims["maxItems"],1)
        self.assertEqual(claims["items"]["properties"]["text"]["maxLength"],900)
        self.assertIn("60–100",prompt)
        refs=claims["items"]["properties"]["evidence_refs"]
        for branch in refs["anyOf"]:
            self.assertEqual([x["enum"][0] for x in branch["items"][:2]],["cie_title","snomed_term"])

    def test_expanded_output_and_repair_both_fit_reserved_context(self):
        _,report=fit_model_evidence(CID,None,evidence(),'unused',lambda _:4500)
        self.assertEqual(report['max_new_tokens'],LOCAL_MAX_NEW_TOKENS)
        self.assertEqual(report['repair_reserve_tokens'],LOCAL_REPAIR_RESERVE_TOKENS)
        self.assertLessEqual(report['input_tokens']+report['max_new_tokens']+report['repair_reserve_tokens'],report['context_limit'])

    def test_multiple_context_sources_can_support_the_same_paragraph(self):
        items = evidence() + [dict(id='site',type='SNOMED',concept_id=CID,role='finding_site',text='hígado'), dict(id='note',type='CIE10',role='notes',text='Nota documental del código.')]
        schema=response_schema(CID,None,items)
        refs=schema['properties']['claims']['items']['properties']['evidence_refs']
        self.assertGreaterEqual(refs['maxItems'],4)
        raw=dict(concept_id=CID,assessment='compatible',additional_detail_needed=[],claims=[dict(text='El título CIE-10 y el término SNOMED coinciden en angiosarcoma de hígado.',evidence_refs=['cie-title','snomed-term','site','note'])])
        result=explain_candidate(CID,None,items,transport=lambda _:dict(content=json.dumps(raw)))
        self.assertEqual(result['status'],'explanation_available')
        self.assertEqual(len(result['analysis']['quotes']),4)

    def test_local_schema_keeps_mandatory_anchor_prefixes_for_all_lengths(self):
        items = evidence() + [dict(id='site',type='SNOMED',concept_id=CID,role='finding_site',text='hígado')]
        refs=response_schema(CID,None,items)['properties']['claims']['items']['properties']['evidence_refs']
        for branch in refs['anyOf']:
            self.assertEqual([x['enum'][0] for x in branch['items'][:2]],['cie-title','snomed-term'])
            self.assertEqual(branch['minItems'],branch['maxItems'])

    def test_external_transport_accepts_expanded_prose_without_a_paid_call(self):
        from io import StringIO
        from cie10.openai_explanation import OpenAITransport
        from cie10.explanation_limits import EXTERNAL_MAX_OUTPUT_TOKENS
        raw=dict(concept_id=CID,assessment='compatible',additional_detail_needed=[],claims=[dict(text=p,evidence_refs=['cie_title','snomed_term']) for p in PARAGRAPHS])
        class Opener:
            def open(self,request,timeout):
                self.payload=json.loads(request.data)
                return StringIO(json.dumps(dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(raw))])],usage={})))
        opener=Opener()
        remote=OpenAITransport('test-only-token','mock-model',opener=opener)
        result=explain_candidate(CID,None,evidence(),transport=remote,prompt_renderer=lambda text,_:text,generation_method='openai_model')
        self.assertEqual(result['status'],'explanation_available')
        self.assertGreater(len(result['analysis']['justification'].split()),70)
        self.assertEqual(opener.payload['max_output_tokens'],EXTERNAL_MAX_OUTPUT_TOKENS)
        refs=opener.payload['text']['format']['schema']['properties']['claims']['items']['properties']['evidence_refs']
        self.assertNotIn('anyOf',refs)
        self.assertIsInstance(refs['items'],dict)

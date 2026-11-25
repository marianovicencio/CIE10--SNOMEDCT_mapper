import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from cie10.openai_explanation import OpenAITransport, OpenAIError, load_config, provider_schema, normalize_api_key
from cie10.candidate_explanation import generation_setup, explain_candidate
from cie10.explanation_service import run_explanation

CID='123456789'
ITEMS=[dict(id='cie-title',type='CIE10',role='title',text='Afección documentada'),
       dict(id='snomed-term',type='SNOMED',role='candidate_term',concept_id=CID,text='Afección documentada')]
KEY='test-key-for-mocked-transport-only'


class Opener:
    def __init__(self, response):self.response=response;self.requests=[]
    def open(self, request, timeout):
        self.requests.append((request,timeout))
        if isinstance(self.response,Exception):raise self.response
        return io.BytesIO(json.dumps(self.response).encode())


def response(content):
    return dict(status='completed',model='gpt-6.1-terra',usage=dict(input_tokens=100,output_tokens=50,total_tokens=150),
                output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(content))])])


def valid():
    return dict(concept_id=CID,assessment='compatible',additional_detail_needed=[],claims=[
        dict(text='El título CIE-10 y el candidato SNOMED comparten la descripción documentada.',evidence_refs=['cie_title','snomed_term'])])


class OpenAIIntegrationTests(unittest.TestCase):
    def test_transport_uses_fixed_endpoint_store_false_and_no_local_chat_markers(self):
        opener=Opener(response(valid()));remote=OpenAITransport(KEY,'gpt-6.1-terra',opener)
        result=explain_candidate(CID,None,ITEMS,transport=remote,prompt_renderer=lambda p,_:p,generation_method='openai_model')
        self.assertEqual(result['generation_method'],'openai_model')
        req,timeout=opener.requests[0];body=json.loads(req.data)
        self.assertEqual(req.full_url,'https://api.openai.com/v1/responses')
        self.assertFalse(body['store']);self.assertNotIn('tools',body);self.assertNotIn('<start_of_turn>',body['input'])
        self.assertNotIn(KEY,body['input']);self.assertEqual(len(remote.usage),1)
        self.assertEqual(result['analysis']['evidence_refs'],['cie-title','snomed-term'])

    def test_provider_schema_does_not_mutate_common_schema_and_local_checks_remain(self):
        schema,_=generation_setup(CID,None,ITEMS);before=copy.deepcopy(schema)
        adapted=provider_schema(schema)
        self.assertEqual(schema,before)
        refs=adapted['properties']['claims']['items']['properties']['evidence_refs']
        self.assertNotIn('uniqueItems',refs);self.assertNotIn('enum',refs)
        self.assertIn('cie_title',refs['items']['enum'])
        value=valid();value['claims'][0]['evidence_refs']=['snomed_term']
        remote=OpenAITransport(KEY,'gpt-6.1-terra',Opener(response(value)))
        result=explain_candidate(CID,None,ITEMS,transport=remote,prompt_renderer=lambda p,_:p)
        self.assertEqual(result['status'],'explanation_rejected')

    def test_http_error_does_not_disclose_response_or_credentials(self):
        error=HTTPError('https://api.openai.com/v1/responses',401,KEY,{},io.BytesIO(KEY.encode()))
        remote=OpenAITransport(KEY,'gpt-6.1-terra',Opener(error))
        with self.assertRaises(OpenAIError) as caught:remote(dict(prompt='Datos',json_schema={}))
        self.assertNotIn(KEY,str(caught.exception))
        self.assertIn('clave',str(caught.exception))
        self.assertTrue(error.fp.closed)

    def test_incomplete_and_refusal_are_not_accepted(self):
        for value in [dict(status='incomplete',output=[]),dict(status='completed',output=[dict(type='message',content=[dict(type='refusal',refusal='No')])])]:
            with self.subTest(value=value):
                remote=OpenAITransport(KEY,'gpt-6.1-terra',Opener(value))
                with self.assertRaises(OpenAIError):remote(dict(prompt='Datos',json_schema={}))

    def test_external_consent_is_required_before_retrieving_or_sending_data(self):
        with patch('cie10.explanation_service.prepare_evidence') as prepare:
            with self.assertRaises(ValueError):run_explanation(dict(provider='openai'))
            prepare.assert_not_called()

    def test_config_requires_private_permissions_and_no_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'credential.json';p.write_text(json.dumps(dict(api_key=KEY,model='gpt-6.1-terra')));p.chmod(0o600)
            self.assertEqual(load_config(p),(KEY,'gpt-6.1-terra'))
            p.chmod(0o644)
            with self.assertRaises(OpenAIError):load_config(p)
            p.chmod(0o600);link=Path(directory)/'link';link.symlink_to(p)
            with self.assertRaises(OpenAIError):load_config(link)

    def test_external_context_limit_prevents_network_calls(self):
        opener=Opener(response(valid()));remote=OpenAITransport(KEY,'gpt-6.1-terra',opener)
        with self.assertRaises(OpenAIError):remote(dict(prompt='x'*60001,json_schema={}))
        self.assertEqual(opener.requests,[])

    def test_local_documentary_exclusion_never_sends_a_paid_request(self):
        items=[dict(id='e',type='CIE10',role='exclusion',inherited=False,text='Pelvis renal (C65)'),
               dict(id='s',type='SNOMED',role='finding_site',concept_id=CID,text='Pelvis renal')]
        result=explain_candidate(CID,None,items,transport=lambda _:self.fail('Remote call'))
        self.assertEqual(result['analysis']['assessment'],'incompatible')


    def test_service_openai_path_does_not_start_gpu_and_reports_model_and_usage(self):
        manual=dict(id='manual',type='CIE10',role='manual_instruction',volume=2,text='Orientación documental.',
                    scope='morbidity',section='3',title='Orientación',requires_case_context=False,
                    contains_worked_examples=False,provenance='Tomo 2',record_ids=[])
        items=copy.deepcopy(ITEMS)
        items[1]['text']='Descripción alternativa de la afección'
        remote=OpenAITransport(KEY,'gpt-6.1-terra',Opener(response(valid())))
        with patch('cie10.explanation_service.prepare_evidence',return_value=items), \
             patch('cie10.explanation_service.build_manual_context',return_value=([manual],{})), \
             patch('cie10.explanation_service.build_index_context',return_value=([],{})), \
             patch('cie10.explanation_service.load_config',return_value=(KEY,'gpt-6.1-terra')), \
             patch('cie10.explanation_service.OpenAITransport',return_value=remote), \
             patch('cie10.explanation_service.model_server') as gpu:
            result=run_explanation(dict(provider='openai',external_consent=True,concept_id=CID,source_snapshot_sha256='a'*64))
        gpu.assert_not_called()
        self.assertEqual(result['generation_method'],'openai_model')
        self.assertEqual(result['provider'],'openai')
        self.assertEqual(result['token_usage'][0]['total_tokens'],150)
        self.assertNotIn(KEY,json.dumps(result))


    def test_key_clipboard_wrappers_are_normalized_without_touching_the_token(self):
        for value in [KEY,' '+KEY+'\n','"'+KEY+'"',"'"+KEY+"'",'Bearer '+KEY,
                      'Authorization: Bearer '+KEY,'export OPENAI_API_KEY="'+KEY+'"',
                      '\ufeff'+KEY+'\u200b','\x1b[200~'+KEY+'\x1b[201~']:
            self.assertEqual(normalize_api_key(value),KEY)

    def test_validator_does_not_assume_a_specific_vendor_key_prefix(self):
        self.assertEqual(normalize_api_key('opaque-test-token-123456'), 'opaque-test-token-123456')
        self.assertEqual(normalize_api_key('sk-proj-'+'x'*1500),'sk-proj-'+'x'*1500)

    def test_bad_key_diagnostics_never_echo_the_received_secret(self):
        for value in ['',KEY+' suffix',KEY+'\nsecond-line',KEY+'\x1b',KEY+'…',KEY+'****','short']:
            with self.subTest(kind='invalid_input'):
                with self.assertRaises(OpenAIError) as caught:normalize_api_key(value)
                self.assertNotIn(KEY,str(caught.exception))

    def test_loader_uses_the_same_key_normalization_as_the_assistant(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'credential.json'
            p.write_text(json.dumps(dict(api_key='"'+KEY+'"',model='gpt-6.1-terra')));p.chmod(0o600)
            self.assertEqual(load_config(p)[0],KEY)


if __name__=='__main__':unittest.main()

class LiteralProviderTests(unittest.TestCase):
 def test_literal_identity_does_not_bypass_external_consent(self):
  from cie10.candidate_explanation import ExplanationError
  with patch('cie10.explanation_service.prepare_evidence') as prepare, patch('cie10.explanation_service.OpenAITransport') as paid:
   with self.assertRaises(ExplanationError):
    run_explanation(dict(provider='openai',external_consent=False,concept_id=CID,source_snapshot_sha256='a'*64))
   prepare.assert_not_called()
   paid.assert_not_called()

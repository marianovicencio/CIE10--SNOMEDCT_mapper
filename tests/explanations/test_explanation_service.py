import unittest
import socket
from unittest.mock import patch
from cie10.explanations.candidate_explanation import ExplanationError
from cie10.explanations.explanation_service import (
    VERSION,
    prepare_evidence,
    run_explanation,
    check_model_port,
)


MANUAL_STUB = dict(id='manual-test',type='CIE10',volume=2,role='manual_convention',section='3.1.2',title='Convención',scope='classification_usage',requires_case_context=False,contains_worked_examples=False,text='Convención documental.',provenance='Volumen 2',record_ids=['v2-test'])



class EvidencePreparationTests(unittest.TestCase):
    def setUp(self):
        self.request = dict(code='C64', concept_id='188250002', diagnostic_text='Texto original',
                            source_snapshot_sha256='a' * 64, target_version=VERSION)
        self.doc = dict(source_snapshot_sha256='a' * 64, title='Tumor renal',
                        classification=dict(subdivisions=[dict(text='Subdivisión')],
                                            reference=dict(source='Volumen 1')),
                        tabular=dict(exclusions=[dict(text='Pelvis renal(es) (C65)', inherited=False,
                                                     references=[dict(source='Página 198')])]))
        self.lookup = dict(parameter=[dict(name='version', valueString=VERSION),
                           dict(name='display', valueString='Neoplasia de riñón'),
                           dict(name='property', part=[dict(name='code', valueCode='363698007'),
                                dict(name='value', valueCode='25990002'),
                                dict(name='description', valueString='estructura de la pelvis renal')])])

    def test_evidence_retains_scope_sources_and_original_input(self):
        with patch('cie10.explanations.explanation_service.get_json', return_value=self.doc), patch('cie10.explanations.explanation_service.SnowstormFHIR') as fhir:
            fhir.return_value.get.return_value = self.lookup
            result = prepare_evidence(self.request)
            fhir.return_value.lookup_active.assert_called_once_with('188250002')
        self.assertEqual(result[0]['text'], 'Tumor renal — Subdivisión')
        exclusion = next(item for item in result if item.get('role') == 'exclusion')
        self.assertIs(exclusion['inherited'], False)
        self.assertEqual(exclusion['provenance'], 'Página 198')
        self.assertEqual(result[-1]['text'], 'Texto original')
        self.assertEqual(result[-1]['type'], 'INPUT')
        self.assertTrue(any(item.get('role') == 'finding_site' for item in result))

    def test_stale_snapshot_fails_before_snomed_or_model(self):
        with patch('cie10.explanations.explanation_service.get_json', return_value={**self.doc, 'source_snapshot_sha256': 'b' * 64}), patch('cie10.explanations.explanation_service.SnowstormFHIR') as fhir:
            with self.assertRaises(ExplanationError):
                prepare_evidence(self.request)
            fhir.assert_not_called()

    def test_wrong_returned_edition_is_rejected(self):
        self.lookup['parameter'][0]['valueString'] = 'another-edition'
        with patch('cie10.explanations.explanation_service.get_json', return_value=self.doc), patch('cie10.explanations.explanation_service.SnowstormFHIR') as fhir:
            fhir.return_value.get.return_value = self.lookup
            with self.assertRaises(ExplanationError):
                prepare_evidence(self.request)

    def test_anatomical_exclusion_does_not_start_model(self):
        with patch('cie10.explanations.explanation_service.get_json', return_value=self.doc), patch('cie10.explanations.explanation_service.SnowstormFHIR') as fhir, patch('cie10.explanations.explanation_service.model_server') as model, patch('cie10.explanations.explanation_service.build_manual_context', return_value=([MANUAL_STUB], {})), patch('cie10.explanations.explanation_service.build_index_context', return_value=([], {})):
            fhir.return_value.get.return_value = self.lookup
            result = run_explanation(self.request)
            model.assert_not_called()
        self.assertIsNone(result['analysis'])
        self.assertEqual(result['documentary_constraint']['assessment'], 'incompatible')
        self.assertEqual(result['generation_method'], 'blocked_by_documentary_constraint')
        self.assertEqual(result['scope'], 'tabular_manual_index_and_snomed')
        self.assertEqual(result['status'], 'explanation_unavailable')


class ModelPortTests(unittest.TestCase):
    def test_live_listener_is_still_rejected(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0))
            server.listen()
            with self.assertRaises(ExplanationError):
                check_model_port(server.getsockname()[1])

    def test_recently_closed_connection_allows_restart(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
            server.listen()
            with socket.create_connection(('127.0.0.1', port)) as client:
                connection, _ = server.accept()
                connection.shutdown(socket.SHUT_RDWR)
                connection.close()
                self.assertEqual(client.recv(1), b'')
        check_model_port(port)


if __name__ == '__main__':
    unittest.main()

class TransientReadTests(unittest.TestCase):
 def test_transient_timeout_retries_once(self):
  from cie10.explanations.explanation_service import get_json
  from io import StringIO
  with patch('cie10.explanations.explanation_service.urlopen',side_effect=[TimeoutError(),StringIO('{"ok":true}')]) as transport,patch('cie10.explanations.explanation_service.time.sleep'):
   self.assertEqual(get_json('http://local'),{'ok':True});self.assertEqual(transport.call_count,2)
 def test_invalid_json_is_not_silently_retried(self):
  from cie10.explanations.explanation_service import get_json
  from io import StringIO
  with patch('cie10.explanations.explanation_service.urlopen',return_value=StringIO('invalid')) as transport:
   with self.assertRaises(ValueError):get_json('http://local')
   self.assertEqual(transport.call_count,1)

class RepeatedSnomedPropertiesTests(unittest.TestCase):
    def setUp(self):
        fixture=EvidencePreparationTests();fixture.setUp()
        self.request,self.doc,self.lookup=fixture.request,fixture.doc,fixture.lookup
    def test_identical_relationship_occurrences_share_one_evidence_id(self):
        from copy import deepcopy
        self.lookup['parameter'].append(deepcopy(self.lookup['parameter'][-1]))
        with patch('cie10.explanations.explanation_service.get_json', return_value=self.doc), patch('cie10.explanations.explanation_service.SnowstormFHIR') as fhir:
            fhir.return_value.get.return_value=self.lookup
            items=prepare_evidence(self.request)
        ids=[x['id'] for x in items]
        self.assertEqual(len(ids),len(set(ids)))
        site=next(x for x in items if x.get('role')=='finding_site')
        self.assertEqual(site['source_occurrences'],2)


class SelectedProviderGenerationTests(unittest.TestCase):
    """A grammatical match must reach the selected provider, retaining validators."""
    def run_provider(self, provider, invalid=False):
        import json
        from contextlib import nullcontext
        from cie10.explanations.candidate_explanation import explain_candidate
        request = dict(code='C22.3', concept_id='109844006', source_snapshot_sha256='a'*64,
                       target_version=VERSION, provider=provider, external_consent=True)
        evidence = [dict(id='cie-title', type='CIE10', role='title', text='Angiosarcoma del hígado'),
                    dict(id='snomed-term', type='SNOMED', role='candidate_term', concept_id='109844006', text='angiosarcoma de hígado')]
        prompts = []
        prose = ('CIE-10 y el candidato SNOMED comparten angiosarcoma y localización hepática; la contracción del no cambia esos términos.'
                 if provider == 'local' else
                 'El candidato SNOMED coincide con CIE-10 en angiosarcoma de hígado; la diferencia de artículos conserva la afección y la localización.')
        def transport(body):
            prompts.append(body['prompt'])
            if invalid:return dict(content='invalid response')
            return dict(content=json.dumps(dict(concept_id='109844006', assessment='compatible',
                claims=[dict(text=prose,evidence_refs=['cie_title','snomed_term'])],additional_detail_needed=[])))
        def execute(*args, **kwargs):
            if provider == 'local':kwargs['transport'] = transport
            return explain_candidate(*args, **kwargs)
        remote = unittest.mock.Mock(side_effect=transport)
        remote.usage = []
        with patch('cie10.explanations.explanation_service.prepare_evidence', return_value=evidence), \
             patch('cie10.explanations.explanation_service.build_manual_context', return_value=([dict(MANUAL_STUB)], {})), \
             patch('cie10.explanations.explanation_service.build_index_context', return_value=([], {})), \
             patch('cie10.terminology.terminology_alignment.configured_components', side_effect=lambda root, req, ev:(ev, {})), \
             patch('cie10.explanations.explanation_service.model_server', return_value=nullcontext()) as local, \
             patch('cie10.explanations.explanation_service.fit_model_evidence', side_effect=lambda cid, diag, ev, endpoint:(ev, {})), \
             patch('cie10.explanations.explanation_service.load_config', return_value=('test-key-not-a-secret','test-model')) as config, \
             patch('cie10.explanations.explanation_service.OpenAITransport', return_value=remote), \
             patch('cie10.explanations.explanation_service.explain_candidate', side_effect=execute):
            result = run_explanation(request)
        if invalid:
            self.assertEqual(len(prompts),3 if provider == "local" else 2)
            self.assertIsNone(result['analysis'])
            self.assertEqual(result['status'],'explanation_rejected')
            self.assertEqual(len(result['errors']),3 if provider == 'local' else 2)
            self.assertNotEqual(result['generation_method'],'conservative_documentary_fallback')
            return result
        self.assertEqual(len(prompts),1)
        self.assertIn('automatic_label_comparison',prompts[0])
        self.assertIn('grammatical',prompts[0])
        self.assertEqual(result['analysis']['justification'],prose)
        self.assertEqual(result['generation_method'],provider+'_model' if provider=='openai' else 'local_model')
        self.assertEqual(result['provider'],provider)
        self.assertEqual(result['attempts'],1)
        self.assertNotEqual(result['automatic_comparison']['text'],prose)
        self.assertNotIn('no demuestra por sí sola',result['automatic_comparison']['text'])
        self.assertEqual(local.call_count,1 if provider=='local' else 0)
        self.assertEqual(config.call_count,1 if provider=='openai' else 0)
        return result

    def test_local_model_receives_grammatical_match(self):self.run_provider('local')
    def test_external_model_receives_grammatical_match(self):self.run_provider('openai')

    def test_local_failure_returns_no_template_explanation(self):self.run_provider('local',invalid=True)
    def test_external_failure_returns_no_template_explanation(self):self.run_provider('openai',invalid=True)

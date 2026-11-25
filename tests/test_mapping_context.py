import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, unquote, urlsplit
from unittest.mock import patch

from cie10 import context_api
from cie10.common import write_json, write_jsonl
from cie10.mapping_context import ContextError, MappingContextClient, focus_context, messages_for, validate_mapping_input
from cie10.mapping_context import digest


def source(volume, page):
    return {'volume': volume, 'source_file': f'vol{volume}.pdf',
            'source_sha256': str(volume) * 64, 'pdf_page': page,
            'printed_page': str(page), 'line_id': 1, 'bbox': [1, 2, 3, 4]}


class MappingContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        data = cls.root / 'data/processed/full'
        write_json(data / 'manifest.json', {'sources': {'edition': '2018'}})
        write_jsonl(data / 'vol1_tabular.jsonl', [
            {'id': 'parent', 'kind': 'code', 'code': 'C76', 'description': 'Padre', 'sources': [source(1, 1)],
             'review_status': 'source_verified', 'exclusions': [{'text': 'Sitio no especificado (C80.–)', 'source': source(1, 1)}]},
            {'id': 'child', 'kind': 'code', 'code': 'C76.4', 'description': 'Miembro superior', 'parent_code': 'C76',
             'sources': [source(1, 2)], 'ancestor_refs': ['parent'], 'review_status': 'source_verified',
             'applicable_note_refs': [{'record_id': 'parent', 'fields': ['exclusions'], 'scope': 'subordinate_codes', 'sources': [source(1, 1)]}]}])
        write_jsonl(data / 'vol2_specific_notes.jsonl', [
            {'id': f'v2-note-{i}', 'kind': 'manual_specific_instruction', 'scope': 'mortality' if i == 0 else 'morbidity',
             'text': f'Regla completa {i}. Excepción preservada.', 'sources': [source(2, i + 1)],
             'subject_code_expressions': ['C76'], 'code_references': []} for i in range(4)])
        write_jsonl(data / 'vol3_index_diseases.jsonl', [
            {'id': 'v3-index', 'kind': 'index_entry', 'term_path': ['Tumor', 'mano NCOP #'],
             'text': 'Tumor de mano NCOP #', 'sources': [source(3, 5)], 'code_references': ['C76.4'],
             'usable_as_synonym': False}])
        write_jsonl(data / 'vol3_index_conventions.jsonl', [
            {'id': 'v3-convention', 'kind': 'index_convention', 'text': 'Ver no es equivalencia.',
             'sources': [source(3, 1)], 'code_mentions_are_examples': True}])
        with patch.object(context_api, 'ROOT', cls.root):
            db = context_api.build_database()['database']
        cls.store = context_api.ContextStore(Path(db))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def transport(self, path):
        parsed = urlsplit(path)
        if parsed.path.startswith('/v1/records/'):
            return self.store.record(unquote(parsed.path.split('/v1/records/', 1)[1]))
        query = parse_qs(parsed.query)
        return self.store.context(unquote(parsed.path.split('/v1/codes/', 1)[1]),
                                  query['scope'][0], int(query['limit'][0]), int(query['offset'][0]), 'evidence')

    def prepare(self, size=1, **request):
        return MappingContextClient(transport=self.transport, page_size=size).prepare({'code': 'C76.4', **request})

    def test_all_pages_and_sources_are_merged_without_local_id_collisions(self):
        pack = self.prepare()
        retrieval = pack['context']['retrieval']
        self.assertEqual(retrieval['page_count'], 5)
        self.assertEqual(retrieval['selected_records'], 5)
        self.assertEqual(len(pack['audit']['source_locations']), 8)
        for i in range(4):
            ref = pack['audit']['records'][f'v2-note-{i}']['sources'][0]['source_ref']
            self.assertEqual(pack['audit']['source_locations'][ref]['pdf_page'], i + 1)
        self.assertEqual(retrieval['general_conventions_retrieved'], 1)

    def test_compaction_preserves_scope_inheritance_and_index_role(self):
        context = self.prepare()['context']
        reading = context['documentary_context']
        self.assertEqual(len(reading['tabular']['exclusions']), 1)
        self.assertEqual(reading['tabular']['exclusions'][0]['origin'], 'C76')
        self.assertTrue(reading['tabular']['exclusions'][0]['inherited'])
        self.assertEqual(reading['index_context'][0]['matches'][0]['role'], 'index_explicit_reference')
        self.assertFalse(reading['index_context'][0]['usable_as_synonym'])
        self.assertEqual({x['scope'] for x in reading['manual_context']}, {'mortality', 'morbidity'})
        self.assertEqual(context['tabular_origin_scopes'][0]['scope'], 'subordinate_codes')

    def test_scope_filter_and_optional_original_unicode_diagnosis(self):
        text = '  Diagnóstico 🩺 sin detalles.  '
        context = self.prepare(scope='morbidity', diagnostic_text=text)['context']
        self.assertNotIn('mortality', {x['scope'] for x in context['documentary_context']['manual_context']})
        self.assertEqual(context['input_evidence']['i:diagnostic_text']['text'], text)
        self.assertEqual(context['input_evidence']['i:diagnostic_text']['end'], len(text))
        self.assertEqual(context['input_mode'], 'code_with_diagnostic_text')

    def test_change_of_snapshot_and_cycle_are_rejected(self):
        for problem in ('snapshot', 'cycle', 'missing'):
            def broken(path):
                page = self.transport(path)
                if 'offset=1' in path:
                    if problem == 'snapshot': page['source_snapshot_sha256'] = 'f' * 64
                    elif problem == 'cycle': page['pagination']['next_offset'] = 1
                    else: page['context_links'] = []
                return page
            with self.subTest(problem=problem), self.assertRaises(ContextError):
                MappingContextClient(transport=broken, page_size=1).prepare({'code': 'C76.4'})

    def test_api_without_snapshot_is_not_silently_accepted(self):
        def old(path):
            page = self.transport(path)
            page.pop('source_snapshot_sha256')
            return page
        with self.assertRaises(ContextError):
            MappingContextClient(transport=old).prepare({'code': 'C76.4'})

    def test_full_context_is_independent_of_page_size(self):
        a = self.prepare(1)['context']
        b = self.prepare(200)['context']
        self.assertEqual(a['documentary_context'], b['documentary_context'])
        self.assertEqual(a['evidence'], b['evidence'])

    def test_focus_keeps_whole_items_and_declares_selection(self):
        pack = self.prepare()['context']
        selected = focus_context(pack, '¿Qué dice mano NCOP #?', max_items=1)
        self.assertIn('mano NCOP #', selected['documentary_context']['index_context'][0]['term'])
        self.assertEqual(selected['context_selection']['coverage'], 'selected_evidence_not_all_retrieved_context')
        self.assertEqual(len(pack['documentary_context']['manual_context']), 4)
        prompt = messages_for(selected, '¿Qué dice mano NCOP #?')
        self.assertNotIn('"expected":', prompt[1]['content'])

    def test_baseline_does_not_receive_rubric_or_full_context(self):
        prompt = messages_for(self.prepare()['context'], '¿Qué excluye?', 'title_only')
        data = json.loads(prompt[1]['content'])['data']
        self.assertEqual(data['evidence'], {})
        self.assertNotIn('tabular', data)
        self.assertNotIn('expected', data)








if __name__ == '__main__':
    unittest.main()

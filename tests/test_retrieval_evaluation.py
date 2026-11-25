import json
from pathlib import Path
import tempfile
import unittest

from cie10.retrieval_evaluation import (concept_ranking, load_dataset, metrics,
    prepare_proxy, run, sha256, write_json, write_jsonl, LexicalRetriever)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root/'source.jsonl'
        write_jsonl(self.source, [
            {'id': 'r-a', 'kind': 'code', 'code': 'A00', 'description': 'Enfermedad alfa',
             'inclusions': [{'text': 'Nombre alternativo alfa', 'source': {'pdf_page': 1}}],
             'exclusions': [{'text': 'Exclusión que no es un término positivo'}]},
            {'id': 'r-b', 'kind': 'code', 'code': 'B00', 'description': 'Enfermedad beta',
             'inclusions': [{'text': 'Nombre alternativo beta', 'source': {'pdf_page': 2}}]},
            {'id': 'note', 'kind': 'note', 'description': 'No es un concepto'}])
        self.dataset = self.root/'dataset'
        prepare_proxy(self.source, self.dataset)

    def tearDown(self):
        self.temp.cleanup()

    def test_proxy_uses_only_direct_inclusion_membership_and_preserves_sources(self):
        meta, aliases, cases = load_dataset(self.dataset)
        self.assertFalse(meta['snomed_mapping_evaluation'])
        self.assertEqual(len(aliases), 2)
        self.assertEqual({c['source_record'] for c in cases}, {'r-a', 'r-b'})
        self.assertTrue(all(c['provenance'][0]['pdf_page'] in (1, 2) for c in cases))
        self.assertNotIn('Exclusión', json.dumps(cases))

    def test_aliases_do_not_occupy_multiple_concept_positions(self):
        rows = [{'concept_id': 'a', 'term': 'alfa'}, {'concept_id': 'a', 'term': 'alias'},
                {'concept_id': 'b', 'term': 'beta'}]
        ranked = concept_ranking(rows, [.7, .9, .8], 2)
        self.assertEqual([r['concept_id'] for r in ranked], ['a', 'b'])
        self.assertEqual(ranked[0]['term'], 'alias')

    def test_ties_are_deterministic_and_nonfinite_scores_fail(self):
        rows = [{'concept_id': 'b', 'term': 'b'}, {'concept_id': 'a', 'term': 'a'}]
        self.assertEqual(concept_ranking(rows, [1, 1], 2)[0]['concept_id'], 'a')
        with self.assertRaises(ValueError):
            concept_ranking(rows, [float('nan'), 1], 2)

    def test_dataset_tampering_is_rejected_before_model_loading(self):
        with (self.dataset/'catalog.jsonl').open('a') as f:
            f.write('{}\n')
        with self.assertRaisesRegex(ValueError, 'cambió'):
            load_dataset(self.dataset)

    def test_expected_concept_must_be_in_the_same_eligible_catalog(self):
        cases = [{'id': 'x', 'query': 'consulta', 'expected_ids': ['absent']}]
        write_jsonl(self.dataset/'cases.jsonl', cases)
        meta = json.loads((self.dataset/'dataset.json').read_text())
        meta['sha256']['cases.jsonl'] = sha256(self.dataset/'cases.jsonl')
        write_json(self.dataset/'dataset.json', meta)
        with self.assertRaisesRegex(ValueError, 'fuera'):
            load_dataset(self.dataset)

    def test_metrics_separate_hits_multi_target_recall_and_unlabelled(self):
        cases = [{'id': 'x', 'expected_ids': ['a', 'b']}, {'id': 'y', 'expected_ids': []}]
        result = metrics([{'case_id': 'x', 'candidates': [{'concept_id': 'a'}]},
                          {'case_id': 'y', 'candidates': []}], cases, (1,))
        self.assertEqual(result['hit_at']['1'], 1)
        self.assertEqual(result['recall_at']['1'], .5)
        self.assertEqual(result['unlabelled_cases'], 1)
        self.assertIsNone(metrics([], [], (1,))['mrr'])

    def test_lexical_handles_accents_and_no_overlap_without_fake_matches(self):
        aliases = [{'concept_id': 'a', 'term': 'Hipertensión arterial'},
                   {'concept_id': 'b', 'term': 'Enfermedad renal'}]
        engine = LexicalRetriever(aliases)
        ranked = engine.search(['hipertension arterial', 'zzzzzz'], 5)
        self.assertEqual(ranked[0][0]['concept_id'], 'a')
        self.assertEqual(ranked[1], [])

    def test_runs_preserve_rankings_provenance_and_never_overwrite(self):
        output = self.root/'run'
        result = run(self.dataset, output, top_k=5)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['mapping_endpoint_implemented'])
        self.assertEqual(sha256(output/'rankings.jsonl'), result['rankings_sha256'])
        self.assertTrue((output/'results.md').exists())
        with self.assertRaises(ValueError):
            run(self.dataset, output)


if __name__ == '__main__':
    unittest.main()

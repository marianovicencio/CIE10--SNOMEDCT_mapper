import unittest
from collections import Counter
from cie10.common import ROOT, read_json
from cie10.processing.extract import normalize_page_record
from cie10.processing.volume2.manual_specific import specific_notes

class SpecificNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=ROOT/'data/interim/full/vol2'
        if not folder.exists():raise unittest.SkipTest('Requiere la extracción completa local verificada.')
        cls.pages=[normalize_page_record(read_json(folder/f'page_{n:04d}.json')) for n in list(range(161,166))+list(range(187,201))]
        cls.records=specific_notes(cls.pages)
    def test_complete_counts_and_scopes(self):
        self.assertEqual(len(self.records),70)
        self.assertEqual(Counter(r['kind'] for r in self.records)['manual_worked_example'],28)
        mortality=[r for r in self.records if r['kind']=='manual_specific_instruction' and r['scope']=='mortality']
        self.assertEqual(len(mortality),7)
        self.assertTrue(all(r['coding_context']=='multiple_causes_of_death' for r in mortality))
    def test_no_line_loss_or_duplication_inside_reviewed_sections(self):
        expected=[]
        for p in self.pages:
            for l in p['lines']:
                n=p['pdf_page'];i=l['id']
                if n==161 and i>=32 or 162<=n<=163 or n==164 and i<=18 or n==187 and i>=27 or 188<=n<=199:expected.append((n,i))
        actual=[(s['pdf_page'],s['line_id']) for r in self.records for s in r['sources']]
        self.assertEqual(Counter(actual),Counter(expected))
        self.assertEqual(len(actual),len(set(actual)))
    def test_hiv_example_and_general_guidance_do_not_merge(self):
        example=next(r for r in self.records if r.get('example_number')==3)
        self.assertEqual(example['sources'][-1]['pdf_page'],189)
        self.assertEqual(example['sources'][-1]['line_id'],5)
        note=next(r for r in self.records if r['id']=='v2-p189-l6-specific')
        self.assertIn('decisión',note['text']);self.assertNotIn('Ejemplo 3:',note['text'])
    def test_printed_I_heading_typos_remain_literal(self):
        note=next(r for r in self.records if r['id']=='v2-p195-l15-specific')
        self.assertTrue(note['text'].startswith('115.–'))
        self.assertEqual(note['subject_code_expressions'],['I15.–'])
        self.assertIn('printed_heading_typo_preserved',note['warnings'])
    def test_consecutive_headers_share_the_following_instruction(self):
        note=next(r for r in self.records if r['id']=='v2-p191-l6-specific')
        self.assertEqual(note['subject_code_expressions'],['C80','C80.0','C80.9'])
        note=next(r for r in self.records if r['id']=='v2-p193-l7-specific')
        self.assertEqual(note['subject_code_expressions'],['E64.–','E68'])
    def test_obstetric_intervals_and_neonatal_exception_preserved(self):
        note=next(r for r in self.records if r['id']=='v2-p162-l13-specific')
        self.assertIn('42 días',note['text']);self.assertIn('un año o más',note['text'])
        note=next(r for r in self.records if r['id']=='v2-p162-l26-specific')
        self.assertIn('menos de 28',note['text'].replace('menores de 28','menos de 28'))
        self.assertIn('primera semana',note['text']);self.assertIn('A33',note['text'])

if __name__=='__main__':unittest.main()

"""Literal source, scope, alternatives and cell preservation for reviewed routes."""
import copy,json,unittest
from cie10.common import ROOT,read_jsonl,read_json
from cie10.index_remission_review import reviewed_remission
from cie10.volume3_special import bind_reviewed_table_wraps
from cie10.parse import parse_index
from cie10.extract import normalize_page_record
from tests.test_vol3_continuations import fixture_page


class SingleLetterAddressTests(unittest.TestCase):
    def test_wrapped_letter_is_content(self):
        page=fixture_page(10,[('Infección',True,28),('– suero – ver Hepatitis, viral, tipo,',False,28),('B',False,35)])
        rows=parse_index([page],'diseases')
        self.assertIn('tipo, B',rows[-1]['text'])
        self.assertEqual([s['line_id'] for s in rows[-1]['sources']],[2,3])

    def test_bold_alphabet_divider_does_not_complete_address(self):
        page=fixture_page(10,[('Infección',True,28),('– suero – ver Hepatitis, viral, tipo,',False,28),('B',True,35)])
        self.assertNotIn('tipo, B',parse_index([page],'diseases')[-1]['text'])

    def test_single_letter_after_ordinary_term_is_not_appended(self):
        page=fixture_page(10,[('Nombre,',True,28),('B',False,35)])
        self.assertEqual(len(parse_index([page],'diseases')[0]['sources']),1)


@unittest.skipUnless((ROOT/'data/processed/full/vol3_remissions.jsonl').is_file(),'Full data unavailable')
class ReviewedRemissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows={}
        for p in (ROOT/'data/processed/full').glob('vol3*.jsonl'):
            cls.rows.update((r['id'],r) for r in read_jsonl(p))
        cls.ledger=read_json(ROOT/'cie10/volume3_remission_review.json')

    def edge(self,source):
        return next(e for e in self.rows[source]['remissions'] if e.get('documentary_review',{}).get('review_complete'))

    def test_all_140_are_reviewed_and_retained(self):
        count=0
        for d in self.ledger['decisions']:
            for source in d['source_ids']:
                e=self.edge(source);count+=1
                self.assertEqual(e['target_text'],d['printed_target_text'])
                self.assertFalse(e['implies_clinical_equivalence'])
        self.assertEqual(count,140)

    def test_perinatal_abo_keeps_fetal_scope(self):
        e=self.edge('v3-p44-l10')
        self.assertEqual(e['target_id'],'v3-p45-l75')
        self.assertIn('feto o recién nacido',self.rows[e['target_id']]['term_path'])
        self.assertTrue(e['requires_case_context'])

    def test_spastic_subtypes_are_options_not_a_default(self):
        e=self.edge('v3-p407-l119')
        self.assertIsNone(e['target_id']);self.assertEqual(len(e['target_ids']),6)
        self.assertEqual(e['navigation_selector']['option_refs'],e['target_ids'])
        self.assertFalse(e['navigation_selector']['automatic_code_selection'])
        self.assertEqual({c for i in e['target_ids'] for c in self.rows[i]['code_references']},{'G80.0','G80.1','G80.2'})

    def test_two_labium_rows_remain_distinct(self):
        e=self.edge('v3-p562-table-y2648')
        self.assertEqual(e['target_ids'],['v3-p559-table-y1306','v3-p559-table-y2134'])
        self.assertTrue(e['table_selector']['row_selection_required'])
        self.assertEqual([self.rows[i]['cells']['malignant_primary']['text'] for i in e['target_ids']],['C00.4','C00.3'])

    def test_metadata_requires_site(self):
        e=self.edge('v3-p542-l115')
        self.assertEqual(e['table_selector']['candidate_columns'],['benign'])
        self.assertTrue(e['table_selector']['anatomic_site_or_substance_required'])
        self.assertTrue(e['documentary_review']['source_scope_conflict'])

    def test_wrong_source_edition_does_not_apply_review(self):
        source=copy.deepcopy(self.rows['v3-p44-l10'])
        source['sources'][0]['source_sha256']='different'
        edge={'target_text':'Afecciones originadas en el período perinatal, isoinmunización, ABO','resolution':'unresolved'}
        reviewed_remission(edge,source,self.rows)
        self.assertEqual(edge['resolution'],'unresolved');self.assertNotIn('documentary_review',edge)

    def test_changed_destination_hierarchy_requires_new_review(self):
        targets=dict(self.rows);targets['v3-p45-l75']=copy.deepcopy(targets['v3-p45-l75'])
        targets['v3-p45-l75']['term_path']=['Madre','ABO']
        edge={'target_text':'Afecciones originadas en el período perinatal, isoinmunización, ABO','resolution':'unresolved'}
        reviewed_remission(edge,self.rows['v3-p44-l10'],targets)
        self.assertEqual(edge['resolution'],'unresolved');self.assertNotIn('documentary_review',edge)

    def test_bad_printed_direction_stays_unresolved(self):
        e=self.edge('v3-p407-l1')
        self.assertEqual(e['target_text'],'Paresoa');self.assertEqual(e['resolution'],'unresolved')
        self.assertTrue(e['documentary_review']['review_complete'])

    def test_neoplasm_wrap_preserves_both_physical_rows_and_blank_cells(self):
        a,b=[copy.deepcopy(self.rows[i]) for i in ['v3-p545-table-y4509','v3-p545-table-y4601']]
        values=[r['cells'] for r in (a,b)];text=[r['raw_term'] for r in (a,b)]
        result=bind_reviewed_table_wraps([a,b])
        self.assertEqual(len(result),2);self.assertEqual([r['cells'] for r in result],values)
        self.assertEqual([r['raw_term'] for r in result],text)
        self.assertEqual(b['continuation_of'],a['id']);self.assertEqual(b['term_path'],a['term_path'])

    def test_hepatitis_letter_and_its_evidence_are_recovered(self):
        page=normalize_page_record(read_json(ROOT/'data/interim/full/vol3/page_0307.json'))
        row=next(r for r in parse_index([page],'diseases') if r['id']=='v3-p307-l66')
        self.assertIn('tipo, B',row['text']);self.assertIn(67,[s['line_id'] for s in row['sources']])
        e=self.edge(row['id']);self.assertEqual(e['resolution'],'unresolved')
        self.assertEqual(e['printed_target_text'],'Hepatitis, viral, tipo, B')


if __name__=='__main__':unittest.main()

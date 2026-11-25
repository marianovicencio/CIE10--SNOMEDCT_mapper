import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from cie10.api import context_api as api
from cie10.common import write_json, write_jsonl
from cie10.processing.volume3.volume3_special import resolve_remissions, independent_cell_references
from cie10.processing.volume3.index_documentary import repair_joined_entries
from cie10.api.context_readable import unwrap, readable_context

SOURCE={'volume':1,'source_file':'original.pdf','source_sha256':'a'*64,'pdf_page':1,'printed_page':'1','line_id':1,'bbox':[1,2,3,4],'column':None}
def record(identifier,code=None,**extra):
    return {'id':identifier,'kind':'code' if code else 'context','sources':[SOURCE],
            'warnings':[],'review_status':'pending',**({'code':code} if code else {}),**extra}

class ContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        folder=cls.root/'data/processed/full'
        write_json(folder/'manifest.json',{'sources':{'edition':'2018'}})
        rows=[record('parent','C76',exclusions=[{'text':'Exclusión del padre','source':SOURCE}]),
              record('child','C76.4',description='Tumor maligno del miembro superior',ancestor_refs=['parent'],applicable_note_refs=[{'record_id':'parent','fields':['exclusions'],'scope':'subordinate_codes','sources':[SOURCE]}]),
              record('abortion','O06',description='Aborto no especificado',code_structure={'shared_suffixes':['.1']},subdivision_scheme_refs=['scheme']),
              record('scheme',subdivision_table={'rows':[{'suffix':'.1','text':'Hemorragia','sources':[SOURCE]}]})]
        write_jsonl(folder/'vol1_tabular.jsonl',rows)
        write_jsonl(folder/'vol2_specific_notes.jsonl',[
            record('mortality',kind='manual_specific_instruction',scope='mortality',subject_code_expressions=['C76'],code_references=['C76']),
            record('morbidity',kind='manual_specific_instruction',scope='morbidity',subject_code_expressions=['C76'],code_references=['C76']),
            record('example',kind='manual_worked_example',scope='morbidity',subject_code_expressions=[],code_references=['C76.4'])])
        write_jsonl(folder/'vol3_index_diseases.jsonl',[record('index',kind='index_entry',code_references=['C76.4'],remissions=[{'target_id':'target','resolution':'resolved_exact'}]),record('target',kind='index_entry',code_references=[])])
        with patch.object(api,'ROOT',cls.root): result=api.build_database()
        cls.store=api.ContextStore(Path(result['database']))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_parent_exclusion_preserves_origin(self):
        response=self.store.evidence_context('C76.4')
        exclusion=next(n for n in response['effective_tabular_notes'] if n['origin_record_id']=='parent')
        self.assertTrue(exclusion['inherited']);self.assertEqual(exclusion['origin_code'],'C76')
        self.assertEqual(exclusion['fields']['exclusions'][0]['text'],'Exclusión del padre')
    def test_definition_context_is_local_and_rendered_once(self):
        evidence=self.store.evidence_context('C76.4')
        block={'id':'fracture-definition','title':'Fracturas, inclusive:',
            'scope':'injury_type_definition','declared_code_ranges':['S00–S99'],
            'automatic_applicability':False,'sources':evidence['records']['parent']['sources'],
            'inclusions':[],'exclusions':[{'text':'fractura patológica (M84.4)'}],
            'notes':[],'definition_groups':[{'prefix':'Fractura abierta','members':['compuesta'],
                'shared_qualifier':'con o sin retardo en la consolidación'}]}
        origin={'origin_record_id':'parent','origin_code':'C76','inherited':True,
                'scope':'documentary_context_only','fields':{'definition_blocks':[block]}}
        evidence['effective_tabular_notes'].extend([origin,origin])
        response=readable_context(evidence)
        definitions=response['tabular']['general_context']
        self.assertEqual(len(definitions),1)
        self.assertEqual(definitions[0]['exclusions'],['fractura patológica (M84.4)'])
        self.assertFalse(definitions[0]['automatic_applicability'])
        self.assertFalse(any('M84.4' in x['text'] for x in response['tabular']['exclusions']))
    def test_morbidity_does_not_receive_mortality_rule(self):
        response=self.store.evidence_context('C76.4','morbidity')
        ids={l['record_id'] for l in response['context_links']}
        self.assertIn('morbidity',ids);self.assertIn('index',ids);self.assertNotIn('mortality',ids)
    def test_example_is_never_instruction_subject(self):
        response=self.store.evidence_context('C76.4')
        links=[l for l in response['context_links'] if l['record_id']=='example']
        self.assertEqual([l['role'] for l in links],['example_mention'])
    def test_source_compaction_and_resolved_dependency(self):
        response=self.store.evidence_context('C76.4')
        self.assertIn('target',response['records'])
        self.assertEqual(len(response['source_locations']),1)
        self.assertEqual(response['records']['child']['sources'],[{'source_ref':'s1'}])
        self.assertEqual(response['documents']['vol1']['sha256'],'a'*64)
    def test_shared_subdivision_without_invented_heading(self):
        response=self.store.evidence_context('O06.1')
        self.assertEqual(response['classification']['representation'],'shared_subdivision')
        self.assertEqual(response['classification']['heading_refs'],['abortion'])
        self.assertEqual(response['classification']['shared_subdivision_rows'][0][0]['row']['text'],'Hemorragia')
        self.assertIn('scheme',response['records'])
    def test_code_suggestions_filter_prefix_and_include_shared_subdivisions(self):
        suggestions = self.store.suggest_codes('c76.')
        self.assertEqual(suggestions, [{'code': 'C76.4', 'title': 'Tumor maligno del miembro superior'}])
        self.assertEqual(self.store.suggest_codes('C', limit=1)[0]['code'], 'C76')
        self.assertEqual(self.store.suggest_codes('O06.'), [
            {'code': 'O06.1', 'title': 'Aborto no especificado — Hemorragia'}
        ])
        self.assertEqual(self.store.suggest_codes('Z99'), [])
        with self.assertRaises(ValueError):
            self.store.suggest_codes('C%')
        with self.assertRaises(ValueError):
            self.store.suggest_codes('C', limit=51)

    def test_invalid_and_nonexistent_codes(self):
        with self.assertRaises(ValueError):self.store.evidence_context('../../etc/passwd')
        with self.assertRaises(KeyError):self.store.evidence_context('C76.99')
        with self.assertRaises(ValueError):self.store.evidence_context('C76.4',limit=201)
    def test_pagination_reports_incomplete(self):
        r=self.store.evidence_context('C76.4',limit=1)
        self.assertFalse(r['pagination']['complete']);self.assertEqual(r['pagination']['next_offset'],1)
        self.assertEqual(len({l['record_id'] for l in r['context_links']}),1)
    def test_exact_sibling_does_not_match(self):
        low,high,_=api.expression_bounds('C76.3')
        self.assertFalse(low<='C76.4'<=high)
        low,high,_=api.expression_bounds('C74.–')
        self.assertTrue(low<='C74.1'<=high);self.assertFalse(low<='C75.1'<=high)
        self.assertIsNone(api.expression_bounds('Y18.–Y14.–'))
    def test_table_bindings_keep_columns_and_ambiguity(self):
        r=record('drug',cells={'accidental':{'text':'X44.–'},'undetermined':{'text':'Y18.–Y14.–','review_status':'source_ambiguity_preserved','candidate_code_expressions':['Y18.–','Y14.–']}})
        links=api.bindings('vol3_drug_table',r)
        self.assertIn(('X44.–','table_column:accidental'),links)
        self.assertIn(('Y14.–','ambiguous_table_candidate:undetermined'),links)
    def test_abortion_bindings_use_the_actual_suffix(self):
        r=record('table',cells={'incomplete':{'text':'.1','code_family':'O03–O06','category_scope':['O03','O04','O05','O06']}})
        self.assertIn(('O06.1','table_column:incomplete'),api.bindings('vol3_abortion_table',r))
    def test_readable_default_keeps_inheritance_and_audit_access(self):
        r=self.store.context('C76.4')
        self.assertEqual(r['view'],'readable')
        exclusion=r['tabular']['exclusions'][0]
        self.assertEqual(exclusion['text'],'Exclusión del padre')
        self.assertTrue(exclusion['inherited']);self.assertEqual(exclusion['origin'],'C76')
        self.assertEqual(exclusion['references'][0]['detail_url'],'/v1/records/parent')
        self.assertNotIn('source_locations',r)
        self.assertIn('view=evidence',r['evidence_url'])
        self.assertIn('source_locations',self.store.context('C76.4',view='evidence'))
        with self.assertRaises(ValueError):self.store.context('C76.4',view='unknown')
    def test_readable_retains_example_role_and_scope(self):
        r=self.store.context('C76.4',scope='morbidity')
        self.assertFalse(any(m['scope']=='mortality' for m in r['manual_context']))
        example=next(m for m in r['manual_context'] if m['kind']=='manual_worked_example')
        self.assertEqual(example['matches'][0]['role'],'example_mention')
    def test_intro_examples_do_not_bind_to_every_code(self):
        self.assertEqual(api.bindings('vol3_index_conventions',record('intro',code_references=['A00–T98'])),[])
    def test_physical_wraps_preserve_lists_exceptions_and_code_families(self):
        text='Tumores malig-\nnos de origen\ndesconocido.\n• glándula\nsuprarrenal (C74.–)\nExcepción: no se aplica\nsi el origen se conoce.'
        self.assertEqual(unwrap(text),'Tumores malignos de origen desconocido.\n• glándula suprarrenal (C74.–)\nExcepción: no se aplica si el origen se conoce.')
        self.assertEqual(unwrap('C00-C97\nC74.-\nB21.- o B22.7'), 'C00-C97 C74.- B21.- o B22.7')
        self.assertEqual(unwrap('(d)\n2\nOtra afección.'),'(d)\n2 Otra afección.')
    def test_association_exception_and_subject_are_never_discarded(self):
        evidence=self.store.evidence_context('C76.4')
        evidence['records']['association']=record('association',kind='manual_rule_block_candidate',scope='mortality',subject_code_expressions=['A00-B99'],text='Cuando se informa como la causa de:\nC00-C97, codifique en C00-C97;\nExcepción: VIH, codifique en\nB21.- o B22.7.',selection_context={'step':'M1'})
        evidence['context_links'].append({'record_id':'association','matched_expression':'C00-C97','role':'association_condition'})
        r=readable_context(evidence)
        rule=next(m for m in r['manual_context'] if m['kind']=='manual_rule_block_candidate')
        self.assertEqual(rule['subject_code_expressions'],['A00-B99'])
        self.assertIn('Excepción: VIH, codifique en B21.- o B22.7.',rule['text'])
        self.assertEqual(rule['selection_context']['step'],'M1')
    def test_priority_and_probable_sex_are_not_changed_to_hard_rules(self):
        evidence=self.store.evidence_context('C76.4')
        evidence['records']['v2-annex']=record('v2-annex',kind='manual_code_fact_candidate',sex='female',hard_exclusion=False,sex_constraint_type='limited_or_more_likely_not_disambiguated_by_source',priority=6,priority_order='1_is_highest')
        evidence['context_links'].append({'record_id':'v2-annex','matched_expression':'C76.4','role':'annex_entry'})
        row=next(m for m in readable_context(evidence)['manual_context'] if m['kind']=='manual_code_fact_candidate')
        self.assertFalse(row['hard_exclusion']);self.assertEqual(row['priority_order'],'1_is_highest')
        self.assertEqual(row['sex'],'female');self.assertEqual(row['priority'],6)
    def test_transport_preserves_victim_and_collision_direction(self):
        evidence=self.store.evidence_context('C76.4')
        evidence['records']['v3-transport']=record('v3-transport',kind='transport_matrix_row',victim_mode='Peatón')
        evidence['context_links'].append({'record_id':'v3-transport','matched_expression':'V01.–','role':'transport_collision:pedal_cycle'})
        row=next(m for m in readable_context(evidence)['index_context'] if m['kind']=='transport_matrix_row')
        self.assertEqual(row['victim_mode'],'Peatón');self.assertEqual(row['matched_columns'],['pedal_cycle'])
    def test_table_header_is_read_in_row_order_without_truncating_words(self):
        evidence=self.store.evidence_context('C76.4')
        for key,box in [('left',[1,1,20,10]),('right',[20,1,40,10]),('next',[1,12,40,21])]:
            evidence['source_locations'][key]={'document_ref':'vol1','pdf_page':1,'bbox':box}
        evidence['records']['header']=record('header',kind='special_table_metadata',header_fragments=[{'text':'1. Los tum','source':{'source_ref':'left'}},{'text':'se clasifican.','source':{'source_ref':'next'}},{'text':'ores malignos','source':{'source_ref':'right'}}])
        row=next(m for m in readable_context(evidence)['shared_context'] if m['kind']=='special_table_metadata')
        self.assertEqual(row['text'],'1. Los tumores malignos se clasifican.')

    def test_neoplasm_marker_survives_a_physical_line_break(self):
        evidence=self.store.evidence_context('C76.4')
        for key,box in [('a',[1,1,80,10]),('b',[1,12,80,21]),('symbol',[15,17,30,26])]:
            evidence['source_locations'][key]={'document_ref':'vol1','pdf_page':1,'bbox':box}
        evidence['records']['header']=record('header',kind='special_table_metadata',table='neoplasm',header_fragments=[
            {'text':'3. Sitios marcados con el','source':{'source_ref':'a'}},
            {'text':'signo (p. ej. isquion ) deben codificarse.','source':{'source_ref':'b'}},
            {'text':'♢ ♢','source':{'source_ref':'symbol'}}])
        row=next(m for m in readable_context(evidence)['shared_context'] if m['kind']=='special_table_metadata')
        self.assertEqual(row['text'],'3. Sitios marcados con el signo ♢ (p. ej. isquion ♢) deben codificarse.')

class RemissionTests(unittest.TestCase):
    def test_two_parenthetical_remissions_are_separate(self):
        r=record('p',text='Parahemofilia (ver también Defecto, coagulación) (ver también Paresoa) D68.2',term_path=['Parahemofilia'])
        edges=resolve_remissions([r])
        self.assertEqual([e['target_text'] for e in edges],['Defecto, coagulación','Paresoa'])
        self.assertFalse(any(e['implies_clinical_equivalence'] for e in edges))
    def test_contextual_lookup_is_not_a_missing_disease(self):
        r=record('p',text='Uveal – ver estado patológico',term_path=['Uveal'])
        edge=resolve_remissions([r])[0]
        self.assertEqual(edge['resolution'],'contextual_instruction');self.assertIsNone(edge['target_id'])
        self.assertTrue(edge['requires_case_context'])
    def test_table_reference_requires_existing_table_metadata(self):
        def row():return record('p',text='Lesión – ver Tabla de medicamentos y productos químicos',term_path=['Lesión'])
        self.assertEqual(resolve_remissions([row()])[0]['resolution'],'unresolved')
        metadata=[record('v3-p654-drug-metadata')]
        edge=resolve_remissions([row()],table_metadata=metadata)[0]
        self.assertEqual(edge['resolution'],'resolved_table_instruction')
        self.assertTrue(edge['requires_case_context'])
    def test_code_column_boundary_never_creates_a_range(self):
        self.assertEqual(independent_cell_references({'poisoning':'T50.9–','accidental':'X44.–'}),['T50.9','X44.–'])
    def test_joined_main_entries_and_child_parent(self):
        r=record('v3-p398-l10',text='Oligemia – ver Anemia Oligergasia – ver Retraso, mental Oligoastrocitoma, mixto',term_fragment='joined',depth=0,ancestors=[],term_path=['joined'])
        child=record('child',text='– sitio',term_fragment='sitio',depth=1,ancestors=['joined'],term_path=['joined','sitio'])
        rows=repair_joined_entries([r,child])
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[-1]['term_path'],['Oligoastrocitoma, mixto','sitio'])
        self.assertEqual(rows[0]['text'],'Oligemia – ver Anemia')

if __name__=='__main__':unittest.main()

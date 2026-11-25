import unittest
from cie10.common import ROOT, read_json
from cie10.processing.extract import normalize_page_record
from cie10.processing.parse import parse_index
from cie10.processing.volume3.volume3_special import resolve_remissions, _key, parse_drug_table
from cie10.processing.volume3.index_structure import review_source_hierarchy
from .test_vol3_continuations import fixture_page
from .test_vol3_special import fixture

class ClosureTests(unittest.TestCase):
    def edge(self, target_text, targets):
        source=fixture('Raíz – ver '+target_text,['Raíz'],'source')
        return resolve_remissions([source]+targets)[0]

    def test_nested_nonessential_modifiers_do_not_leave_a_suffix(self):
        self.assertEqual(_key('miocardio (agudo (28 días) o menos)'), 'miocardio')

    def test_main_headword_beats_a_secondary_comma_form(self):
        primary=fixture('Tumor',['Tumor'],'primary')
        secondary=fixture('Brenner, tumor de',['Brenner, tumor de'],'secondary')
        self.assertEqual(self.edge('Tumor',[primary,secondary])['target_id'],'primary')

    def test_explicit_alternative_keeps_specific_qualifiers_separate(self):
        plain=fixture('aguda o subaguda',['Bronquitis','aguda o subaguda'],'plain')
        specific=fixture('neumocócica, aguda o subaguda',['Bronquitis','neumocócica, aguda o subaguda'],'specific')
        self.assertEqual(self.edge('Bronquitis, aguda',[plain,specific])['target_id'],'plain')

    def test_optional_printed_plural_is_a_documentary_address(self):
        target=fixture('Adherencia(s)',['Adherencia(s)','peritoneo'],'target')
        edge=self.edge('Adherencias, peritoneo',[target])
        self.assertEqual(edge['target_id'],'target')
        self.assertFalse(edge['implies_clinical_equivalence'])

    def test_no_spelling_or_clinical_guess(self):
        target=fixture('Arteriosclerosis',['Arteriosclerosis'],'target')
        edge=self.edge('Arterioesclerosis',[target])
        self.assertEqual(edge['resolution'],'unresolved')
        self.assertIsNone(edge['target_id'])

    def test_missing_selector_is_not_an_exact_destination(self):
        target=fixture('Hernia',['Hernia'],'target')
        edge=self.edge('Hernia, por sitio, gangrenosa',[target])
        self.assertEqual(edge['resolution'],'resolved_contextual_navigation')
        self.assertTrue(edge['requires_case_context'])
        self.assertEqual(edge['navigation_selector']['instruction_literal'],'por sitio, gangrenosa')
        self.assertNotIn('code_references',target)

    def test_unknown_modifier_remains_unresolved_even_with_an_anchor(self):
        target=fixture('Hernia',['Hernia'],'target')
        edge=self.edge('Hernia, inventada',[target])
        self.assertEqual(edge['resolution'],'unresolved')
        self.assertIsNone(edge['target_id'])
        self.assertFalse(edge['partial_navigation']['is_complete_resolution'])

    def test_malignant_selector_does_not_choose_primary_or_secondary(self):
        row=fixture('– piel',['Tumor (de)','piel'],'table')
        row['kind']='neoplasm_table_row'
        edge=self.edge('Tumor, piel, maligno',[row])
        self.assertEqual(edge['resolution'],'resolved_table_instruction')
        self.assertEqual(edge['table_selector']['candidate_columns'],['malignant_primary','malignant_secondary'])
        self.assertTrue(edge['requires_case_context'])
        self.assertFalse(edge['implies_clinical_equivalence'])

    def test_substance_remission_does_not_choose_a_drug_column(self):
        row=fixture('Ajenjo',['Ajenjo'],'table');row['kind']='drug_table_row'
        row['cells']={'poisoning_chapter_xix':{'text':'T62.2'},'adverse_therapeutic_use':None}
        edge=self.edge('Ajenjo',[row])
        self.assertEqual(edge['resolution'],'resolved_table_instruction')
        self.assertTrue(edge['requires_case_context'])
        self.assertTrue(edge['table_selector']['column_required_from_case_context'])
        self.assertFalse(edge['implies_clinical_equivalence'])

    def test_section_disambiguation_does_not_cross_indices(self):
        source=fixture('Raíz – ver Caída',['Raíz'],'source');source['section']='external_causes'
        a=fixture('Caída',['Caída'],'disease');a['section']='diseases'
        b=fixture('Caída',['Caída'],'external');b['section']='external_causes'
        edge=resolve_remissions([source,a,b])[0]
        self.assertEqual(edge['target_id'],'external')

    def test_code_range_keeps_the_character_instruction(self):
        edge=self.edge('E10–E14, cuarto carácter .6',[])
        self.assertEqual(edge['resolution'],'code_expression_preserved')
        self.assertEqual(edge['target_code_expressions'],['E10–E14'])
        self.assertIn('cuarto carácter .6',edge['target_text'])

    def test_note_keeps_scope_without_polluting_entry_or_stack(self):
        page=fixture_page(26,[('Adenoma – ver también Tumor, benigno',True,28),
          ('Nota – Variedades morfológicas',False,31),('con excepción de las indicadas.',False,31),
          ('– células D35.1',False,28),('– otro D35.2',False,28)])
        rows=parse_index([page],'diseases');entry,note,child,sibling=rows
        self.assertEqual(note['kind'],'index_note')
        self.assertEqual(note['scope_anchor_id'],entry['id'])
        self.assertEqual(child['ancestors'],[entry['term_fragment']])
        self.assertNotIn('Variedades',entry['term_fragment'])
        self.assertEqual(sibling['index_note_refs'],[note['id']])

    def test_continuation_preserves_omitted_intermediate_ancestor(self):
        first=fixture_page(71,[('Anomalía',True,28),('– cromosomas',False,28),
           ('– – translocación',False,28),('– – – 13 Q91.6',False,28)])
        second=fixture_page(72,[('Anomalía — continuación',True,28),
           ('– – translocación — continuación',False,28),('– – – 18 Q91.2',False,28)])
        rows=parse_index([first,second],'diseases')
        self.assertEqual(rows[-1]['ancestors'],['Anomalía','cromosomas','translocación'])
        self.assertEqual(rows[-2]['continuation_of'],rows[2]['id'])

    def test_missing_levels_do_not_turn_a_sibling_into_a_parent(self):
        p=fixture_page(25,[('Raíz',True,28),('– rama',False,28),
              ('– – – especificado A00',False,28),('– – – no especificado A01',False,28)])
        rows=parse_index([p],'diseases')
        self.assertEqual(rows[-1]['ancestors'],['Raíz','rama','[missing_ancestor]'])
        self.assertTrue(rows[-1]['hierarchy_requires_review'])

@unittest.skipUnless((ROOT/'data/interim/full/vol3/page_0026.json').is_file(), 'Full PDF cache unavailable')
class SourceClosureTests(unittest.TestCase):
    def page(self,n):
        return normalize_page_record(read_json(ROOT/f'data/interim/full/vol3/page_{n:04d}.json'))

    def test_printed_anomaly_in_dhp_is_exposed_without_inventing_a_parent(self):
        rows=parse_drug_table([self.page(690)]);review_source_hierarchy(rows)
        r=next(r for r in rows if r['id']=='v3-p690-l7')
        self.assertIn('[missing_ancestor]',r['term_path'])
        self.assertTrue(r['source_hierarchy_review']['no_parent_invented'])

    def test_unmarked_hypertension_heading_is_a_continuation(self):
        rows=parse_index([self.page(295),self.page(296)],'diseases')
        r=next(r for r in rows if r['id']=='v3-p296-l1')
        self.assertEqual(r['continuation_of'],'v3-p295-l68')

    def test_repeated_espongioblastoma_preserves_polar_primitivo(self):
        rows=parse_index([self.page(231)],'diseases')
        r=next(r for r in rows if r['id']=='v3-p231-l34')
        self.assertEqual(r['ancestors'],['Espongioblastoma','polar','primitivo'])

    def test_inline_child_in_miembro_is_recovered(self):
        rows=parse_index([self.page(371)],'diseases')
        r=next(r for r in rows if r['id']=='v3-p371-l94')
        self.assertEqual(r['ancestors'][-1],'de la familia')
        self.assertEqual(r['code_references'],['Z63.7'])

    def test_relaxant_wrapped_name_keeps_original_numeric_row(self):
        rows=parse_drug_table([self.page(751)])
        r=next(r for r in rows if r['id']=='v3-p751-l22')
        self.assertEqual(r['term_fragment'],'relajante muscular, músculo anestésico')
        self.assertEqual(r['codes_by_context']['poisoning_chapter_xix'],'T48.1')
        self.assertEqual([s['line_id'] for s in r['sources']],[22,23])
        siblings=[r for r in rows if r['id'] in ('v3-p751-l24','v3-p751-l25')]
        self.assertEqual(siblings[0]['ancestors'],siblings[1]['ancestors'])
        review_source_hierarchy(rows)
        self.assertIn('inherited_hierarchy_ambiguity',siblings[1]['warnings'])

    def test_verified_compound_abbreviation_is_limited_to_source_hash(self):
        rows=parse_index([self.page(354),self.page(355)],'diseases')
        source=fixture('Origen – ver Mala, posición, útero',['Origen'],'source')
        edge=resolve_remissions([source]+rows)[0]
        self.assertEqual(edge['target_id'],'v3-p355-l55')
        target=next(r for r in rows if r['id']=='v3-p355-l55')
        target['sources'][0]['source_sha256']='different-source'
        self.assertEqual(resolve_remissions([source]+rows)[0]['resolution'],'unresolved')

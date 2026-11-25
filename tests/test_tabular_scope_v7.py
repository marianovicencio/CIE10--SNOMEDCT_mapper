import json
import unittest
from pathlib import Path
from copy import deepcopy
from cie10.common import ROOT,read_json
from cie10.extract import normalize_page_record
from cie10.parse import parse_tabular
from cie10.tabular_geometry import geometry_pages
from cie10.tabular_definitions import normalize_definitions


class InjuryDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=read_json(ROOT/'config/sources.json')['volumes']['1']
        folder=ROOT/'data/interim/full/vol1'
        if not (folder/'page_0836.json').exists():
            raise unittest.SkipTest('Full source extraction is not available')
        pages=[normalize_page_record(read_json(folder/f'page_{n:04}.json')) for n in range(836,841)]
        cls.records=parse_tabular(geometry_pages(pages,cls.config,'full'))
        cls.chapter=next(r for r in cls.records if r['id']=='v1-p836-l1')

    def test_only_two_chapter_exclusions_are_inheritable(self):
        self.assertEqual([x['text'] for x in self.chapter['exclusions']],
            ['trauma obstétrico (O70–O71)','traumatismo del nacimiento (P10–P15)'])
        for child in (r for r in self.records if r['kind']=='code'):
            ref=next(x for x in child['applicable_note_refs'] if x['fields']==['definition_blocks'])
            self.assertEqual(ref['scope'],'documentary_context_only')

    def test_definition_source_lines_are_preserved_once(self):
        blocks=self.chapter['definition_blocks']
        self.assertEqual(len(blocks),11)
        refs=[(s['pdf_page'],s['line_id']) for b in blocks for s in b['sources']]
        self.assertEqual(len(refs),len(set(refs)))
        expected=[(s['pdf_page'],s['line_id']) for s in self.chapter['sources']
                  if (s['pdf_page'],s['line_id']) >= (837,15)]
        self.assertEqual(refs,expected)
        for b in blocks:
            self.assertFalse(b['automatic_applicability'])
            self.assertEqual(b['structure_issues'],[])

    def test_fracture_exclusions_are_local_and_full(self):
        block=next(b for b in self.chapter['definition_blocks'] if b['title']=='Fracturas, inclusive:')
        self.assertEqual(len(block['exclusions']),5)
        self.assertTrue(all(x['scope']=='injury_type_definition' for x in block['exclusions']))
        self.assertEqual(block['definition_groups'][0]['prefix'],'Fractura abierta')
        self.assertEqual(len(block['definition_groups'][1]['members']),11)
        self.assertEqual(block['inclusions'][0]['text'],'Fractura cerrada dislocada')

    def test_nested_braces_preserve_members_and_qualifiers(self):
        block=next(b for b in self.chapter['definition_blocks'] if b['title'].startswith('Luxaciones'))
        group=block['definition_groups'][0]
        self.assertEqual(len(group['members']),8)
        self.assertEqual(group['shared_qualifiers'],['cartílago','cápsula articular','ligamento'])
        organs=next(b for b in self.chapter['definition_blocks'] if b['title'].startswith('Traumatismos de órganos'))
        self.assertIn('magulladura',organs['definition_groups'][0]['members'])
        self.assertEqual(organs['definition_groups'][0]['shared_qualifier'],'de órganos internos')

    def test_changed_source_cannot_reuse_a_visual_rule(self):
        block=deepcopy(next(b for b in self.chapter['definition_blocks'] if b['title'].startswith('Luxaciones')))
        block['inclusions']=deepcopy(block['raw_note_fragments']['inclusions'])
        block.pop('definition_groups')
        block['sources'][0]['source_sha256']='different'
        normalize_definitions({'definition_blocks':[block]})
        self.assertNotIn('definition_groups',block)
        self.assertTrue(block['structure_issues'])


if __name__=='__main__':unittest.main()

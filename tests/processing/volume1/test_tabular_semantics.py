import unittest

from cie10.processing.volume1.tabular_semantics import conventions, enrich_tabular
from cie10.processing.volume1.tabular_notes import logical_notes
from .test_tabular_notes import f, CTX


def record(code, description, n=1, kind='code', **kw):
    source = f('', n=n)['source']
    return dict(id=str(n), kind=kind, code=code, description=description,
                sources=[source], raw_lines=[description], parent_code=code[:3] if code and '.' in code else None,
                symbol=kw.pop('symbol', ''), warnings=[],
                **{k: kw.get(k, []) for k in ('inclusions','exclusions','instructions','notes','unclassified')})


class SemanticsTests(unittest.TestCase):
    def test_parentheses_have_distinct_roles(self):
        result = conventions('Hipertensión (arterial) (I10)')
        self.assertEqual([x['kind'] for x in result], ['nonessential_modifier', 'code_reference'])

    def test_brackets_do_not_assert_synonym_equivalence(self):
        self.assertEqual(conventions('Lepra [enfermedad de Hansen]')[0]['kind'], 'alternative_or_explanation')
        self.assertEqual(conventions('[Ver nota 5]')[0]['kind'], 'cross_reference')

    def test_ncop_and_sai_are_different(self):
        self.assertEqual(conventions('NCOP')[0]['kind'], 'not_elsewhere_classified')
        self.assertEqual(conventions('SAI')[0]['kind'], 'unspecified')
        self.assertEqual(conventions('huesos y articulaciones', title=True)[0]['interpretation'], 'and_or')
        self.assertEqual(conventions('huesos y articulaciones'), [])

    def test_unbulleted_nested_colons_and_siblings(self):
        entries, issues = logical_notes([f('lesión:',96,100,1),f('sitio:',110,112,2),
            f('crónico',125,124,3),f('agudo',125,136,4),f('otro',110,148,5),f('independiente',96,160,6)],
            'inclusion', CTX, 'implicit_under_code_heading')
        self.assertEqual([e['text'] for e in entries], ['lesión sitio crónico','lesión sitio agudo','lesión otro','independiente'])
        self.assertFalse(issues)

    def test_hierarchy_excludes_future_and_unrelated_contexts(self):
        chapter=record(None,'Chapter (A00–B99)',1,'context', exclusions=[f('excluded')])
        group=record(None,'Group (A15–A19)',2,'context')
        parent=record('A17','Parent',3,notes=[f('parent note')])
        child=record('A17.0','Child',4)
        future=record(None,'Future (A00–B99)',5,'context')
        enrich_tabular([chapter,group,parent,child,future])
        self.assertEqual(child['ancestor_refs'], ['1','2','3'])
        self.assertEqual([n['record_id'] for n in child['applicable_note_refs']],['1','3'])

    def test_dual_codes_are_relations_not_exclusion_pairs(self):
        r=record('A17.0','Meningitis (G01*)',symbol='†',exclusions=[f('excluded (G02*)')])
        enrich_tabular([r])
        self.assertEqual(len(r['coding_relations']),1)
        pair=r['coding_relations'][0]
        self.assertEqual(pair['etiology_codes'],['A17.0†'])
        self.assertEqual(pair['manifestation_codes'],['G01*'])
        self.assertTrue(pair['manifestation_must_not_be_used_alone'])

    def test_wrapped_optional_instruction(self):
        r=record('A00','Example',instructions=[f('Use código adicional (B95)'),f('si desea identificar el agente',n=2)])
        enrich_tabular([r])
        self.assertEqual(r['coding_relations'][0]['requirement'],'optional')

    def test_note_reference_is_not_falsely_resolved(self):
        r=record('C00.8','Example',unclassified=[f('[Ver nota 5 al inicio de este capítulo]')])
        enrich_tabular([r])
        self.assertEqual(r['coding_relations'][0]['resolution'],'unresolved')
        self.assertTrue(r['semantic_review_issues'])

    def test_numbered_note_resolves_only_in_ancestor_scope(self):
        chapter=record(None,'Tumores (C00–D48)',1,'context')
        notes=record(None,'Notas',2,'context')
        notes['raw_lines'] += ['5. Sitios contiguos', 'Explicación conservada']
        r=record('C00.8','Example',3,unclassified=[f('[Ver nota 5 al inicio de este capítulo]')])
        enrich_tabular([chapter,notes,r])
        self.assertEqual(r['coding_relations'][0]['resolution'],'numbered_note_located')
        self.assertEqual(r['coding_relations'][0]['target_note_number'],5)

    def test_spaced_dagger_reference(self):
        r=record('G01','Manifestación (A17.0 †)',symbol='*')
        enrich_tabular([r])
        self.assertEqual(r['coding_relations'][0]['etiology_codes'],['A17.0†'])

    def test_table_requires_explicit_scope(self):
        scheme=record(None,'Las siguientes subdivisiones de cuarto carácter se usan con O03–O06:',1,'shared_subdivision_scheme')
        scheme['raw_lines'] += ['.0 Complicado','.1 Sin complicación']
        a=record('O03','Example',2,unclassified=[f('[Para el cuarto carácter ver antes de O03]')])
        b=record('O07','Outside',3)
        enrich_tabular([scheme,a,b])
        self.assertEqual(a['subdivision_scheme_refs'],['1'])
        self.assertNotIn('subdivision_scheme_refs',b)
        self.assertEqual(a['code_structure']['shared_suffixes'],['.0','.1'])
        self.assertEqual(a['coding_relations'][0]['resolution'],'explicit_table_located')


if __name__ == '__main__':
    unittest.main()

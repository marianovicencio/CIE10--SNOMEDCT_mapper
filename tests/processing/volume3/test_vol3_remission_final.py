"""Documentary navigation regressions; no inferred clinical recoding."""
import unittest
from cie10.processing.volume3.volume3_special import resolve_remissions, parse_drug_table
from cie10.processing.volume3.index_documentary import repair_joined_entries
from cie10.processing.volume3.index_structure import SOURCE_SHA256
from cie10.common import ROOT, read_json
from cie10.processing.extract import normalize_page_record


def entry(identifier, path, text=None, parents=(), sha=SOURCE_SHA256, page=10, codes=()):
    return dict(id=identifier,kind='index_entry',term_path=path,
        term_fragment=path[-1],text=text or path[-1],warnings=[],section='diseases',
        sources=[dict(source_sha256=sha,pdf_page=page,line_id=1)],
        code_references=list(codes),ancestor_entry_refs=list(parents),
        ancestors=path[:-1],depth=len(path)-1)


class RemissionFinalTests(unittest.TestCase):
    def edge(self, text, targets=(), metadata=()):
        source=entry('source',['Source'],text)
        return resolve_remissions([source,*targets],table_metadata=metadata)[0]

    def test_qualifier_is_not_an_alternative_headword(self):
        target=entry('target',['Infección','rubéola, congénita'])
        edge=self.edge('Source – ver Infección, congénita',[target])
        self.assertEqual(edge['resolution'],'unresolved')

    def test_repeated_identical_destinations_keep_every_location(self):
        a=entry('a',['Accidente','transporte'],page=603,codes=['V99'])
        b=entry('b',['Accidente','transporte'],page=608,codes=['V99'])
        edge=self.edge('Source – ver Accidente, transporte',[a,b])
        self.assertEqual(edge['target_id'],'a')
        self.assertEqual(edge['duplicate_target_ids'],['b'])
        self.assertFalse(edge['implies_clinical_equivalence'])

    def test_repeated_heading_with_distinct_directive_is_not_coalesced(self):
        a=entry('a',['Raíz'],'Raíz – ver Destino A')
        b=entry('b',['Raíz'],'Raíz – ver Destino B')
        edge=self.edge('Source – ver Raíz',[a,b])
        self.assertEqual(edge['resolution'],'ambiguous')

    def test_parenthetical_senses_are_not_duplicates(self):
        a=entry('a',['Carbunco (absceso)'])
        b=entry('b',['Carbunco (ántrax)'])
        self.assertEqual(self.edge('Source – ver Carbunco',[a,b])['resolution'],'ambiguous')

    def test_main_heading_wins_over_flattened_child_path(self):
        a=entry('a',['Atención materna'])
        b=entry('b',['Atención','materna'])
        self.assertEqual(self.edge('Source – ver Atención materna',[a,b])['target_id'],'a')

    def test_source_is_not_preferred_over_an_actual_destination(self):
        source=entry('source',['Nombre'],'Nombre – ver Nombre')
        destination=entry('destination',['Nombre'])
        self.assertEqual(resolve_remissions([source,destination])[0]['target_id'],'destination')

    def test_accentless_and_parenthesized_also(self):
        for text in ('Source – ver tambien Destino','Source – ver (también) Destino'):
            edge=self.edge(text,[entry('target',['Destino'])])
            self.assertEqual((edge['directive'],edge['target_id']),('see_also','target'))

    def test_instruction_after_closing_parenthesis_is_separate(self):
        edge=self.edge('Source (ver también Psicosis, droga) codifique en F11–F19',
                       [entry('target',['Psicosis','droga'])])
        self.assertEqual(edge['target_text'],'Psicosis, droga')
        self.assertEqual(edge['target_id'],'target')

    def test_case_dependent_instruction_is_not_a_missing_entry(self):
        edge=self.edge('Source – ver por tipo de procedimiento')
        self.assertEqual(edge['resolution'],'contextual_instruction')
        self.assertTrue(edge['requires_case_context'])
        self.assertIsNone(edge['target_id'])

    def test_dynamic_anchor_does_not_choose_a_patient_modifier(self):
        edge=self.edge('Source – ver Atresia, por órgano',[entry('target',['Atresia'])])
        self.assertEqual(edge['resolution'],'resolved_contextual_navigation')
        self.assertTrue(edge['navigation_selector']['missing_patient_selector'])

    def test_external_note_preserves_codes_and_uncertainty(self):
        edge=self.edge('Source – ver Vol. 1, Nota 6 al inicio de V01–V99')
        ref=edge['external_document_reference']
        self.assertEqual((ref['volume'],ref['code_expressions']),(1,['V01–V99']))
        self.assertTrue(ref['exact_note_not_resolved'])
        self.assertIsNone(edge['target_id'])

    def test_next_page_table_uses_documentary_position(self):
        metadata=[dict(id='table',kind='table_metadata',sources=[dict(pdf_page=11)])]
        edge=self.edge('Source – ver tabla en la próxima página',metadata=metadata)
        self.assertEqual(edge['target_id'],'table')
        self.assertEqual(edge['resolution'],'resolved_table_instruction')

    def test_named_drug_selects_row_but_keeps_all_columns(self):
        drug=entry('lead',['Plomo']);drug.update(kind='drug_table_row',section=None,
            cells={'poisoning_chapter_xix':{'text':'T56.0'},'adverse_therapeutic_use':None})
        edge=self.edge('Source – ver Tabla de medicamentos y productos químicos, plomo',[drug])
        self.assertEqual(edge['target_id'],'lead')
        self.assertTrue(edge['table_selector']['column_required_from_case_context'])
        self.assertEqual(set(edge['table_selector']['candidate_columns']),set(drug['cells']))

    def test_reviewed_spelling_is_limited_to_this_source(self):
        for sha,expected in ((SOURCE_SHA256,'resolved_exact'),('different','unresolved')):
            source=entry('v3-p764-l29',['Trilene'],'Trilene – ver Ticloroetileno',sha=sha)
            target=entry('v3-p764-l5',['Tricloroetileno'])
            edge=resolve_remissions([source,target])[0]
            self.assertEqual(edge['resolution'],expected)
            if sha==SOURCE_SHA256:self.assertTrue(edge['documentary_review']['source_literal_preserved'])

    def test_source_alias_keeps_printed_term(self):
        root=entry('root',['Insuficiencia'])
        branch=entry('v3-p331-l15',['Insuficiencia','ventrículo, ventricular'],parents=['root'])
        leaf=entry('v3-p331-l19',['Insuficiencia','ventrículo, ventricular','izquierda'],
                   parents=['root',branch['id']])
        self.assertEqual(self.edge('Source – ver Insuficiencia, ventricular, izquierdo',[root,branch,leaf])['target_id'],leaf['id'])
        self.assertEqual(self.edge('Source – ver Insuficiencia, ventrículo, izquierdo',[root,branch,leaf])['target_id'],leaf['id'])
        self.assertEqual(self.edge('Source – ver Insuficiencia, ventricular, izquierda',[root,branch,leaf])['target_id'],leaf['id'])
        self.assertEqual(leaf['term_fragment'],'izquierda')

    def test_separate_bold_headings_keep_each_code(self):
        source=entry('v3-p612-l56',['Avalancha, víctima de Aviadores'],
            'Avalancha, víctima de X36.– Aviadores, enfermedad de los W94.–')
        rows=repair_joined_entries([source])
        self.assertEqual([r['code_references'] for r in rows],[['X36.–'],['W94.–']])
        self.assertEqual([r['term_path'] for r in rows],[['Avalancha, víctima de'],['Aviadores, enfermedad de los']])


@unittest.skipUnless((ROOT/'data/interim/full/vol3/page_0715.json').is_file(),'PDF cache unavailable')
class DrugWrapSourceTests(unittest.TestCase):
    def test_destination_at_left_margin_is_not_a_new_substance(self):
        page=normalize_page_record(read_json(ROOT/'data/interim/full/vol3/page_0715.json'))
        rows=parse_drug_table([page])
        row=next(r for r in rows if r['id']=='v3-p715-l48')
        self.assertIn('ver también Carbono, monóxido',row['text'])
        self.assertFalse(any(r['id']=='v3-p715-l50' for r in rows))
        self.assertIn(50,[s['line_id'] for s in row['sources']])


if __name__=='__main__':unittest.main()

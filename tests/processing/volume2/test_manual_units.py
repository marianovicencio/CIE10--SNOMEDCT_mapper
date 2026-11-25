import unittest
from cie10.processing.volume2.manual_units import document_units, manual_references


def page(number, texts):
    lines=[]
    for i,item in enumerate(texts,1):
        text,heading=item if isinstance(item,tuple) else (item,False)
        lines.append({'id':i,'text':text,'start_font':'Arial-ItalicMT' if heading else 'TimesNewRomanPSMT','start_size':11 if heading else 10.5,'bbox':[28,20*i,350,20*i+10],'column':None})
    return {'volume':2,'pdf_page':number,'printed_page':str(number-11),'source_file':'book.pdf','source_sha256':'a'*64,'lines':lines}


class ManualUnitTests(unittest.TestCase):
    def test_exception_and_list_survive_size_and_page_boundaries(self):
        pages=[page(145,[('4.3.5 B. Tumores malignos: Primario o secundario',True),'C00-C96','c) Otra indicación de tumor maligno primario','Texto introductorio '+('x '*750),'Codifique como primarias, a menos']),page(146,['que el certificador las especifique como secundarias.','• Otro criterio.',('C. Más de un tumor maligno primario',True),'C00-C76'])]
        units=document_units(pages)
        rule=next(r for r in units if r['section_address']=='4.3.5 B c')
        self.assertIn('a menos\nque el certificador las especifique como secundarias.',rule['text'])
        self.assertIn('• Otro criterio.',rule['text'])
        self.assertIn('C00-C96',rule['context_code_expressions'])
        all_lines=[(s['pdf_page'],s['line_id']) for r in units for s in r['sources']]
        self.assertEqual(len(all_lines),len(set(all_lines)))
        self.assertEqual(len(all_lines),sum(len(p['lines']) for p in pages))
    def test_source_gap_does_not_join_unrelated_pages(self):
        units=document_units([page(1,[('4.3.5 Tumores',True),'a menos']),page(3,['otra sección desconocida'])])
        self.assertEqual(units[0]['boundary_end'],'source_page_gap')
        self.assertIn('incomplete_unit_source_page_gap',units[0]['warnings'])
        self.assertNotIn('otra sección',units[0]['text'])
    def test_qualified_reference_selects_hiv_item_and_not_other_sequences(self):
        units=document_units([page(69,[('4.2.3 Instrucciones especiales',True),('A. Secuencias aceptadas',True),'c) Enfermedades infecciosas debidas al VIH','Otras reglas.','d) Tumores malignos y VIH','Texto de la excepción.','e) Otras afecciones','Otra regla.'])])
        refs=manual_references({'text':'Excepción: tumores enumerados en la Sección 4.2.3, A (Secuencias aceptadas, inciso d) Tumores malignos y VIH.'},units)
        self.assertEqual(refs[0]['printed_reference'],'4.2.3 A d')
        self.assertEqual(refs[0]['target_unit_refs'],[next(r['id'] for r in units if r['section_address']=='4.2.3 A d')])
    def test_broad_reference_has_section_url(self):
        units=document_units([page(69,[('4.2.3 Instrucciones especiales',True),('A. Secuencias aceptadas',True),'d) Tumores malignos y VIH','Regla completa.'])])
        ref=manual_references({'text':'Véase la Sección 4.2.3.'},units)[0]
        self.assertEqual(len(ref['target_unit_refs']),3)
        self.assertEqual(ref['section_url'],'/v1/manual/sections/4.2.3')
    def test_printed_number_conflict_never_selects_perinatal_rules(self):
        units=document_units([page(165,[('4.4.1 Certificación de muertes perinatales',True),'Texto perinatal.',('4.5.1 Orientaciones para registro',True),('Contacto con servicios de salud por razones que no son enfermedades',True),'Texto de atención.'])])
        ref=manual_references({'text':'(ver en la sección 4.4.1, Contacto con servicios de salud por razones que no son enfermedades)'},units)[0]
        self.assertEqual(ref['resolution'],'printed_number_title_conflict')
        self.assertEqual(ref['target_unit_refs'],[])
        self.assertEqual(len(ref['candidate_unit_refs']),1)
    def test_named_step_is_a_reference_target(self):
        units=document_units([page(60,[('4.1.1 Selección',True),('Paso SP8 - Afecciones poco probables de causar la muerte',True),'Regla completa.'])])
        ref=manual_references({'text':'Siga las instrucciones del Paso SP8.'},units)[0]
        self.assertEqual(ref['resolution'],'resolved_exact_address')
        self.assertEqual(ref['target_unit_refs'],[units[1]['id']])
    def test_shared_prefix_keeps_both_section_references(self):
        units=document_units([page(201,[('5.4 Primera lista',True),'Texto.',('5.5 Segunda lista',True),'Texto.'])])
        refs=manual_references({'text':'Ver las secciones 5.4 y 5.5.'},units)
        self.assertEqual([ref['printed_reference'] for ref in refs],['5.4','5.5'])
    def test_annex_and_numeric_subsection_are_addressable(self):
        units=document_units([page(244,[('7.4 Lista de afecciones',True),'Texto.',('7.4.1 Primera parte',True),'Texto.'])])
        ref=manual_references({'text':'Consulte el Anexo 7.4.'},units)[0]
        self.assertEqual(len(ref['target_unit_refs']),2)
        self.assertEqual(ref['section_url'],'/v1/manual/sections/7.4')


if __name__=='__main__':unittest.main()

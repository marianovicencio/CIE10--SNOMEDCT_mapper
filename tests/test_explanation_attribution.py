import json
import unittest
from cie10.explanation_attribution import validate_claim_attribution, validate_mapping_comparison, source_label
from cie10.candidate_explanation import explain_candidate, generation_setup, reference_aliases

ID='123456789'
ITEMS=[dict(id='title',type='CIE10',role='title',text='Tumor maligno de la pelvis renal'),
       dict(id='term',type='SNOMED',role='candidate_term',concept_id=ID,text='Neoplasia epitelial maligna de pelvis renal'),
       dict(id='input',type='INPUT',text='Neoplasia epitelial maligna de la pelvis renal.'),
       dict(id='manual',type='CIE10',volume=2,role='manual_convention',scope='classification_usage',text='Guía de especificidad.'),
       dict(id='index',type='CIE10',volume=3,role='index_entry',text='Ruta del índice.'),
       dict(id='note',type='CIE10',role='notes',text='Nota general.'),
       dict(id='site',type='SNOMED',role='finding_site',concept_id=ID,text='Pelvis renal')]
SOURCES={x['id']:x for x in ITEMS}


def raw(claims):
    return dict(concept_id=ID,assessment='compatible',claims=claims,additional_detail_needed=[])


class AttributionTests(unittest.TestCase):
    def test_claim_cannot_borrow_an_input_citation_from_another_claim(self):
        value=raw([dict(text='El diagnóstico especifica origen epitelial.',evidence_refs=['title','term']),
                   dict(text='La entrada respalda esa especificidad.',evidence_refs=['input'])])
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(value)))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_manual_and_index_citations_are_required_on_the_same_claim(self):
        for text,ref in [('La guía del manual respalda la comparación.','manual'),('La ruta del índice orienta la consulta.','index')]:
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):validate_claim_attribution(text,['title','term'],SOURCES)
                validate_claim_attribution(text,[ref],SOURCES)

    def test_snomed_attribute_cannot_be_called_cie_inclusion(self):
        with self.assertRaises(ValueError):validate_claim_attribution('La inclusión es pelvis renal.',['site','title','term'],SOURCES)

    def test_quoted_title_cannot_be_replaced_by_the_diagnostic_even_if_both_are_cited(self):
        with self.assertRaises(ValueError):
            validate_claim_attribution('El título CIE-10 dice «Neoplasia epitelial maligna de la pelvis renal».',['title','input','term'],SOURCES)
        validate_claim_attribution('El diagnóstico dice «Neoplasia epitelial maligna de la pelvis renal».',['input'],SOURCES)

    def test_title_and_term_have_separate_source_labels(self):
        self.assertNotEqual(source_label(ITEMS[0]),source_label(ITEMS[1]))
        self.assertEqual(source_label(ITEMS[2]),'Entrada del usuario')
        self.assertNotIn('Inclusión',source_label(ITEMS[-1]))

    def test_claims_form_readable_text_and_exact_quotes_without_repeated_refs(self):
        claims=[dict(text='El título y el término SNOMED concuerdan en malignidad y localización. El diagnóstico aporta el origen epitelial requerido por el candidato.',evidence_refs=['title','term','input'])]
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(raw(claims))))
        self.assertEqual(result['status'],'explanation_available')
        self.assertEqual(result['attributed_claims'],claims)
        self.assertEqual(result['analysis']['justification'],' '.join(x['text'] for x in claims))
        self.assertEqual(result['analysis']['evidence_refs'],['title','term','input'])
        self.assertEqual(result['analysis']['quotes'][0]['text'],ITEMS[0]['text'])

    def test_missing_input_still_prevents_proposing_selection(self):
        value=raw([dict(text='El título y el término SNOMED comparten localización.',evidence_refs=['title','term'])])
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(value)))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_old_detached_citation_protocol_is_rejected(self):
        value=raw([]);value.pop('claims');value.update(justification='Coinciden.',cie_evidence_refs=['title'],snomed_evidence_refs=['term'],diagnostic_evidence_ref='input')
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(value)))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_generic_clinical_caution_does_not_invent_an_input(self):
        validate_claim_attribution('Esta comparación no confirma una enfermedad en el paciente.',['title','term'],SOURCES)

    def test_claim_with_unknown_source_is_rejected(self):
        value=raw([dict(text='El diagnóstico coincide.',evidence_refs=['title','term','invented'])])
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(value)))
        self.assertEqual(result['status'],'explanation_rejected')


    def test_short_references_round_trip_to_public_source_ids(self):
        aliases=reference_aliases(ITEMS)
        schema,prompt=generation_setup(ID,ITEMS[2]['text'],ITEMS)
        self.assertIn('cie_title',schema['properties']['claims']['items']['properties']['evidence_refs']['items']['enum'])
        claims=[dict(text='El título y el término SNOMED comparten localización; el diagnóstico aporta el origen epitelial.',
                     evidence_refs=[aliases['title'],aliases['term'],aliases['input']])]
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(raw(claims))))
        self.assertEqual(result['status'],'explanation_available')
        self.assertEqual(result['attributed_claims'][0]['evidence_refs'],['title','term','input'])
        self.assertNotIn('cie_title',result['analysis']['evidence_refs'])

    def test_clinical_patient_summary_is_not_a_mapping_explanation(self):
        for text in ['El paciente presenta una neoplasia.','Esta enfermedad se caracteriza por complicaciones.']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):validate_claim_attribution(text,['title','term','input'],SOURCES)

    def test_quotation_cannot_borrow_a_real_quote_from_another_claim(self):
        with self.assertRaises(ValueError):
            validate_claim_attribution('El diagnóstico dice «Neoplasia epitelial maligna de la pelvis renal».',['title','term'],SOURCES)


    def test_code_only_mode_is_explicit_and_format_does_not_add_fictitious_clinical_values(self):
        from cie10.candidate_explanation import gemma_turn
        schema,prompt=generation_setup(ID,None,ITEMS[:2])
        self.assertIn('"has_diagnostic_text": false',prompt)
        self.assertIn('NO se recibió diagnóstico',prompt)
        rendered=gemma_turn('PRUEBA',False)
        self.assertNotIn('Afección alfa',rendered)
        self.assertNotIn('grado leve',rendered)
        self.assertEqual(rendered,gemma_turn('PRUEBA',True))

    def test_separate_title_and_snomed_summaries_do_not_explain_a_comparison(self):
        claims=[dict(text='El título establece localización.',evidence_refs=['title']),
                dict(text='El término SNOMED especifica el sitio.',evidence_refs=['term','input'])]
        result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(raw(claims))))
        self.assertEqual(result['status'],'explanation_rejected')

    def test_curly_quoted_source_misattribution_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_claim_attribution('El título CIE-10 dice ‘Neoplasia epitelial maligna de la pelvis renal’.',['title','input','term'],SOURCES)


    def test_expanded_reference_schema_retains_known_ids_and_bounded_lists(self):
        schema,_=generation_setup(ID,ITEMS[2]['text'],ITEMS)
        refs=schema['properties']['claims']['items']['properties']['evidence_refs']
        self.assertTrue({'cie_title','snomed_term','user_text'} <= set(refs['items']['enum']))
        self.assertEqual(refs['minItems'],3)
        self.assertLessEqual(refs['maxItems'],6)
        self.assertTrue(refs['uniqueItems'])

    def test_generic_definitions_and_examples_remain_auditable_but_are_not_patient_evidence(self):
        from cie10.explanation_focus import focus_evidence
        examples=[dict(id='definition',type='CIE10',role='manual_convention',volume=2,text='Términos de inclusión. Ejemplo ajeno.'),
                  dict(id='specificity',type='CIE10',role='manual_guidance',volume=2,text='Especificidad. A continuación se presentan ejemplos de diagnóstico.')]
        original=ITEMS[:3]+examples
        selected,report=focus_evidence(original)
        self.assertTrue(all(x['id'] not in {'definition','specificity'} for x in selected))
        self.assertEqual(len(original),5)
        self.assertEqual({x['id'] for x in report['omitted_items']},{'definition','specificity'})


    def test_cie_and_snomed_quotes_in_the_same_sentence_use_their_own_roles(self):
        validate_claim_attribution('El término SNOMED dice «Neoplasia epitelial maligna de pelvis renal» y el código CIE-10 dice «Tumor maligno de la pelvis renal».',['title','term','input'],SOURCES)

    def test_disease_summary_and_unsourced_physicological_definition_are_not_a_comparison(self):
        for text in ['La hipertensión se define como una presión superior a 140 mmHg.',
                     'El código CIE-10 representa diabetes mellitus tipo 2 sin complicaciones.',
                     'El código CIE-10 y el candidato SNOMED coinciden y la enfermedad se caracteriza por complicaciones.']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):validate_mapping_comparison(text)

    def test_selection_is_a_server_policy_not_a_second_model_decision(self):
        claims=[dict(text='El título CIE-10 y el candidato SNOMED comparten localización; la entrada precisa el tipo epitelial.',evidence_refs=['title','term','input'])]
        schema,_=generation_setup(ID,ITEMS[2]['text'],ITEMS)
        self.assertNotIn('selection',schema['properties'])
        for assessment,missing,expected in [('compatible',[],'proposed'),('compatible',['Precisar detalle.'],'abstained'),('undetermined',['Precisar detalle.'],'abstained'),('incompatible',[],'abstained')]:
            value=raw(claims);value.update(assessment=assessment,additional_detail_needed=missing)
            result=explain_candidate(ID,ITEMS[2]['text'],ITEMS,transport=lambda _:dict(content=json.dumps(value)))
            self.assertEqual(result['analysis']['selection'],expected)


    def test_index_cie_label_cannot_be_supported_by_a_title_or_hierarchy(self):
        text='El índice CIE10 respalda la comparación entre CIE-10 y SNOMED.'
        with self.assertRaises(ValueError):validate_claim_attribution(text,['title','term'],SOURCES)
        validate_claim_attribution(text,['index'],SOURCES)


if __name__=='__main__':unittest.main()

from copy import deepcopy
import unittest

from cie10.context_readable import Reader
from cie10.mapping_context import ContextError, digest
from cie10.retrieval_queries import (check_token_budget, pointer_get, prepare_queries,
                                     queries_for_encoding, render_queries)


def pack(shared=False, diagnostic=None, inclusions=None):
    code = 'E10.7' if shared else 'C76.0'
    title = 'Diabetes mellitus tipo 1' if shared else 'Tumor maligno de la cabeza, cara y cuello'
    source = {'source_ref':'loc'}
    includes = inclusions if inclusions is not None else ['Mejilla SAI','Nariz SAI']
    record = {'id':'r','kind':'code','code':'E10' if shared else code,'description':title,
              'sources':[source],'review_status':'pending','warnings':[]}
    fields = {'inclusions':[{'text':x,'source':source} for x in includes],
              'exclusions':[{'text':'Exclusión de prueba (C80.–)','source':source}]}
    audit = {'code':code,'edition':'2018','source_snapshot_sha256':'a'*64,
        'classification':{'heading_refs':['r'],'representation':'shared_subdivision' if shared else 'explicit_heading',
                          'shared_subdivision_rows':[]},
        'records':{'r':record},'source_locations':{'loc':{'document_ref':'vol1','pdf_page':8,'printed_page':'2'}},
        'documents':{'vol1':{'volume':1,'sha256':'b'*64}},
        'retrieval':{'all_selected_pages_retrieved':True,'selected_records':0,'total_selected_records':0},
        'pagination':{'complete':True},
        'effective_tabular_notes':[{'origin_record_id':'r','origin_code':record['code'],'inherited':shared,
                                   'fields':fields}]}
    reference = {'evidence_ref':'e:r'}
    reader = Reader(audit)
    tabular = reader.tabular()
    for name in tabular:
        for entry in tabular[name]:
            entry['references'] = [reference]
    # The real consumer replaces Reader URLs with compact evidence references.
    # Adapt Reader output in this fixture using an equivalent reference method.
    classification = {'representation':audit['classification']['representation'],'reference':reference}
    if shared:
        audit['records']['scheme'] = {'id':'scheme','kind':'subdivision_scheme','sources':[source]}
        audit['classification']['shared_subdivision_rows'] = [[{'scheme_ref':'scheme',
            'row':{'suffix':'.7','text':'Con complicaciones múltiples','sources':[source]}}]]
        classification['subdivisions'] = [{'suffix':'.7','text':'Con complicaciones múltiples'}]
    request = {'code':code,'scope':'all','top_k':10}
    context = {'input':request,'input_mode':'code_only','source_snapshot_sha256':'a'*64,
        'retrieval':deepcopy(audit['retrieval']),
        'documentary_context':{'code':code,'edition':'2018','title':title,'classification':classification,
            'tabular':tabular,'manual_context':[{'text':'Regla mortalidad C00–C97'}],
            'index_context':[{'term':'Demencia urémica','usable_as_synonym':False}],
            'shared_context':[],'general_conventions':[]},
        'tabular_annotations':[],'tabular_origin_scopes':[],'quality':{},
        'evidence':{'e:r':{'record_id':'r','volume':1,'pdf_pages':[8],'source_sha256':'b'*64}}}
    if diagnostic is not None:
        context['input']['diagnostic_text'] = diagnostic
        context['input_mode'] = 'code_with_diagnostic_text'
        context['input_evidence'] = {'i:diagnostic_text':{'text':diagnostic,'start':0,'end':len(diagnostic),
            'field':'diagnostic_text','offset_unit':'unicode_code_points'}}
    context['context_sha256'] = digest(context)
    return {'context':context,'audit':audit}


def reseal(value):
    value['context'].pop('context_sha256',None)
    value['context']['context_sha256'] = digest(value['context'])


class QueryTests(unittest.TestCase):
    def test_originals_and_input_pack_remain_intact_and_sourced(self):
        p = pack(diagnostic='  Niega metástasis 🩺. Tumor en mejilla.  ')
        original = deepcopy(p)
        result = prepare_queries(p)
        self.assertEqual(p,original)
        diagnostic = next(q for q in result['queries'] if q['kind']=='diagnostic_original')
        self.assertEqual(diagnostic['text'],p['context']['input']['diagnostic_text'])
        self.assertEqual(result['evidence']['i:diagnostic_text']['end'],len(diagnostic['text']))
        for s in result['segments'].values():
            self.assertEqual(pointer_get(p[s['container']],s['pointer']),s['text'])
            self.assertTrue(all(ref in result['evidence'] for ref in s['evidence_refs']))
        self.assertTrue(all(q['patient_assertion'] is False for q in result['queries']))

    def test_exclusions_rules_and_index_mentions_never_become_positive_queries(self):
        result = prepare_queries(pack())
        texts = ' '.join(q['text'] for q in result['queries'])
        self.assertNotIn('Exclusión',texts)
        self.assertNotIn('Demencia',texts)
        self.assertNotIn('Regla mortalidad',texts)
        self.assertTrue(all(g['positive_query_source'] is False for g in result['review_context']))
        self.assertFalse(result['policy']['automatic_snomed_exclusion_filter'])

    def test_each_inclusion_is_an_alternative_with_the_complete_title(self):
        result = prepare_queries(pack())
        branches = [q for q in result['queries'] if q['kind']=='description_with_inclusion']
        self.assertEqual(len(branches),2)
        self.assertTrue(all(q['text'].startswith('Tumor maligno de la cabeza, cara y cuello') for q in branches))
        self.assertFalse(any('Mejilla' in q['text'] and 'Nariz' in q['text'] for q in branches))

    def test_shared_subdivision_preserves_qualifier_and_its_own_source(self):
        result = prepare_queries(pack(shared=True))
        self.assertEqual(result['queries'][0]['text'],'Diabetes mellitus tipo 1 — Con complicaciones múltiples')
        qualifier = next(s for s in result['segments'].values() if s['role']=='shared_subdivision_qualifier')
        self.assertEqual(qualifier['evidence_refs'],['e:scheme'])
        self.assertEqual(result['evidence']['e:scheme']['pdf_pages'],[8])
        self.assertEqual(len(result['queries']),1)
        self.assertTrue(all(x['reason']=='inherited_or_other_scope_not_a_subcode_assertion' for x in result['held_inclusions_or_variants']))

    def test_incomplete_child_title_gets_a_separate_sourced_hierarchy_variant(self):
        p=pack()
        p['context']['documentary_context']['title']='Otras drogas'
        p['audit']['records']['r']['description']='Otras drogas'
        p['audit']['records']['parent']={'id':'parent','code':'C76','kind':'code',
            'description':'Envenenamiento por drogas','sources':[{'source_ref':'loc'}]}
        p['audit']['classification']['hierarchy_refs']=['parent']
        p['context']['documentary_context']['classification']['hierarchy']=[{'code':'C76','title':'Envenenamiento por drogas'}]
        reseal(p)
        result=prepare_queries(p)
        self.assertEqual(result['queries'][0]['text'],'Otras drogas')
        enriched=next(q for q in result['queries'] if q['kind']=='description_with_hierarchy')
        self.assertEqual(enriched['text'],'Envenenamiento por drogas — Otras drogas')
        self.assertIn('e:parent',result['evidence'])
        self.assertTrue(all(q['text'].startswith('Envenenamiento por drogas') for q in result['queries'] if q['kind']=='description_with_inclusion'))

    def test_dual_codes_and_ranges_are_held_not_stripped_into_synonyms(self):
        result = prepare_queries(pack(inclusions=['Demencia† (F02.8*) urémica','Con afección (C74.–)','Con complicación sin diálisis']))
        self.assertEqual(len(result['held_inclusions_or_variants']),2)
        self.assertNotIn('Demencia',' '.join(q['text'] for q in result['queries']))
        self.assertTrue(any('sin diálisis' in q['text'] for q in result['queries']))

    def test_query_budget_is_explicit_and_does_not_delete_context(self):
        p = pack()
        result = prepare_queries(p,max_queries=2)
        self.assertEqual(len(result['queries']),2)
        self.assertEqual(result['held_inclusions_or_variants'][0]['reason'],'query_budget')
        self.assertEqual(len(p['context']['documentary_context']['tabular']['inclusions']),2)

    def test_missing_pages_different_snapshots_and_focused_context_are_rejected(self):
        for problem in ('pages','snapshot','focused','suffix'):
            p = pack(shared=problem=='suffix')
            if problem=='pages':p['context']['retrieval']['all_selected_pages_retrieved']=False
            elif problem=='snapshot':p['audit']['source_snapshot_sha256']='c'*64
            elif problem=='focused':p['context']['context_selection']={'mode':'question_focused'}
            else:p['audit']['classification']['shared_subdivision_rows'][0][0]['row']['suffix']='.1'
            reseal(p)
            with self.subTest(problem=problem),self.assertRaises(ContextError):prepare_queries(p)

    def test_tampered_context_or_source_title_cannot_be_accepted(self):
        for resealed in (False,True):
            p=pack()
            p['context']['documentary_context']['title']='Tumor benigno'
            if resealed:reseal(p)
            with self.subTest(resealed=resealed),self.assertRaises(ContextError):prepare_queries(p)

    def test_long_diagnostic_is_not_silently_truncated_or_omitted(self):
        text='  Niega diálisis. 🩺\n' * 90
        result=prepare_queries(pack(diagnostic=text))
        def tokenizer(text,**kwargs):
            self.assertFalse(kwargs['truncation'])
            return {'input_ids':list(range(len(text)+2))}
        checked=check_token_budget(result,tokenizer,64,{'fixture':'character_counter'})
        self.assertFalse(checked['token_budget_check']['all_queries_fit'])
        self.assertEqual(next(q['text'] for q in checked['queries'] if q['kind']=='diagnostic_original'),text)
        with self.assertRaises(ContextError):queries_for_encoding(checked,{'fixture':'character_counter'},64)
        with self.assertRaises(ContextError):queries_for_encoding(result,{'fixture':'character_counter'},64)

    def test_checked_plan_has_reproducible_hash_and_cannot_be_modified_for_execution(self):
        result=prepare_queries(pack())
        self.assertEqual(result,prepare_queries(pack()))
        checked=check_token_budget(result,lambda text,**kw:{'input_ids':[1,2,3]},64,{'fixture':'short'})
        self.assertEqual(len(queries_for_encoding(checked,{'fixture':'short'},64)),3)
        with self.assertRaises(ContextError):queries_for_encoding(checked,{'fixture':'different'},64)
        with self.assertRaises(ContextError):queries_for_encoding(checked,{'fixture':'short'},32)
        checked['queries'][0]['text']='Cambiar significado'
        with self.assertRaises(ContextError):queries_for_encoding(checked,{'fixture':'short'},64)
        self.assertIn('no se ejecutó búsqueda SNOMED',render_queries(result))


if __name__=='__main__':
    unittest.main()
